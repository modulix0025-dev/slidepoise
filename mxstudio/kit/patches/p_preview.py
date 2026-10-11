"""P-PREVIEW — OM editor: single-slide preview export cached by content hash (flag MODULEX_MAG_PAGE_PREVIEW)."""
from __future__ import annotations

from ._editor_ext import ANCHORS, hook, payload
from .base import Patch

PATCH = Patch(
    id="P-PREVIEW",
    flag="MODULEX_MAG_PAGE_PREVIEW",
    title_ar="معاينة صفحة واحدة",
    title_en="Single-page preview",
    summary_en="GET /api/editor/mag/preview/<order>/<slide> exports one slide with OM's own export_pdf; "
               "cached under OrderManagement/mag_cache/preview by sha256(deck)+slide.",
    anchors=ANCHORS,
    hooks=(hook("MODULEX_MAG_PAGE_PREVIEW", "mag_preview"),),
    payloads=(payload("preview"),),
)
