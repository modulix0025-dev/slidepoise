"""HarfBuzz measurement of mixed Arabic/Latin text.

Widths are measured on *logical* text split into directional runs. Bidi
reordering changes the order in which runs are drawn, never their widths, so
measurement needs run segmentation (by the Unicode bidi class of each
character) but no visual reordering. That keeps the runtime free of an LGPL bidi
dependency while staying exact for fitting.

Vertical ink extents include the GPOS positioning of marks (harakat, shadda), so
a vowelised line reports its real height. That is what makes the line height
harakat-aware.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

import uharfbuzz as hb
from fontTools.ttLib import TTFont

from slidepoise.arabic.fonts import FontFace

RTL_CHARS = re.compile("[֐-ࣿיִ-﷿ﹰ-﻿\U00010E60-\U00010E7F\U0001EE00-\U0001EEFF]")
ARABIC_LETTERS = re.compile("[ؠ-يٮ-ۓۺ-ۿݐ-ݿࢠ-ࣉ]")
HARAKAT = re.compile("[ً-ْٰ]")
_RTL_CLASSES = {"R", "AL", "AN"}
_LTR_CLASSES = {"L"}
ARABIC_INDIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
WESTERN_DIGITS = "0123456789"


def has_rtl(text: str) -> bool:
    return bool(RTL_CHARS.search(text or ""))


def has_harakat(text: str) -> bool:
    return bool(HARAKAT.search(text or ""))


def to_arabic_indic_digits(text: str) -> str:
    return (text or "").translate(str.maketrans(WESTERN_DIGITS, ARABIC_INDIC_DIGITS))


def to_western_digits(text: str) -> str:
    return (text or "").translate(str.maketrans(ARABIC_INDIC_DIGITS, WESTERN_DIGITS))


def directional_runs(text: str, base_rtl: bool | None = None) -> list[tuple[str, bool]]:
    """Split logical text into (run, is_rtl). Neutrals and marks join the run they sit in."""
    if base_rtl is None:
        base_rtl = has_rtl(text)
    runs: list[tuple[str, bool]] = []
    current, current_rtl = "", None
    for char in text:
        klass = unicodedata.bidirectional(char)
        if klass in _RTL_CLASSES:
            direction = True
        elif klass in _LTR_CLASSES:
            direction = False
        else:
            direction = current_rtl if current_rtl is not None else base_rtl
        if current and direction != current_rtl:
            runs.append((current, bool(current_rtl)))
            current = ""
        current += char
        current_rtl = direction
    if current:
        runs.append((current, bool(current_rtl)))
    return runs


@dataclass(frozen=True)
class FontMetrics:
    upem: int
    win_ascent: int
    win_descent: int
    hhea_ascent: int
    hhea_descent: int
    line_gap: int

    @property
    def office_line_units(self) -> int:
        """Office lays out single-spaced lines on the Windows ascent + descent box."""
        return max(self.win_ascent + self.win_descent, self.hhea_ascent - self.hhea_descent + self.line_gap, 1)


@lru_cache(maxsize=64)
def _hb_font(path: str, index: int) -> hb.Font:
    blob = hb.Blob.from_file_path(path)
    return hb.Font(hb.Face(blob, index))


@lru_cache(maxsize=64)
def font_metrics(path: str, index: int = 0) -> FontMetrics:
    font = TTFont(path, lazy=True, fontNumber=index)
    try:
        os2 = font["OS/2"]
        hhea = font["hhea"]
        return FontMetrics(upem=int(font["head"].unitsPerEm), win_ascent=int(os2.usWinAscent),
                           win_descent=int(os2.usWinDescent), hhea_ascent=int(hhea.ascent),
                           hhea_descent=int(hhea.descent), line_gap=int(hhea.lineGap))
    finally:
        font.close()


@dataclass(frozen=True)
class Shaped:
    width_units: int
    ink_top_units: int
    ink_bottom_units: int
    notdef: int

    def width_pt(self, size_pt: float, upem: int) -> float:
        return self.width_units * size_pt / upem


def _shape_run(font: hb.Font, text: str, rtl: bool) -> tuple[list, list]:
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    if rtl:
        buf.direction = "rtl"
        if ARABIC_LETTERS.search(text):
            buf.script = "Arab"
            buf.language = "ar"
    hb.shape(font, buf, {})
    return buf.glyph_infos, buf.glyph_positions


@lru_cache(maxsize=4096)
def shape(path: str, index: int, text: str) -> Shaped:
    """Shape `text` (logical order) with the font at path/index; units are font units."""
    font = _hb_font(path, index)
    width = 0
    top = 0
    bottom = 0
    notdef = 0
    for run, rtl in directional_runs(text):
        infos, positions = _shape_run(font, run, rtl)
        for info, pos in zip(infos, positions):
            width += pos.x_advance
            if info.codepoint == 0:
                notdef += 1
                continue
            extents = font.get_glyph_extents(info.codepoint)
            if extents is None:
                continue
            glyph_top = pos.y_offset + extents.y_bearing
            glyph_bottom = glyph_top + extents.height
            top = max(top, glyph_top)
            bottom = min(bottom, glyph_bottom)
    return Shaped(width_units=width, ink_top_units=top, ink_bottom_units=bottom, notdef=notdef)


def text_width_pt(face: FontFace, text: str, size_pt: float) -> float:
    metrics = font_metrics(face.path, face.index)
    return shape(face.path, face.index, text).width_pt(size_pt, metrics.upem)
