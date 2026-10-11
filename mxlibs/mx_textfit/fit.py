"""Deterministic text-box fitting with Egyptian-Arabic verdicts.

Rules enforced:

* Lines break only at whitespace. An Arabic word is never split (a split breaks
  letter joining); a word wider than the box is an overflow *fact*.
* Explicit newlines (the editor turns ``\\n`` into ``<a:br/>``) are hard breaks.
* Line height = max(Office single-line box x spacing multiple, real ink height of
  the line incl. harakat + 8 % clearance); an exact spacing in points wins.
* The verdict is one of ``fits`` / ``will_shrink`` / ``does_not_fit`` /
  ``missing_glyphs`` / ``font_missing``. It is a measurement, not a visual
  judgement; the result always says which measurement method produced it, and
  ``approximate`` results are flagged as such.
"""

from __future__ import annotations

import math
import re

from .fonts import FontResolver, default_resolver
from .measure import has_harakat, has_rtl, measurer_for

EMU_PER_PT = 12700
EMU_PER_CM = 360000
#: PowerPoint's default body insets (lIns, tIns, rIns, bIns): 0.1" left/right, 0.05" top/bottom.
DEFAULT_INSET_EMU = (91440, 45720, 91440, 45720)
#: The operator's editor limits (OM app/editor/deck.py, P149-b).
EDITOR_MAX_TEXT = 2000
EDITOR_MAX_LINES = 30
HALF_POINT = 0.5
MARK_CLEARANCE = 0.08

# Breakable whitespace only. NBSP (U+00A0), figure space (U+2007) and narrow NBSP (U+202F) do NOT break.
BREAKABLE_SPACE = re.compile("[ \t  -  -  　]+")

MESSAGES = {
    "fits": ("النص داخل في المكان تمام", "The text fits."),
    "will_shrink": ("النص هيصغر لـ {size} نقطة عشان يدخل في المكان", "The text will shrink to {size} pt to fit."),
    "does_not_fit": (
        "النص ده أطول من المكان المتاح — قصّره شوية",
        "This text is longer than the space available — please shorten it.",
    ),
    "word_too_wide": (
        "فيه كلمة أعرض من المكان («{word}») — قصّرها أو افصلها بمسافة",
        "A word is wider than the box (“{word}”) — shorten it or split it with a space.",
    ),
    "too_many_lines": (
        "النص ده {lines} سطر والمسموح {max_lines} بس — قلّل السطور",
        "This text has {lines} lines and at most {max_lines} are allowed — use fewer lines.",
    ),
    "too_many_chars": (
        "النص ده {chars} حرف والمسموح {max_chars} بس — قصّره شوية",
        "This text has {chars} characters and at most {max_chars} are allowed — shorten it.",
    ),
    "missing_glyphs": (
        "فيه {count} حرف مش موجود في الخط «{family}» وهيطلع مربعات — شيله أو غيّره",
        "{count} character(s) are missing from the font “{family}” and would print as boxes.",
    ),
    "font_missing": (
        "الخط «{family}» مش متسطّب على الجهاز ده — مش قادرين نقيس النص",
        "The font “{family}” is not installed on this machine — the text cannot be measured.",
    ),
    "substitute": (
        "(اتقاس بالخط البديل «{used}» لأن «{family}» مش موجود)",
        "(measured with the substitute font “{used}” because “{family}” is missing)",
    ),
    "approximate": (
        "(القياس ده تقريبي — مفيش HarfBuzz ولا raqm على الجهاز)",
        "(approximate measurement — neither HarfBuzz nor raqm is available)",
    ),
}


def char_limit(original_text: str) -> int:
    """The editor's per-paragraph character cap: ``min(2000, max(80, len(orig)*2+40))``."""
    return min(EDITOR_MAX_TEXT, max(80, len(original_text or "") * 2 + 40))


def _fmt_size(size: float) -> str:
    return f"{size:g}"


def _insets(inset) -> tuple[int, int, int, int]:
    if inset is None:
        return DEFAULT_INSET_EMU
    if isinstance(inset, (int, float)):
        value = int(inset)
        return (value, value, value, value)
    values = tuple(int(v) for v in inset)
    if len(values) == 2:  # (horizontal, vertical)
        return (values[0], values[1], values[0], values[1])
    if len(values) != 4:
        raise ValueError("inset_emu must be one number, (h, v) or (left, top, right, bottom)")
    return values  # type: ignore[return-value]


