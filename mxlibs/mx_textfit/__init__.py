"""mx_textfit — will this text fit its box? Pure, deterministic, vendorable.

Public API:
    fit(text, box_emu, font, rules) -> {fits, verdict, size_pt, lines, overflow_pt, font_used,
                                        substitute, method, ar, en, ...}
    paragraph_box(pptx_path, "t-<slide>-<shape_id>-<para>") -> box size, insets, autofit, font
    fit_paragraph_edit(pptx_path, para_id, new_text, rules=None) -> fit() result for the edited shape
    char_limit(original_text) -> the editor's per-paragraph character cap
    FontResolver / normalize_family -> exact family-name font lookup

Dependencies: stdlib + Pillow. uharfbuzz (preferred) and fontTools are optional;
without them the result says which method measured it (``method``).
This library never writes files or state.
"""

from .fit import (
    DEFAULT_INSET_EMU,
    EDITOR_MAX_LINES,
    EDITOR_MAX_TEXT,
    EMU_PER_CM,
    EMU_PER_PT,
    MESSAGES,
    char_limit,
    fit,
    normalise_text,
    wrap,
)
from .fonts import FontFace, FontResolver, default_resolver, normalize_family
from .measure import directional_runs, has_harakat, has_rtl, measurer_for
from .pptx_box import ParagraphNotFound, fit_paragraph_edit, paragraph_box

__version__ = "1.0.0"
__all__ = [
    "DEFAULT_INSET_EMU",
    "EDITOR_MAX_LINES",
    "EDITOR_MAX_TEXT",
    "EMU_PER_CM",
    "EMU_PER_PT",
    "MESSAGES",
    "FontFace",
    "FontResolver",
    "ParagraphNotFound",
    "char_limit",
    "default_resolver",
    "directional_runs",
    "fit",
    "fit_paragraph_edit",
    "has_harakat",
    "has_rtl",
    "measurer_for",
    "normalise_text",
    "normalize_family",
    "paragraph_box",
    "wrap",
]
