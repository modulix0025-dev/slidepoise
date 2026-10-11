"""Provider interfaces. Every call returns plain data; transport errors become ProviderError."""
from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import httpx


class ProviderError(RuntimeError):
    pass


def image_media_type(data: bytes) -> str:
    if data[:4] == b"\x89PNG":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    raise ProviderError("unsupported image type (use PNG, JPEG, WebP or GIF)")


@dataclass
class AnthropicClaude:
    """Claude through the official Anthropic SDK (Messages API). Messages may carry `images` (raw bytes).

    Default model: Claude Opus 5.5. Refusal fallbacks are on (`fallbacks: "default"`), so a
    classifier decline is retried server-side on Anthropic's recommended model; a final
    refusal comes back as a plain final answer that says so.
    """
    api_key: str | None = None
    model: str = "claude-opus-5-5"
    effort: str = "medium"
    name: str = "anthropic"
    client: Any = None  # injectable for tests

    def _client(self):
        if self.client is not None:
            return self.client
        try:
            import anthropic  # noqa: PLC0415
        except ImportError as exc:
            raise ProviderError("the anthropic package is not installed") from exc
        return anthropic.Anthropic(api_key=self.api_key, max_retries=2)

    @staticmethod
    def _content(message: dict) -> str | list[dict]:
        pictures = message.get("images") or []
        if not pictures:
            return str(message.get("content", ""))
        blocks = [{"type": "image", "source": {"type": "base64", "media_type": image_media_type(img),
                                               "data": base64.standard_b64encode(img).decode("ascii")}}
                  for img in pictures]
        return blocks + [{"type": "text", "text": str(message.get("content", "")) or "(image)"}]

    def chat(self, messages: list[dict], *, images: list[bytes] | None = None, max_tokens: int = 16000,
             temperature: float | None = None) -> dict:
        system = "\n\n".join(str(m["content"]) for m in messages if m["role"] == "system")
        convo = [dict(m) for m in messages if m["role"] != "system"]
        if images and convo:
            convo[-1]["images"] = list(convo[-1].get("images") or []) + list(images)
        payload = [{"role": m["role"], "content": self._content(m)} for m in convo]
        try:
            import anthropic  # noqa: PLC0415
            api_error: type[Exception] = anthropic.APIError
        except ImportError:
            api_error = RuntimeError
        try:
            response = self._client().beta.messages.create(
                model=self.model, max_tokens=max(max_tokens, 4096), system=system or None, messages=payload,
                output_config={"effort": self.effort}, betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        except api_error as exc:
            raise ProviderError(f"anthropic: {exc}") from exc
        if response.stop_reason == "refusal":
            return {"text": json.dumps({"final": "The model declined this request; nothing was changed."}),
                    "usage": {}, "model": response.model, "refusal": True}
        text = "".join(block.text for block in response.content if block.type == "text")
        usage = response.usage
        return {"text": text, "model": response.model,
                "usage": {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens}}

    def test_connection(self) -> dict:
        try:
            info = self._client().models.retrieve(self.model)
        except Exception as exc:  # noqa: BLE001 - reported to the operator, never raised
            return {"ok": False, "ar": "مش قادر أوصل لـClaude — اتأكد من المفتاح.", "detail": str(exc)[:300]}
        return {"ok": True, "models": [info.id], "model_listed": True}


class TextVisionProvider(Protocol):
    name: str

    def chat(self, messages: list[dict], *, images: list[bytes] | None = None, max_tokens: int = 1024,
             temperature: float = 0.2) -> dict: ...

    def test_connection(self) -> dict: ...


class ImageProvider(Protocol):
    name: str

    def generate(self, prompt: str, *, width: int, height: int, references: list[bytes] | None = None,
                 seed: int | None = None) -> list[bytes]: ...

    def test_connection(self) -> dict: ...


@dataclass
class OpenAICompatible:
    """Any OpenAI-compatible chat endpoint: vLLM, LM Studio (localhost:1234), OpenRouter, DashScope…"""
    base_url: str
    model: str
    api_key: str | None = None
    timeout: float = 120.0
    name: str = "openai_compatible"
    transport: Any = None

    def _client(self) -> httpx.Client:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        return httpx.Client(base_url=self.base_url.rstrip("/"), headers=headers, timeout=self.timeout,
                            transport=self.transport)

    def chat(self, messages: list[dict], *, images: list[bytes] | None = None, max_tokens: int = 1024,
             temperature: float = 0.2) -> dict:
        payload_messages = []
        for index, message in enumerate(messages):
            pictures = list(message.get("images") or [])
            if images and index == len(messages) - 1:
                pictures += images
            if pictures:
                parts = [{"type": "text", "text": str(message.get("content", ""))}]
                parts += [{"type": "image_url", "image_url": {"url": f"data:{image_media_type(img)};base64,"
                                                              + base64.b64encode(img).decode("ascii")}}
                          for img in pictures]
                payload_messages.append({"role": message["role"], "content": parts})
            else:
                payload_messages.append({"role": message["role"], "content": message.get("content", "")})
        body = {"model": self.model, "messages": payload_messages, "max_tokens": max_tokens, "temperature": temperature}
        try:
            with self._client() as client:
                response = client.post("/v1/chat/completions", json=body)
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(f"{self.name}: {exc}") from exc
        choice = (data.get("choices") or [{}])[0]
        return {"text": (choice.get("message") or {}).get("content") or "", "usage": data.get("usage") or {},
                "model": data.get("model", self.model)}

    def test_connection(self) -> dict:
        try:
            with self._client() as client:
                response = client.get("/v1/models")
                response.raise_for_status()
                models = [m.get("id") for m in response.json().get("data", [])]
        except (httpx.HTTPError, ValueError) as exc:
            return {"ok": False, "ar": "مش قادر أوصل للموديل.", "detail": str(exc)}
        return {"ok": True, "models": models, "model_listed": self.model in models}


@dataclass
class ComfyUIRemote:
    """Remote ComfyUI: POST /prompt with a workflow template, poll /history, fetch /view."""
    base_url: str
    workflow: dict
    timeout: float = 600.0
    poll_seconds: float = 2.0
    name: str = "comfyui"
    transport: Any = None
    sleep: Any = field(default=time.sleep)

    def _client(self) -> httpx.Client:
        return httpx.Client(base_url=self.base_url.rstrip("/"), timeout=60, transport=self.transport)

    def _fill(self, prompt: str, width: int, height: int, seed: int | None) -> dict:
        """Replace placeholder values anywhere in the workflow graph (strings stay strings, numbers numbers)."""
        values = {"__PROMPT__": prompt, "__WIDTH__": int(width), "__HEIGHT__": int(height),
                  "__SEED__": int(seed if seed is not None else 0)}

        def walk(node):
            if isinstance(node, dict):
                return {key: walk(value) for key, value in node.items()}
            if isinstance(node, list):
                return [walk(value) for value in node]
            if isinstance(node, str) and node in values:
                return values[node]
            return node

        return walk(self.workflow)

    def generate(self, prompt: str, *, width: int, height: int, references: list[bytes] | None = None,
                 seed: int | None = None) -> list[bytes]:
        if references:
            raise ProviderError("reference images go through a workflow with LoadImage nodes; upload them first")
        graph = self._fill(prompt, width, height, seed)
        deadline = time.time() + self.timeout
        try:
            with self._client() as client:
                prompt_id = client.post("/prompt", json={"prompt": graph}).raise_for_status().json()["prompt_id"]
                while True:
                    history = client.get(f"/history/{prompt_id}").raise_for_status().json()
                    if prompt_id in history:
                        break
                    if time.time() > deadline:
                        raise ProviderError("ComfyUI did not finish in time")
                    self.sleep(self.poll_seconds)
                images = []
                for node in history[prompt_id].get("outputs", {}).values():
                    for image in node.get("images", []):
                        params = {"filename": image["filename"], "subfolder": image.get("subfolder", ""),
                                  "type": image.get("type", "output")}
                        images.append(client.get("/view", params=params).raise_for_status().content)
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise ProviderError(f"comfyui: {exc}") from exc
        return images

    def test_connection(self) -> dict:
        try:
            with self._client() as client:
                stats = client.get("/system_stats").raise_for_status().json()
        except (httpx.HTTPError, ValueError) as exc:
            return {"ok": False, "ar": "مش قادر أوصل لـComfyUI.", "detail": str(exc)}
        return {"ok": True, "devices": [d.get("name") for d in stats.get("devices", [])]}


@dataclass
class ManualExchange:
    """No API at all: the Studio writes the prompt into an inbox folder; the operator drops images back."""
    folder: Path
    name: str = "manual"

    def generate(self, prompt: str, *, width: int, height: int, references: list[bytes] | None = None,
                 seed: int | None = None) -> list[bytes]:
        request_id = f"{int(time.time() * 1000)}"
        folder = Path(self.folder)
        (folder / "requests").mkdir(parents=True, exist_ok=True)
        (folder / "requests" / f"{request_id}.json").write_text(
            json.dumps({"prompt": prompt, "width": width, "height": height, "seed": seed}, ensure_ascii=False),
            encoding="utf-8")
        return []

    def collect(self) -> list[Path]:
        inbox = Path(self.folder) / "responses"
        return sorted(p for p in inbox.glob("*") if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}) \
            if inbox.is_dir() else []

    def test_connection(self) -> dict:
        return {"ok": True, "folder": str(self.folder)}
