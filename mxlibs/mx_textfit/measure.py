"""Text measurement backends, best available first.

Rule enforced: the fitter says *how* it measured. Order of preference:

1. ``harfbuzz``    - uharfbuzz shaping per directional run (exact advances, GPOS marks);
2. ``pillow_raqm`` - Pillow with the libraqm layout engine (HarfBuzz + FriBiDi inside Pillow);
3. ``approximate`` - fontTools ``hmtx`` advance widths per code point (no joining, no kerning),
                     or Pillow's basic layout when fontTools is absent.

Widths are measured on logical text split into directional runs: bidi
reordering changes the order runs are drawn in, never their widths.
Units are font units (``upem`` per em).
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from . import _sfnt
from .fonts import FontFace

_RTL_CLASSES = {"R", "AL", "AN"}
_LTR_CLASSES = {"L"}
#: Characters that never need a glyph of their own.
_IGNORABLE = {
    0x200C,
    0x200D,
    0x200E,
    0x200F,
    0x061C,
    0x2066,
    0x2067,
    0x2068,
    0x2069,
    0x202A,
    0x202B,
    0x202C,
    0x202D,
    0x202E,
    0xFE0F,
    0x00AD,
}


def has_rtl(text: str) -> bool:
    return any(unicodedata.bidirectional(ch) in ("R", "AL") for ch in text or "")


def has_harakat(text: str) -> bool:
    return any(0x064B <= ord(ch) <= 0x0652 or ord(ch) == 0x0670 for ch in text or "")


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
class Measured:
    width_units: float
    ink_top_units: float
    ink_bottom_units: float
    notdef: int


def _missing_glyphs(face: FontFace, text: str) -> int:
    try:
        coverage = _sfnt.coverage_for(face.path, face.index)
    except Exception:  # noqa: BLE001
        return 0
    if not coverage:
        return 0
    return sum(
        1
        for ch in text
        if not ch.isspace()
        and ord(ch) not in _IGNORABLE
        and unicodedata.category(ch) not in ("Cc", "Cf")
        and ord(ch) not in coverage
    )


def _layout(image_font, name: str):
    """Pillow >= 10 exposes ImageFont.Layout.<NAME>; older releases LAYOUT_<NAME>."""
    layout = getattr(image_font, "Layout", None)
    return getattr(layout, name) if layout is not None else getattr(image_font, f"LAYOUT_{name}")


class _Base:
    method = "approximate"
    backend = ""

    def __init__(self, face: FontFace):
        self.face = face
        self.info = _sfnt.info_for(face.path, face.index)
        self.upem = self.info.upem
        self._cache: dict[str, Measured] = {}

    def measure(self, text: str) -> Measured:
        hit = self._cache.get(text)
        if hit is None:
            hit = self._measure(text) if text else Measured(0.0, 0.0, 0.0, 0)
            if len(self._cache) > 20000:
                self._cache.clear()
            self._cache[text] = hit
        return hit

    def _measure(self, text: str) -> Measured:  # pragma: no cover - abstract
        raise NotImplementedError


class HarfBuzzMeasurer(_Base):
    method = "harfbuzz"
    backend = "uharfbuzz"

    def __init__(self, face: FontFace):
        super().__init__(face)
        import uharfbuzz as hb

        self._hb = hb
        blob = hb.Blob.from_file_path(face.path)
        self._font = hb.Font(hb.Face(blob, face.index))

    def _measure(self, text: str) -> Measured:
        hb = self._hb
        width = top = bottom = 0
        notdef = 0
        for run, rtl in directional_runs(text):
            buf = hb.Buffer()
            buf.add_str(run)
            buf.guess_segment_properties()
            if rtl:
                buf.direction = "rtl"
                if any("؀" <= ch <= "ۿ" or "ݐ" <= ch <= "ࣿ" for ch in run):
                    buf.script = "Arab"
                    buf.language = "ar"
            hb.shape(self._font, buf, {})
            for info, pos in zip(buf.glyph_infos, buf.glyph_positions, strict=True):
                width += pos.x_advance
                if info.codepoint == 0:
                    notdef += 1
                    continue
                extents = self._font.get_glyph_extents(info.codepoint)
                if extents is None:
                    continue
                glyph_top = pos.y_offset + extents.y_bearing
                top = max(top, glyph_top)
                bottom = min(bottom, glyph_top + extents.height)
        return Measured(float(width), float(top), float(bottom), notdef)


class PillowRaqmMeasurer(_Base):
    method = "pillow_raqm"
    backend = "Pillow+libraqm"

    def __init__(self, face: FontFace):
        super().__init__(face)
        from PIL import ImageFont, features

        if not features.check("raqm"):
            raise ImportError("Pillow was built without libraqm")
        self._font = ImageFont.truetype(
            face.path, size=self.upem, index=face.index, layout_engine=_layout(ImageFont, "RAQM")
        )

    def _measure(self, text: str) -> Measured:
        width = 0.0
        top = bottom = 0.0
        for run, rtl in directional_runs(text):
            direction = "rtl" if rtl else "ltr"
            width += float(self._font.getlength(run, direction=direction))
            if run.strip():
                _left, t, _right, b = self._font.getbbox(run, direction=direction, anchor="ls")
                top = max(top, -float(t))
                bottom = min(bottom, -float(b))
        return Measured(width, top, bottom, _missing_glyphs(self.face, text))


class FontToolsMeasurer(_Base):
    """Advance widths of nominal glyphs. No joining, ligatures or kerning: approximate."""

    method = "approximate"
    backend = "fontTools-hmtx"

    def __init__(self, face: FontFace):
        super().__init__(face)
        from fontTools.ttLib import TTFont

        font = TTFont(face.path, fontNumber=face.index, lazy=True)
        try:
            self._cmap = dict(font.getBestCmap() or {})
            self._hmtx = {name: adv for name, (adv, _lsb) in font["hmtx"].metrics.items()}
            self._notdef_adv = self._hmtx.get(".notdef", self.upem // 2)
        finally:
            font.close()

    def _measure(self, text: str) -> Measured:
        width = 0
        for ch in text:
            cp = ord(ch)
            if unicodedata.category(ch) == "Mn" or cp in _IGNORABLE:
                continue  # marks and joiners carry no advance in a shaped line
            glyph = self._cmap.get(cp)
            width += self._hmtx.get(glyph, self._notdef_adv) if glyph else self._notdef_adv
        return Measured(
            float(width), float(self.info.hhea_ascent), float(self.info.hhea_descent), _missing_glyphs(self.face, text)
        )


class PillowBasicMeasurer(_Base):
    """Pillow without raqm: no Arabic shaping, so widths are approximate."""

    method = "approximate"
    backend = "Pillow-basic"

    def __init__(self, face: FontFace):
        super().__init__(face)
        from PIL import ImageFont

        self._font = ImageFont.truetype(
            face.path, size=self.upem, index=face.index, layout_engine=_layout(ImageFont, "BASIC")
        )

    def _measure(self, text: str) -> Measured:
        return Measured(
            float(self._font.getlength(text)),
            float(self.info.hhea_ascent),
            float(self.info.hhea_descent),
            _missing_glyphs(self.face, text),
        )


ORDER = {
    "harfbuzz": (HarfBuzzMeasurer,),
    "pillow_raqm": (PillowRaqmMeasurer,),
    "approximate": (FontToolsMeasurer, PillowBasicMeasurer),
}


def measurer_for(face: FontFace, prefer: str = "auto") -> _Base:
    """Best available measurer; ``prefer`` pins one method (used by tests and the editor's diagnostics)."""
    if prefer == "auto":
        classes = ORDER["harfbuzz"] + ORDER["pillow_raqm"] + ORDER["approximate"]
    elif prefer in ORDER:
        classes = ORDER[prefer]
    else:
        raise ValueError(f"unknown measurement method {prefer!r}; known: auto, {', '.join(ORDER)}")
    errors = []
    for cls in classes:
        try:
            return cls(face)
        except Exception as exc:  # noqa: BLE001 - try the next backend
            errors.append(f"{cls.__name__}: {exc}")
    raise RuntimeError("no measurement backend is available: " + "; ".join(errors))