def normalise_text(text: str) -> str:
    """CRLF/CR and PowerPoint's vertical-tab soft break become hard line breaks."""
    return (text or "").replace("\r\n", "\n").replace("\r", "\n").replace("\v", "\n")


def _words(paragraph: str) -> list[str]:
    return [word for word in BREAKABLE_SPACE.split(paragraph) if word]


def wrap(measurer, text: str, size_pt: float, width_pt: float) -> tuple[list[str], list[str]]:
    """Greedy whitespace wrap. Returns (lines, words wider than the line)."""
    scale = size_pt / measurer.upem
    width = lambda value: measurer.measure(value).width_units * scale
    lines: list[str] = []
    too_wide: list[str] = []
    for paragraph in normalise_text(text).split("\n"):
        words = _words(paragraph)
        if not words:
            lines.append("")
            continue
        current = ""
        for word in words:
            if width(word) > width_pt + 1e-6 and word not in too_wide:
                too_wide.append(word)
            candidate = f"{current} {word}" if current else word
            if not current or width(candidate) <= width_pt + 1e-6:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines or [""], too_wide


def _layout(measurer, text: str, size: float, usable_w: float, spacing: float, spacing_pt: float | None) -> dict:
    lines, too_wide = wrap(measurer, text, size, usable_w)
    scale = size / measurer.upem
    if spacing_pt:
        line_height = float(spacing_pt)
    else:
        office = measurer.info.office_line_units * scale * spacing
        ink = 0.0
        for line in lines:
            if line:
                m = measurer.measure(line)
                ink = max(ink, (m.ink_top_units - m.ink_bottom_units) * scale)
        line_height = max(office, ink * (1 + MARK_CLEARANCE))
    widths = [measurer.measure(line).width_units * scale for line in lines if line]
    notdef = sum(measurer.measure(line).notdef for line in lines if line)
    return {
        "lines": lines,
        "too_wide": too_wide,
        "line_height_pt": line_height,
        "block_height_pt": line_height * len(lines),
        "max_width_pt": max(widths, default=0.0),
        "notdef": notdef,
    }


def _message(key: str, **values) -> tuple[str, str]:
    ar, en = MESSAGES[key]
    return ar.format(**values), en.format(**values)


