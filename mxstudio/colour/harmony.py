"""Colour harmonies by OKLCH hue rotation at controlled lightness and chroma.

Rule: a harmony is geometry on the OKLCH hue circle — nothing more. The base colour's
hue is rotated by fixed published offsets; lightness and chroma are either kept from the
base or set by the caller, so every member of a scheme has the same perceived weight.
Members that fall outside sRGB are fitted by chroma reduction at constant L and h, and
the result says so (``in_gamut``). Which scheme *looks* right is the host Agent's call.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from .oklch import ColourLike, from_oklch, to_oklch

SCHEMES: dict[str, tuple[float, ...]] = {
    "analogous": (-30.0, 0.0, 30.0),
    "complementary": (0.0, 180.0),
    "split_complementary": (0.0, 150.0, 210.0),
    "triadic": (0.0, 120.0, 240.0),
    "tetradic": (0.0, 60.0, 180.0, 240.0),  # rectangle: two complementary pairs 60° apart
    "square": (0.0, 90.0, 180.0, 270.0),
}


@dataclass(frozen=True)
class HarmonyMember:
    hex: str
    L: float
    C: float
    h: float
    offset: float
    in_gamut: bool

    def as_dict(self) -> dict:
        return asdict(self)


def rotate_hues(base: ColourLike, scheme: str) -> list[float]:
    if scheme not in SCHEMES:
        raise ValueError(f"unknown harmony scheme {scheme!r}; known: {sorted(SCHEMES)}")
    _L, _C, h = to_oklch(base)
    return [(h + off) % 360.0 for off in SCHEMES[scheme]]


def harmony(base: ColourLike, scheme: str, lightness: float | None = None,
            chroma: float | None = None) -> list[HarmonyMember]:
    """Members of ``scheme`` around ``base`` (offset 0 is the base hue).

    ``lightness`` (OKLCH L, 0..1) and ``chroma`` (OKLCH C, typically 0..0.37) are held
    constant for all members when given; otherwise the base colour's values are used.
    """
    L0, C0, h0 = to_oklch(base)
    L = L0 if lightness is None else float(lightness)
    C = C0 if chroma is None else float(chroma)
    if not 0.0 <= L <= 1.0:
        raise ValueError("lightness must be within 0..1 (OKLCH L)")
    if C < 0.0:
        raise ValueError("chroma must be ≥ 0")
    members = []
    for off in SCHEMES[scheme] if scheme in SCHEMES else rotate_hues(base, scheme):
        h = (h0 + off) % 360.0
        hx, ok = from_oklch(L, C, h)
        members.append(HarmonyMember(hx, round(L, 5), round(C, 5), round(h, 3), off, ok))
    return members


def harmony_hex(base: ColourLike, scheme: str, lightness: float | None = None,
                chroma: float | None = None) -> list[str]:
    return [m.hex for m in harmony(base, scheme, lightness, chroma)]


def all_harmonies(base: ColourLike, lightness: float | None = None, chroma: float | None = None) -> dict:
    return {name: [m.as_dict() for m in harmony(base, name, lightness, chroma)] for name in SCHEMES}
