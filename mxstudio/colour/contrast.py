"""Text contrast: WCAG 2.x contrast ratio and APCA Lc (0.0.98G-4g constants).

Rule: a contrast number is a measured fact. The Studio uses two published models side by
side — WCAG 2.x (ratio 1..21, thresholds 4.5 body / 3.0 large text) and APCA (Lc,
polarity-aware; positive = dark text on light background, negative = light on dark).
Both are implemented here from their published equations and constants so that results
are reproducible offline; coloraide's WCAG 2.1 implementation cross-checks the ratio.

APCA constants are those of APCA-W3 0.0.98G-4g (Myndex, "SA98G"); only the math is
used, no code was copied. APCA is a draft model for WCAG 3; the Studio reports it next to
WCAG and treats WCAG 2.x as the normative floor.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .oklch import ColourLike, as_float_rgb, parse_rgb, relative_luminance_array

# ------------------------------------------------------------------- WCAG 2.x

WCAG_AA_BODY = 4.5
WCAG_AA_LARGE = 3.0
WCAG_AAA_BODY = 7.0


def relative_luminance(colour: ColourLike) -> float:
    return float(relative_luminance_array(np.array(parse_rgb(colour), dtype=np.uint8)))


def wcag_ratio_from_luminance(y1, y2):
    y1 = np.asarray(y1, dtype=np.float64)
    y2 = np.asarray(y2, dtype=np.float64)
    hi, lo = np.maximum(y1, y2), np.minimum(y1, y2)
    return (hi + 0.05) / (lo + 0.05)


def wcag_contrast(fg: ColourLike, bg: ColourLike) -> float:
    return float(wcag_ratio_from_luminance(relative_luminance(fg), relative_luminance(bg)))


def is_large_text(font_size_pt: float, bold: bool = False) -> bool:
    """WCAG 'large scale': ≥ 18 pt regular or ≥ 14 pt bold."""
    return font_size_pt >= 18.0 or (bold and font_size_pt >= 14.0)


def wcag_threshold(font_size_pt: float, bold: bool = False) -> float:
    return WCAG_AA_LARGE if is_large_text(font_size_pt, bold) else WCAG_AA_BODY


# ------------------------------------------------------------------- APCA 0.0.98G-4g

@dataclass(frozen=True)
class APCAConstants:
    main_trc: float = 2.4
    s_r: float = 0.2126729
    s_g: float = 0.7151522
    s_b: float = 0.0721750
    norm_bg: float = 0.56
    norm_txt: float = 0.57
    rev_txt: float = 0.62
    rev_bg: float = 0.65
    blk_thrs: float = 0.022
    blk_clmp: float = 1.414
    scale_bow: float = 1.14
    scale_wob: float = 1.14
    lo_bow_offset: float = 0.027
    lo_wob_offset: float = 0.027
    delta_y_min: float = 0.0005
    lo_clip: float = 0.1


APCA_98G = APCAConstants()


def apca_y(pixels, k: APCAConstants = APCA_98G) -> np.ndarray:
    """APCA screen luminance Ys: simple 2.4 power curve per channel (not the sRGB piecewise)."""
    rgb = as_float_rgb(np.asarray(pixels))
    lin = rgb ** k.main_trc
    return lin @ np.array([k.s_r, k.s_g, k.s_b])


def apca_lc_from_y(txt_y, bg_y, k: APCAConstants = APCA_98G) -> np.ndarray:
    """Vectorised APCA Lc for text luminance(s) over background luminance(s)."""
    txt = np.asarray(txt_y, dtype=np.float64)
    bg = np.asarray(bg_y, dtype=np.float64)
    txt, bg = np.broadcast_arrays(txt, bg)
    txt = np.where(txt > k.blk_thrs, txt, txt + np.abs(k.blk_thrs - txt) ** k.blk_clmp)
    bg = np.where(bg > k.blk_thrs, bg, bg + np.abs(k.blk_thrs - bg) ** k.blk_clmp)
    normal = bg > txt  # dark text on light background
    sapc_n = (bg ** k.norm_bg - txt ** k.norm_txt) * k.scale_bow
    sapc_r = (bg ** k.rev_bg - txt ** k.rev_txt) * k.scale_wob
    out_n = np.where(sapc_n < k.lo_clip, 0.0, sapc_n - k.lo_bow_offset)
    out_r = np.where(sapc_r > -k.lo_clip, 0.0, sapc_r + k.lo_wob_offset)
    out = np.where(normal, out_n, out_r)
    out = np.where(np.abs(bg - txt) < k.delta_y_min, 0.0, out)
    return out * 100.0


def apca_lc(text: ColourLike, background: ColourLike) -> float:
    t = apca_y(np.array(parse_rgb(text), dtype=np.uint8))
    b = apca_y(np.array(parse_rgb(background), dtype=np.uint8))
    return float(apca_lc_from_y(t, b))


# Minimum |Lc| used by the Studio for printed children's text (APCA "bronze" simple mode:
# Lc 75 body text, Lc 60 large/content text, Lc 45 headlines ≥ 36 px-equivalent).
APCA_BODY = 75.0
APCA_LARGE = 60.0
APCA_HEADLINE = 45.0


def apca_threshold(font_size_pt: float, bold: bool = False) -> float:
    if font_size_pt >= 28.0 or (bold and font_size_pt >= 22.0):
        return APCA_HEADLINE
    if is_large_text(font_size_pt, bold):
        return APCA_LARGE
    return APCA_BODY


def contrast_report(text: ColourLike, background: ColourLike, font_size_pt: float = 14.0,
                    bold: bool = False) -> dict:
    """Facts for one colour pair; ``passes_wcag`` is the normative floor."""
    ratio = wcag_contrast(text, background)
    lc = apca_lc(text, background)
    w_min = wcag_threshold(font_size_pt, bold)
    a_min = apca_threshold(font_size_pt, bold)
    return {
        "wcag_ratio": round(ratio, 3), "wcag_min": w_min, "passes_wcag": ratio >= w_min,
        "apca_lc": round(lc, 2), "apca_min_abs": a_min, "passes_apca": abs(lc) >= a_min,
    }
