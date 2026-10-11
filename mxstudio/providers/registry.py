"""Build providers from settings; refuse model weights whose licence is not allowed (D13)."""
from __future__ import annotations

import json
from pathlib import Path

from mxstudio.providers.base import AnthropicClaude, ComfyUIRemote, ManualExchange, OpenAICompatible, ProviderError

POLICY = Path(__file__).resolve().parents[2] / "catalog" / "licence_policy.json"


def _policy() -> dict:
    return json.loads(POLICY.read_text(encoding="utf-8"))


def model_licence_findings(model_or_workflow: str | dict) -> list[dict]:
    """Named findings for any banned model reference (patterns come from the licence policy)."""
    text = json.dumps(model_or_workflow) if isinstance(model_or_workflow, dict) else str(model_or_workflow)
    low = text.lower()
    findings = []
    for component in _policy()["banned_components"]:
        if component["id"] not in {"flux-dev"}:
            continue
        hits = [pattern for pattern in component["patterns"] if pattern in low]
        if hits:
            findings.append({"finding": "model_licence_not_allowed", "component": component["id"],
                             "reason": component["reason"], "replacement": component["replacement"], "matched": hits,
                             "ar": "الموديل ده ترخيصه غير تجاري — استخدم البديل المجاني."})
    return findings


def build_text_provider(config: dict, api_key: str | None = None):
    if not config.get("enabled"):
        raise ProviderError("text/vision provider is not configured")
    if model_licence_findings(config.get("model", "")):
        raise ProviderError("model licence not allowed")
    if config.get("kind") == "anthropic":
        if not api_key:
            raise ProviderError("set the Claude API key (secret provider.text_vision) in Settings")
        return AnthropicClaude(api_key=api_key, model=config.get("model") or "claude-opus-5-5",
                               effort=config.get("effort", "medium"))
    if config.get("kind") != "openai_compatible":
        raise ProviderError(f"unknown text provider kind {config.get('kind')!r}")
    return OpenAICompatible(base_url=config["base_url"], model=config["model"], api_key=api_key)


def build_image_provider(config: dict, workflows_dir: Path | None = None, manual_dir: Path | None = None):
    kind = config.get("kind")
    if kind == "manual":
        return ManualExchange(folder=manual_dir or Path(config.get("folder", "manual_exchange")))
    if not config.get("enabled"):
        raise ProviderError("image provider is not configured")
    if kind == "comfyui":
        workflow = config.get("workflow_graph")
        if workflow is None and workflows_dir is not None:
            workflow = json.loads((workflows_dir / f"{config.get('workflow', 'qwen_image')}.json").read_text("utf-8"))
        if workflow is None:
            raise ProviderError("no ComfyUI workflow template")
        if model_licence_findings(workflow):
            raise ProviderError("workflow references a model whose licence is not allowed")
        return ComfyUIRemote(base_url=config["base_url"], workflow=workflow)
    raise ProviderError(f"unknown image provider kind {kind!r}")
