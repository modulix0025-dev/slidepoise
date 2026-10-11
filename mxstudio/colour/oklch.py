"""OKLab / OKLCH conversions (coloraide as the reference) plus vectorised array paths.

Rule: every colour decision in the Studio is made in OKLab/OKLCH (perceptually even
lightness and hue), and colours are handed to PowerPoint as 8-bit sRGB hex. Scalar
conversions delegate to coloraide (MIT) so they match its reference values; the numpy
paths (used for whole images) implement the same published matrices — Ottosson's OKLab
and IEC 61966-2-1 sRGB, Bradford-adapted CIELab D50 — and are cross-checked against
coloraide in the test-suite.
"""
from __future__ import annotations

import math
import re
from typing import Sequence, Tuple, Union

import numpy as np
from coloraide import Color

RGB8 = Tuple[int, int, int]
ColourLike = Union[str, Sequence[int]]

_HEX = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def parse_rgb(colour: ColourLike) -> RGB8:
    """Accept '#rrggbb', '#rgb', 'rrggbb' or an (r, g, b) triple of 0..255 ints."""
    if isinstance(colour, str):
        match = _HEX.match(colour.strip())
        if not match:
            raise ValueError(f"not an sRGB hex colour: {colour!r}")
        digits = match.group(1)
        if len(digits) == 3:
            digits = "".join(ch * 2 for ch in digits)
        return int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16)
    values = tuple(int(round(float(v))) for v in colour)
    if len(values) != 3 or any(v < 0 or v > 255 for v in values):
        raise ValueError(f"not an 8-bit RGB triple: {colour!r}")
    return values  # type: ignore[return-value]


def to_hex(colour: ColourLike) -> str:
    r, g, b = parse_rgb(colour)
    return f"#{r:02x}{g:02x}{b:02x}"


def to_color(colour: ColourLike) -> Color:
    r, g, b = parse_rgb(colour)
    return Color("srgb", [r / 255.0, g / 255.0, b / 255.0])


def to_oklab(colour: ColourLike) -> tuple[float, float, float]:
    L, a, b = to_color(colour).convert("oklab").coords()
    return float(L), float(a), float(b)


def to_oklch(colour: ColourLike) -> tuple[float, float, float]:
    """(L 0..1, C, h degrees 0..360). Hue of an achromatic colour is reported as 0."""
    L, C, h = to_color(colour).convert("oklch").coords()
    h = 0.0 if (h is None or (isinstance(h, float) and math.isnan(h))) else float(h) % 360.0
    return float(L), float(C), h


def to_lab_d50(colour: ColourLike) -> tuple[float, float, float]:
    L, a, b = to_color(colour).convert("lab").coords()
    return float(L), float(a), float(b)


def from_oklch(L: float, C: float, h: float) -> tuple[str, bool]:
    """Return (hex, was_in_gamut). Out-of-gamut colours are fitted to sRGB keeping L and h
    (coloraide ray-trace chroma reduction in OKLCH), then rounded to 8 bits."""
    colour = Color("oklch", [L, max(0.0, C), h % 360.0])
    in_gamut = colour.in_gamut("srgb", tolerance=0.0005)
    if not in_gamut:
        colour = colour.fit("srgb", method="raytrace", pspace="oklch")
    srgb = colour.convert("srgb").clip()
    r, g, b = (int(round(min(1.0, max(0.0, v)) * 255)) for v in srgb.coords())
    return f"#{r:02x}{g:02x}{b:02x}", bool(in_gamut)


def oklch_hex(L: float, C: float, h: float) -> str:
    return from_oklch(L, C, h)[0]


def hue_distance(h1: float, h2: float) -> float:
    d = abs((h1 - h2) % 360.0)
    return min(d, 360.0 - d)


def delta_e_ok(c1: ColourLike, c2: ColourLike) -> float:
    """Euclidean distance in OKLab (≈ 0.02 is a just-noticeable difference)."""
    a, b = np.array(to_oklab(c1)), np.array(to_oklab(c2))
    return float(np.linalg.norm(a - b))


# ---------------------------------------------------------------- array paths (images)

def _xy_to_xyz(x: float, y: float) -> np.ndarray:
    return np.array([x / y, 1.0, (1.0 - x - y) / y])