def fit(
    text: str,
    box_emu,
    font: dict,
    rules: dict | None = None,
    *,
    resolver: FontResolver | None = None,
    font_dirs: list | None = None,
    font_files: list | None = None,
    method: str = "auto",
) -> dict:
    """Measure ``text`` in a text box and return the verdict with its facts.

    box_emu: (width, height) of the shape in EMU.
    font:    {family, size_pt, bold=False, italic=False, line_spacing=1.0 (multiple),
              line_spacing_pt=None (exact), fallback_families=[]}
    rules:   {min_size_pt=size_pt, max_lines=30, inset_emu=PowerPoint default, allow_shrink=False,
              grow_height=False (shape auto-fit: height is not a limit), reserved_height_pt=0,
              max_chars=None}
    Returns  {fits, verdict, reason, size_pt, lines, line_count, overflow_pt, font_used, substitute,
              method, approximate, ar, en, ...facts}.
    """
    rules = dict(rules or {})
    family = str(font.get("family") or "")
    size_pt = float(font.get("size_pt") or 18.0)
    bold, italic = bool(font.get("bold")), bool(font.get("italic"))
    spacing = float(font.get("line_spacing") or 1.0)
    spacing_pt = font.get("line_spacing_pt")
    allow_shrink = bool(rules.get("allow_shrink", False))
    min_size = float(rules.get("min_size_pt") or (size_pt if not allow_shrink else min(8.0, size_pt)))
    max_lines = int(rules.get("max_lines") or EDITOR_MAX_LINES)
    grow_height = bool(rules.get("grow_height", False))
    reserved = float(rules.get("reserved_height_pt") or 0.0)
    max_chars = rules.get("max_chars")
    left, top, right, bottom = _insets(rules.get("inset_emu"))
    box_w, box_h = (int(v) for v in box_emu)
    usable_w = max(1.0, (box_w - left - right) / EMU_PER_PT)
    usable_h = max(1.0, (box_h - top - bottom) / EMU_PER_PT)
    text = normalise_text(text)

    base = {
        "requested_family": family,
        "requested_size_pt": size_pt,
        "usable_width_pt": round(usable_w, 3),
        "usable_height_pt": round(usable_h, 3),
        "rtl": has_rtl(text),
        "harakat": has_harakat(text),
        "chars": len(text),
        "max_lines": max_lines,
    }

    if resolver is None:
        resolver = (
            FontResolver(directories=font_dirs or [], files=font_files)
            if (font_dirs or font_files)
            else default_resolver()
        )
    face = resolver.resolve(family, bold, italic)
    substitute = None
    if face is None:
        for alt in font.get("fallback_families") or []:
            face = resolver.resolve(alt, bold, italic)
            if face is not None:
                substitute = family
                break
    if face is None:
        ar, en = _message("font_missing", family=family)
        return {
            **base,
            "fits": False,
            "verdict": "font_missing",
            "reason": "font_missing",
            "size_pt": size_pt,
            "lines": [],
            "line_count": 0,
            "overflow_pt": None,
            "font_used": None,
            "substitute": None,
            "method": None,
            "approximate": None,
            "ar": ar,
            "en": en,
        }

    measurer = measurer_for(face, method)

    def passes(facts: dict) -> bool:
        height_ok = grow_height or facts["block_height_pt"] + reserved <= usable_h + 1e-6
        return not facts["too_wide"] and height_ok and len(facts["lines"]) <= max_lines

    sizes = [size_pt]
    if allow_shrink:
        step = math.floor((size_pt - 1e-9) / HALF_POINT) * HALF_POINT
        while step >= min_size - 1e-9:
            sizes.append(round(step, 2))
            step -= HALF_POINT
    chosen = None
    facts = None
    for size in sizes:
        facts = _layout(measurer, text, size, usable_w, spacing, spacing_pt)
        if passes(facts):
            chosen = size
            break
    assert facts is not None
    final_size = chosen if chosen is not None else sizes[-1]

    overflow_h = 0.0 if grow_height else max(0.0, facts["block_height_pt"] + reserved - usable_h)
    widest_word = 0.0
    scale = final_size / measurer.upem
    for word in facts["too_wide"]:
        widest_word = max(widest_word, measurer.measure(word).width_units * scale)
    overflow_w = max(0.0, widest_word - usable_w)
    line_count = len(facts["lines"])

    if facts["notdef"]:
        verdict, reason = "missing_glyphs", "missing_glyphs"
        ar, en = _message("missing_glyphs", count=facts["notdef"], family=face.family)
    elif max_chars is not None and len(text) > int(max_chars):
        verdict, reason = "does_not_fit", "too_many_chars"
        ar, en = _message("too_many_chars", chars=len(text), max_chars=int(max_chars))
    elif chosen is None:
        verdict = "does_not_fit"
        if facts["too_wide"]:
            reason = "word_too_wide"
            ar, en = _message("word_too_wide", word=facts["too_wide"][0])
        elif line_count > max_lines and overflow_h <= 0:
            reason = "too_many_lines"
            ar, en = _message("too_many_lines", lines=line_count, max_lines=max_lines)
        else:
            reason = "height"
            ar, en = _message("does_not_fit")
    elif chosen < size_pt - 1e-9:
        verdict, reason = "will_shrink", "shrink"
        ar, en = _message("will_shrink", size=_fmt_size(chosen))
    else:
        verdict, reason = "fits", "fits"
        ar, en = _message("fits")
    if substitute:
        sub_ar, sub_en = _message("substitute", used=face.family, family=substitute)
        ar, en = f"{ar} {sub_ar}", f"{en} {sub_en}"
    approximate = measurer.method == "approximate"
    if approximate:
        ap_ar, ap_en = _message("approximate")
        ar, en = f"{ar} {ap_ar}", f"{en} {ap_en}"

    return {
        **base,
        "fits": verdict in ("fits", "will_shrink"),
        "verdict": verdict,
        "reason": reason,
        "size_pt": final_size,
        "lines": facts["lines"],
        "line_count": line_count,
        "line_height_pt": round(facts["line_height_pt"], 3),
        "block_height_pt": round(facts["block_height_pt"] + reserved, 3),
        "max_line_width_pt": round(facts["max_width_pt"], 3),
        "overflow_pt": round(max(overflow_h, overflow_w), 3),
        "overflow_height_pt": round(overflow_h, 3),
        "overflow_width_pt": round(overflow_w, 3),
        "unbreakable_words": facts["too_wide"],
        "notdef": facts["notdef"],
        "font_used": face.as_dict(),
        "substitute": substitute,
        "method": measurer.method,
        "measured_with": measurer.backend,
        "approximate": approximate,
        "ar": ar,
        "en": en,
    }
