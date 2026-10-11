"""P-SAFEZONE — OM editor: safe-zone overlay and frames crossing the safe band (flag MODULEX_MAG_SAFEZONE)."""
from __future__ import annotations

from ._editor_ext import ANCHORS, hook, payload
from .base import Patch

PATCH = Patch(
    id="P-SAFEZONE",
    flag="MODULEX_MAG_SAFEZONE",
    title_ar="منطقة الأمان في المحرر",
    title_en="Editor safe-zone overlay",
    summary_en="GET /api/editor/mag/safezone/<order> + an injected overlay script; loopback-only until "
               "MODULEX_MAG_EDITOR_AUTH names the editor's own access check.",
    anchors=ANCHORS,
    hooks=(hook("MODULEX_MAG_SAFEZONE", "mag_safezone"),),
    payloads=(payload("safezone"),),
    notes=("Face detection is not in the order path; frames crossing the safe band are reported instead.",),
)
