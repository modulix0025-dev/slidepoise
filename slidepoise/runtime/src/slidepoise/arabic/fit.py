"""Deterministic text fitting for Arabic, Latin and mixed copy.

Line breaks happen only at whitespace: an Arabic word is never split, because a
split breaks letter joining. A word wider than the box is an overflow fact, not
something to hide. The fitter measures and reports; whether a fit is visually
acceptable stays a reviewer's judgement.

Line height = max(Office single-line box x spacing multiple, real ink height of
the line incl. harakat + clearance). The second term is what keeps vowelised
lines from colliding.
"""
from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field

from slidepoise.arabic.fonts import FontFace, FontRegistry, default_registry
from slidepoise.arabic.shaping import font_metrics, has_harakat, has_rtl, shape

BREAKABLE_SPACE = re.compile(r"[ \t -  　]+")
HALF_POINT = 0.5


@dataclass
class FitResult:
    fits: bool
    size_pt: float
    lines: list[str]
    line_height_pt: float
    block_height_pt: float
    max_line_width_pt: float
    usable_width_pt: float
    usable_height_pt: float
    overflow_width_pt: float
    overflow_height_pt: float
    font_family: str
    font_path: str | None
    substitute_for: str | None = None
    rtl: bool = False
    harakat: bool = False
    notdef: int = 0
    unbreakable_words: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def _words(paragraph: str) -> list[str]:
    return [word for word in BREAKABLE_SPACE.split(paragraph) if word]


def wrap(face: FontFace, text: str, size_pt: float, width_pt: float) -> tuple[list[str], list[str]]:
    """Greedy whitespace wrap. Returns (lines, words wider than the line)."""
    upem = font_metrics(face.path, face.index).upem
    width = lambda value: shape(face.path, face.index, value).width_pt(size_pt, upem)  # noqa: E731
    lines: list[str] = []
    too_wide: list[str] = []
    for paragraph in (text or "").split("\n"):
        words = _words(paragraph)
        if not words:
            lines.append("")
            continue
        current = ""
        for word in words:
            if width(word) > width_pt + 1e-6:
                too_wide.append(word)
            candidate = f"{current} {word}" if current else word
            if not current or width(candidate) <= width_pt + 1e-6:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines or [""], too_wide


def line_height_pt(face: FontFace, lines: list[str], size_pt: float, spacing: float,
                   mark_clearance: float = 0.08) -> float:
    metrics = font_metrics(face.path, face.index)
    office = metrics.office_line_units * size_pt / metrics.upem * spacing
    ink = 0.0
    for line in lines:
        if not line:
            continue
        shaped = shape(face.path, face.index, line)
        ink = max(ink, (shaped.ink_top_units - shaped.ink_bottom_units) * size_pt / metrics.upem)
    return max(office, ink * (1 + mark_clearance))


def measure(face: FontFace, text: str, size_pt: float, width_pt: float, spacing: float = 1.0) -> dict:
    lines, too_wide = wrap(face, text, size_pt, width_pt)
    height = line_height_pt(face, lines, size_pt, spacing)
    upem = font_metrics(face.path, face.index).upem
    widths = [shape(face.path, face.index, line).width_pt(size_pt, upem) for line in lines if line]
    notdef = sum(shape(face.path, face.index, line).notdef for line in lines if line)
    return {"lines": lines, "too_wide": too_wide, "line_height_pt": height, "block_height_pt": height * len(lines),
            "max_width_pt": max(widths, default=0.0), "notdef": notdef}


def fit_text(text: str, box_width_pt: float, box_height_pt: float, family: str, *, bold: bool = False,
             italic: bool = False, max_size_pt: float = 24.0, min_size_pt: float = 8.0, spacing: float = 1.0,
             inset_pt: float = 3.6, registry: FontRegistry | None = None,
             fallback_family: str | None = None) -> FitResult:
    """Largest half-point size from max down to min at which `text` fits the box.

    Uses the requested family; if it is not installed and `fallback_family` is,
    measures with the fallback and labels the result with `substitute_for`.
    """
    registry = registry or default_registry()
    face = registry.resolve(family, bold, italic)
    substitute = None
    if face is None and fallback_family:
        face = registry.resolve(fallback_family, bold, italic)
        substitute = family if face is not None else None
    if face is None:
        raise LookupError(f"font family not installed: {family!r}")
    usable_w = max(1.0, box_width_pt - 2 * inset_pt)
    usable_h = max(1.0, box_height_pt - 2 * inset_pt)
    size = math.floor(max_size_pt / HALF_POINT) * HALF_POINT
    last = None
    while size >= min_size_pt - 1e-9:
        facts = measure(face, text, size, usable_w, spacing)
        last = (size, facts)
        if not facts["too_wide"] and facts["block_height_pt"] <= usable_h + 1e-6:
            break
        size -= HALF_POINT
    assert last is not None, "max_size_pt must be >= min_size_pt"
    size, facts = last
    fits = not facts["too_wide"] and facts["block_height_pt"] <= usable_h + 1e-6
    return FitResult(
        fits=fits, size_pt=size, lines=facts["lines"], line_height_pt=round(facts["line_height_pt"], 3),
        block_height_pt=round(facts["block_height_pt"], 3), max_line_width_pt=round(facts["max_width_pt"], 3),
        usable_width_pt=round(usable_w, 3), usable_height_pt=round(usable_h, 3),
        overflow_width_pt=round(max(0.0, facts["max_width_pt"] - usable_w), 3),
        overflow_height_pt=round(max(0.0, facts["block_height_pt"] - usable_h), 3),
        font_family=face.family, font_path=face.path, substitute_for=substitute, rtl=has_rtl(text),
        harakat=has_harakat(text), notdef=facts["notdef"], unbreakable_words=facts["too_wide"],
    )


def min_safe_line_spacing(face: FontFace, sample: str, size_pt: float = 20.0) -> float:
    """Smallest spacing multiple at which the ink of `sample` fits the Office line box."""
    metrics = font_metrics(face.path, face.index)
    office = metrics.office_line_units * size_pt / metrics.upem
    shaped = shape(face.path, face.index, sample)
    ink = (shaped.ink_top_units - shaped.ink_bottom_units) * size_pt / metrics.upem
    return round(max(1.0, ink * 1.08 / office), 3)
