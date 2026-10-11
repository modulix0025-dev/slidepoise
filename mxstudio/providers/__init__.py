"""AI providers behind small interfaces.

Defaults follow decision D13 (no commercially-licensed component): open-weight
models on the operator's own (rented) GPUs through an OpenAI-compatible
endpoint (Qwen3-VL for text/vision) and remote ComfyUI (Qwen-Image,
Qwen-Image-Edit-2511, FLUX.1 [schnell]) for images. Paid APIs remain possible
through the same OpenAI-compatible client, off until the operator adds them.
Model weights are checked against catalog/licence_policy.json before use.
"""
from mxstudio.providers.base import ImageProvider, ProviderError, TextVisionProvider
from mxstudio.providers.registry import build_image_provider, build_text_provider, model_licence_findings

__all__ = ["ImageProvider", "ProviderError", "TextVisionProvider", "build_image_provider", "build_text_provider",
           "model_licence_findings"]
