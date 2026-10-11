"""Deck-level palette roles: background, primary, secondary, accent, text, outline.

Rule: one magazine = one palette. Roles are derived once per deck from the accepted art's
measured palette (or a curated palette) and every page resolves colours through the role
names, so frames and text stay consistent from page to page. This module derives roles,
checks the *objective* role pairs (text on background must meet WCAG 2.x; outline must
meet the 3:1 non-text floor) and reports pages whose colours drift from the deck roles.
Drift is an advisory fact — the operator may intend it — never a blocking verdict.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Iterable, Mapping

from .contrast import apca_lc, wcag_contrast
from .oklch import delta_e_ok, from_oklch, hue_distance, to_hex, to_oklch

ROLES = ("background", "primary", "secondary", "accent", "text", "outline")
TEXT_MIN_WCAG = 4.5
TEXT_TARGET_WCAG = 7.0
OUTLINE_MIN_WCAG = 3.0
DRIFT_TOLERANCE_OK = 0.03  # OKLab ΔE; ≈ 1.5 JND


@dataclass
class DeckPalette:
    background: str
    primary: str
    secondary: str
    accent: str
    text: str
    outline: str
    mode: str = "light"
    source: str = "derived"
    notes: list[str] = field(default_factory=list)

    def roles(self) -> dict[str, str]:
        return {r: getattr(self, r) for r in ROLES}

    def as_dict(self) -> dict:
        return asdict(self)


def _candidates(palette) -> list[tuple[str, float]]:
    """Accept an :func:`extract_palette` result, a list of hexes or a list of (hex, area)."""
    if isinstance(palette, Mapping):
        cols = [(c["hex"], float(c.get("area", 1.0))) for c in palette.get("colours", [])]
        if not cols:
            cols = [(c["hex"], float(c.get("area", 1.0))) for c in palette.get("skin", [])]
        return cols
    out = []
    for item in palette:
        if isinstance(item, str):
            out.append((to_hex(item), 1.0))
        else:
            out.append((to_hex(item[0]), float(item[1])))
    return out


def _mean_lightness(palette) -> float | None:
    if not isinstance(palette, Mapping):
        return None
    groups = palette.get("colours", []) + palette.get("skin", []) + palette.get("neutrals", [])
    area = sum(c["area"] for c in groups)
    if area <= 0:
        return None
    return sum(c["oklch"][0] * c["area"] for c in groups) / area


def solve_text_colour(bg: str, hue: float, chroma: float, dark_text: bool) -> str:
    """Walk OKLCH L away from the background until text meets the target ratio."""
    steps = [0.34 - 0.02 * i for i in range(15)] if dark_text else [0.90 + 0.007 * i for i in range(15)]
    best = None
    for L in steps:
        hx, _ = from_oklch(L, chroma, hue)
        best = hx
        if wcag_contrast(hx, bg) >= TEXT_TARGET_WCAG and abs(apca_lc(hx, bg)) >= 90:
            return hx
    return best or ("#1a1a1a" if dark_text else "#fafafa")


def derive_roles(palette, mode: str = "auto") -> DeckPalette:
    """Derive the six roles from a measured or curated palette.

    ``mode``: "light" (light paper, dark text), "dark" (night/space pages) or "auto"
    (dark when the art's area-weighted OKLCH lightness is below 0.45).
    """
    cands = _candidates(palette)
    if not cands:
        raise ValueError("palette has no chromatic or skin colours to derive roles from")
    notes: list[str] = []
    if mode == "auto":
        mean_l = _mean_lightness(palette)
        mode = "dark" if (mean_l is not None and mean_l < 0.45) else "light"
    lch = {hx: to_oklch(hx) for hx, _ in cands}
    ordered = sorted(cands, key=lambda c: -c[1])
    vivid = [c for c in ordered if lch[c[0]][1] >= 0.05] or ordered
    primary = vivid[0][0]
    ph = lch[primary][2]
    rest = [c for c in ordered if c[0] != primary]
    secondary = next((c[0] for c in rest if hue_distance(lch[c[0]][2], ph) >= 25.0
                      or delta_e_ok(c[0], primary) >= 0.08), None)
    if secondary is None:
        L, C, h = lch[primary]
        secondary, _ = from_oklch(min(0.85, L + 0.15), C * 0.8, h + 30.0)
        notes.append("secondary synthesised (analogous +30°): art has one dominant hue")
    remaining = [c[0] for c in rest if c[0] != secondary]
    if remaining:
        accent = max(remaining, key=lambda hx: lch[hx][1] * (0.2 + hue_distance(lch[hx][2], ph) / 180.0))
    else:
        L, C, h = lch[primary]
        accent, _ = from_oklch(0.72, max(0.12, C), h + 180.0)
        notes.append("accent synthesised (complement of primary)")
    pc = lch[primary][1]
    if mode == "dark":
        background, _ = from_oklch(0.24, min(0.05, pc * 0.35), ph)
        text = solve_text_colour(background, ph, 0.02, dark_text=False)
        outline, _ = from_oklch(0.93, min(0.04, pc), ph)
    else:
        background, _ = from_oklch(0.975, min(0.018, pc * 0.15), ph)
        text = solve_text_colour(background, ph, min(0.045, pc * 0.4), dark_text=True)
        outline, _ = from_oklch(0.33, min(0.08, pc * 0.6), ph)
    return DeckPalette(background, primary, secondary, accent, text, outline, mode=mode,
                       source="extracted" if isinstance(palette, Mapping) else "given", notes=notes)


def check_roles(deck: DeckPalette | Mapping[str, str]) -> list[dict]:
    """Objective role-pair findings. Text contrast below WCAG AA is blocking."""
    roles = deck.roles() if isinstance(deck, DeckPalette) else dict(deck)
    findings = []
    bg = roles["background"]
    ratio = wcag_contrast(roles["text"], bg)
    lc = apca_lc(roles["text"], bg)
    if ratio < TEXT_MIN_WCAG:
        findings.append({"finding": "role_text_contrast_below_minimum", "blocking": True,
                         "wcag_ratio": round(ratio, 2), "apca_lc": round(lc, 1), "min": TEXT_MIN_WCAG,
                         "ar": "لون الكلام على لون الخلفية مش مقروء كفاية (أقل من ٤٫٥:١).",
                         "en": "Text role on background is below WCAG AA 4.5:1."})
    o_ratio = wcag_contrast(roles["outline"], bg)
    if o_ratio < OUTLINE_MIN_WCAG:
        findings.append({"finding": "role_outline_contrast_low", "blocking": False,
                         "wcag_ratio": round(o_ratio, 2), "min": OUTLINE_MIN_WCAG,
                         "ar": "لون الحدود قريب من الخلفية (أقل من ٣:١) — تنبيه بس.",
                         "en": "Outline role is under the 3:1 non-text floor (advisory)."})
    return findings


def nearest_role(deck: DeckPalette | Mapping[str, str], colour) -> tuple[str, float]:
    roles = deck.roles() if isinstance(deck, DeckPalette) else dict(deck)
    return min(((r, delta_e_ok(colour, hx)) for r, hx in roles.items()), key=lambda x: x[1])


def consistency_report(deck: DeckPalette | Mapping[str, str], pages: Iterable[Mapping],
                       tolerance: float = DRIFT_TOLERANCE_OK) -> dict:
    """Compare each page's used colours with the deck roles.

    ``pages``: iterables of ``{"page_id": ..., "colours": {role_or_label: hex}}``. A key that
    is a role name is compared with that role; any other label is snapped to the nearest
    role. Every deviation beyond ``tolerance`` (OKLab ΔE) is an advisory drift fact.
    """
    roles = deck.roles() if isinstance(deck, DeckPalette) else dict(deck)
    drifts = []
    checked = 0
    for page in pages:
        for label, hx in page.get("colours", {}).items():
            checked += 1
            role = label if label in roles else nearest_role(roles, hx)[0]
            d = delta_e_ok(hx, roles[role])
            if d > tolerance:
                drifts.append({"page_id": page.get("page_id"), "label": label, "role": role,
                               "used": to_hex(hx), "deck": roles[role], "delta_e_ok": round(d, 4)})
    return {"checked": checked, "drifts": drifts, "consistent": not drifts, "blocking": False,
            "finding": "palette_role_drift" if drifts else None, "tolerance_delta_e_ok": tolerance}
