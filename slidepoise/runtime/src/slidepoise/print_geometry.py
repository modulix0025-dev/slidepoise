"""Print page geometry: trim, bleed, safe zone, ISO-216 scaling, mirrored folios.

All lengths are millimetres unless the name says otherwise. The generation
canvas is trim + bleed on every side; the trim box and safe box are expressed in
canvas coordinates so art, text and checks share one frame.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

EMU_PER_MM = 36000
EMU_PER_CM = 360000
MM_PER_INCH = 25.4
ISO216_A4_TO_A5 = 1 / math.sqrt(2)  # 0.70710678… A5 is A4 halved; every length scales by 1/sqrt(2)

TRIM_SIZES_MM = {"A4": (210.0, 297.0), "A5": (148.0, 210.0)}


@dataclass(frozen=True)
class PageSpec:
    trim_mm: tuple[float, float]
    bleed_mm: float = 3.0
    safe_mm: float = 5.0
    dpi: int = 300
    name: str = ""

    @classmethod
    def preset(cls, name: str, bleed_mm: float = 3.0, safe_mm: float = 5.0, dpi: int = 300) -> "PageSpec":
        key = name.upper()
        if key not in TRIM_SIZES_MM:
            raise ValueError(f"unknown page size {name!r}; known: {sorted(TRIM_SIZES_MM)}")
        return cls(TRIM_SIZES_MM[key], bleed_mm, safe_mm, dpi, key)

    def __post_init__(self):
        width, height = self.trim_mm
        if width <= 0 or height <= 0 or self.bleed_mm < 0 or self.safe_mm < 0 or self.dpi <= 0:
            raise ValueError("page dimensions, bleed, safe zone and dpi must be positive")
        if 2 * self.safe_mm >= min(width, height):
            raise ValueError("safe zone leaves no live area")

    @property
    def canvas_mm(self) -> tuple[float, float]:
        return (self.trim_mm[0] + 2 * self.bleed_mm, self.trim_mm[1] + 2 * self.bleed_mm)

    @property
    def canvas_emu(self) -> tuple[int, int]:
        return tuple(round(value * EMU_PER_MM) for value in self.canvas_mm)  # type: ignore[return-value]

    @property
    def canvas_inches(self) -> tuple[float, float]:
        return tuple(value / MM_PER_INCH for value in self.canvas_mm)  # type: ignore[return-value]

    @property
    def canvas_px(self) -> tuple[int, int]:
        return tuple(round(value / MM_PER_INCH * self.dpi) for value in self.canvas_mm)  # type: ignore[return-value]

    def mm_to_px(self, value_mm: float) -> float:
        return value_mm / MM_PER_INCH * self.dpi

    def px_to_mm(self, value_px: float) -> float:
        return value_px * MM_PER_INCH / self.dpi

    def trim_box_mm(self) -> tuple[float, float, float, float]:
        """[x, y, w, h] of the trimmed page inside the canvas."""
        return (self.bleed_mm, self.bleed_mm, self.trim_mm[0], self.trim_mm[1])

    def safe_box_mm(self) -> tuple[float, float, float, float]:
        inset = self.bleed_mm + self.safe_mm
        return (inset, inset, self.trim_mm[0] - 2 * self.safe_mm, self.trim_mm[1] - 2 * self.safe_mm)

    def box_px(self, box_mm: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
        """Box in canvas pixels, scaled by the *integer* canvas size per axis.

        Using the nominal dpi here would leave full-bleed boxes a fraction of a pixel
        short of the canvas edge once the canvas is rounded to whole pixels.
        """
        (cw_mm, ch_mm), (cw_px, ch_px) = self.canvas_mm, self.canvas_px
        x, y, w, h = box_mm
        return (x * cw_px / cw_mm, y * ch_px / ch_mm, w * cw_px / cw_mm, h * ch_px / ch_mm)

    def inside_safe(self, box_mm: tuple[float, float, float, float], tolerance_mm: float = 0.05) -> bool:
        sx, sy, sw, sh = self.safe_box_mm()
        x, y, w, h = box_mm
        return (x >= sx - tolerance_mm and y >= sy - tolerance_mm and x + w <= sx + sw + tolerance_mm
                and y + h <= sy + sh + tolerance_mm)

    def reaches_bleed(self, box_mm: tuple[float, float, float, float], tolerance_mm: float = 0.05) -> dict[str, bool]:
        """Which canvas edges a full-bleed element actually covers."""
        x, y, w, h = box_mm
        cw, ch = self.canvas_mm
        return {"left": x <= tolerance_mm, "top": y <= tolerance_mm,
                "right": x + w >= cw - tolerance_mm, "bottom": y + h >= ch - tolerance_mm}


def iso216_scale(from_size: str, to_size: str) -> float:
    """Linear factor between ISO-216 A sizes (A4->A5 = 1/sqrt(2)); applies to geometry AND font sizes."""
    order = {"A4": 4, "A5": 5}
    try:
        steps = order[to_size.upper()] - order[from_size.upper()]
    except KeyError as exc:
        raise ValueError(f"unsupported ISO-216 size: {exc}") from exc
    return ISO216_A4_TO_A5 ** steps


def scale_box(box: tuple[float, float, float, float], factor: float) -> tuple[float, float, float, float]:
    return tuple(value * factor for value in box)  # type: ignore[return-value]


def folio_box_mm(spec: PageSpec, page_number: int, reading: str = "rtl",
                 size_mm: tuple[float, float] = (12.0, 6.0)) -> tuple[float, float, float, float]:
    """Folio (page number) box on the outer edge of the page, inside the safe zone.

    The outer edge is mirrored left/right with the page side. In an RTL book an
    odd page is a left-hand page, whose outer edge is the left; in an LTR book an
    odd page is a right-hand page.
    """
    if reading not in {"rtl", "ltr"}:
        raise ValueError("reading must be 'rtl' or 'ltr'")
    sx, sy, sw, sh = spec.safe_box_mm()
    width, height = size_mm
    odd = page_number % 2 == 1
    outer_is_left = odd if reading == "rtl" else not odd
    x = sx if outer_is_left else sx + sw - width
    y = sy + sh - height  # bottom of the live area
    return (x, y, width, height)