def _rgb_to_xyz_matrix() -> np.ndarray:
    primaries = np.column_stack([_xy_to_xyz(0.64, 0.33), _xy_to_xyz(0.30, 0.60), _xy_to_xyz(0.15, 0.06)])
    white = _xy_to_xyz(0.31270, 0.32900)
    scale = np.linalg.solve(primaries, white)
    return primaries * scale


SRGB_TO_XYZ_D65 = _rgb_to_xyz_matrix()
_BRADFORD = np.array([[0.8951, 0.2664, -0.1614], [-0.7502, 1.7135, 0.0367], [0.0389, -0.0685, 1.0296]])
WHITE_D65 = _xy_to_xyz(0.31270, 0.32900)
WHITE_D50 = _xy_to_xyz(0.34570, 0.35850)


def _bradford(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    ratio = (_BRADFORD @ dst) / (_BRADFORD @ src)
    return np.linalg.inv(_BRADFORD) @ np.diag(ratio) @ _BRADFORD


D65_TO_D50 = _bradford(WHITE_D65, WHITE_D50)

# Ottosson 2020, "A perceptual color space for image processing" (linear sRGB -> LMS -> OKLab).
_OK_M1 = np.array([[0.4122214708, 0.5363325363, 0.0514459929],
                   [0.2119034982, 0.6806995451, 0.1073969566],
                   [0.0883024619, 0.2817188376, 0.6299787005]])
_OK_M2 = np.array([[0.2104542553, 0.7936177850, -0.0040720468],
                   [1.9779984951, -2.4285922050, 0.4505937099],
                   [0.0259040371, 0.7827717662, -0.8086757660]])


def as_float_rgb(pixels: np.ndarray) -> np.ndarray:
    """uint8 (…, 3) or float 0..1 → float64 0..1, last axis RGB."""
    arr = np.asarray(pixels)
    if arr.dtype == np.uint8:
        return arr[..., :3].astype(np.float64) / 255.0
    return np.clip(arr[..., :3].astype(np.float64), 0.0, 1.0)


def srgb_to_linear(rgb01: np.ndarray) -> np.ndarray:
    rgb01 = np.asarray(rgb01, dtype=np.float64)
    return np.where(rgb01 <= 0.04045, rgb01 / 12.92, ((rgb01 + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(lin: np.ndarray) -> np.ndarray:
    lin = np.clip(np.asarray(lin, dtype=np.float64), 0.0, 1.0)
    return np.where(lin <= 0.0031308, lin * 12.92, 1.055 * np.power(lin, 1 / 2.4) - 0.055)


def srgb_array_to_oklab(pixels: np.ndarray) -> np.ndarray:
    lin = srgb_to_linear(as_float_rgb(pixels))
    lms = np.cbrt(lin @ _OK_M1.T)
    return lms @ _OK_M2.T


def oklab_array_to_srgb(lab: np.ndarray) -> np.ndarray:
    lms = np.asarray(lab, dtype=np.float64) @ np.linalg.inv(_OK_M2).T
    lin = (lms ** 3) @ np.linalg.inv(_OK_M1).T
    return linear_to_srgb(lin)


def oklab_to_oklch_array(lab: np.ndarray) -> np.ndarray:
    lab = np.asarray(lab, dtype=np.float64)
    C = np.hypot(lab[..., 1], lab[..., 2])
    h = np.degrees(np.arctan2(lab[..., 2], lab[..., 1])) % 360.0
    return np.stack([lab[..., 0], C, h], axis=-1)


def srgb_array_to_lab_d50(pixels: np.ndarray) -> np.ndarray:
    """CIELab (D50, Bradford-adapted from sRGB D65) — the space ICC print workflows use."""
    lin = srgb_to_linear(as_float_rgb(pixels))
    xyz = lin @ (D65_TO_D50 @ SRGB_TO_XYZ_D65).T
    t = xyz / WHITE_D50
    eps, kappa = 216 / 24389, 24389 / 27
    f = np.where(t > eps, np.cbrt(t), (kappa * t + 16) / 116)
    L = 116 * f[..., 1] - 16
    a = 500 * (f[..., 0] - f[..., 1])
    b = 200 * (f[..., 1] - f[..., 2])
    return np.stack([L, a, b], axis=-1)


def relative_luminance_array(pixels: np.ndarray) -> np.ndarray:
    """WCAG 2.x relative luminance (piecewise sRGB, Rec.709 coefficients)."""
    lin = srgb_to_linear(as_float_rgb(pixels))
    return lin @ np.array([0.2126, 0.7152, 0.0722])
