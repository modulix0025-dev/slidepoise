"""Phase 6 colour science for ModuleX Magazine Studio.

Rule for the whole package: deterministic code here *measures* (OKLab/OKLCH, contrast,
CIEDE2000, ICC CMYK, colour-vision simulation, texture) and emits facts plus *named*
findings. Only objective failures are blocking (ink limit exceeded, text contrast under a
published floor, meaning collapsing under colour-vision deficiency with no other cue).
Taste — harmony, balance, mood — is advisory, scored by the configured vision model in
:mod:`mxstudio.colour.critic`, and never blocks or publishes anything on its own.
"""
from __future__ import annotations

PACKAGE_RULE = "facts_and_named_findings_only"
