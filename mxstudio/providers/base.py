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
        payload_messages = [dict(m) for m in messages]
        if images:
            last = payload_messages[-1]
            parts = [{"type": "text", "text": str(last.get("content", ""))}]
            parts += [{"type": "image_url", "image_url": {"url": "data:image/png;base64,"
                                                          + base64.b64encode(img).decode("ascii")}} for img in images]
            last["content"] = parts
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
