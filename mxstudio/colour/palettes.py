"""Curated children's palettes: catalogue, builder and validator.

Rule: every curated palette is six deck roles (background, primary, secondary, accent,
text, outline), tagged by age band, mood and theme, and must pass objective checks
before it ships:

* text on background: WCAG 2.x ≥ 4.5 *and* APCA |Lc| ≥ 75 (body text);
* outline on background: WCAG ≥ 3.0 (non-text floor);
* every role printable on every bundled press profile: ΔE2000 ≤ the print warning
  threshold and total ink ≤ the TAC limit;
* primary, secondary and accent distinguishable (OKLab ΔE ≥ 0.05).

The catalogue is *built* from hand-curated seeds (``kids_palettes.seeds.json``: name,
tags, mode, and three hand-picked brand colours). The builder derives background, text
and outline in OKLCH from the primary hue, and pulls any seed colour that would print
dull back into the press gamut by reducing OKLCH chroma at constant L and h. Which
palette suits a story is a taste call left to the host Agent and the operator.

Build:  python -m mxstudio.colour.palettes build
Check:  python -m mxstudio.colour.palettes check
"""
from __future__ import annotations

import argparse
import json
import sys
from functools import lru_cache
from itertools import combinations
from pathlib import Path
from typing import Iterable, Mapping

from .contrast import apca_lc, wcag_contrast
from .cvd import simulate_colour
from .oklch import delta_e_ok, from_oklch, to_hex, to_oklch
from .print_safety import DELTA_E_WARN, PrintSettings, check_colour, known_profiles
from .roles import ROLES, solve_text_colour

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "catalog" / "palettes" / "kids_palettes.json"
SEEDS = ROOT / "catalog" / "palettes" / "kids_palettes.seeds.json"
AGES = ("3-5", "6-8", "9-12")
TEXT_MIN_WCAG, TEXT_MIN_APCA, OUTLINE_MIN_WCAG, DISTINCT_MIN_OK = 4.5, 75.0, 3.0, 0.05
PRINT_FIT_TARGET = DELTA_E_WARN - 1.0  # builder aims 1 ΔE00 inside the warning threshold
REQUIRED_THEMES = ("sea", "space", "desert_egypt", "candy", "forest", "night", "festival")


def _profiles() -> list[str]:
    return sorted(known_profiles())


def _print_worst(hx: str, profiles: Iterable[str]) -> tuple[float, float]:
    rows = [check_colour(hx, PrintSettings(profile=p)) for p in profiles]
    return max(r["delta_e2000"] for r in rows), max(r["tac"] for r in rows)


def fit_to_press(hx: str, profiles: Iterable[str] | None = None, target: float = PRINT_FIT_TARGET) -> tuple[str, bool]:
    """Reduce OKLCH chroma (L, h fixed) until the colour prints within ``target`` ΔE00 on all profiles."""
    profiles = list(profiles or _profiles())
    worst, _ = _print_worst(hx, profiles)
    if worst <= target:
        return to_hex(hx), False
    L, C, h = to_oklch(hx)
    for step in range(1, 40):
        cand, _ = from_oklch(L, C * (1.0 - 0.025 * step), h)
        if _print_worst(cand, profiles)[0] <= target:
            return cand, True
    raise ValueError(f"{hx} cannot be fitted to the press gamut at its lightness")


def build_palette(seed: Mapping) -> dict:
    """Seed → full six-role palette (deterministic)."""
    mode = seed.get("mode", "light")
    fitted = {}
    adjusted = []
    for role in ("primary", "secondary", "accent"):
        fitted[role], changed = fit_to_press(seed[role])
        if changed:
            adjusted.append(role)
    L, C, h = to_oklch(fitted["primary"])
    if mode == "dark":
        background = seed.get("background") or from_oklch(0.25, min(0.05, C * 0.35), h)[0]
        text = seed.get("text") or solve_text_colour(background, h, 0.02, dark_text=False)
        outline = seed.get("outline") or from_oklch(0.92, min(0.04, C), h)[0]
    else:
        background = seed.get("background") or from_oklch(0.975, min(0.02, C * 0.15), h)[0]
        text = seed.get("text") or solve_text_colour(background, h, min(0.045, C * 0.4), dark_text=True)
        outline = seed.get("outline") or from_oklch(0.33, min(0.08, C * 0.6), h)[0]
    for role, value in (("background", background), ("text", text), ("outline", outline)):
        fitted[role], changed = fit_to_press(value)
        if changed:
            adjusted.append(role)
    roles = {r: fitted[r] for r in ROLES}
    return {
        "id": seed["id"], "name_en": seed["name_en"], "name_ar": seed["name_ar"],
        "themes": list(seed["themes"]), "moods": list(seed["moods"]), "ages": list(seed["ages"]),
        "mode": mode, "roles": roles,
        "oklch": {r: [round(v, 4) for v in to_oklch(hx)] for r, hx in roles.items()},
        "seed": {r: seed[r] for r in ("primary", "secondary", "accent")},
        "print_fitted_roles": adjusted,
    }


def validate_palette(pal: Mapping, profiles: Iterable[str] | None = None) -> dict:
    """Objective checks for one palette. Returns facts and a list of failed check names."""
    profiles = list(profiles or _profiles())
    roles = pal["roles"]
    failures = []
    for r in ROLES:
        if r not in roles:
            failures.append(f"missing_role:{r}")
    if failures:
        return {"id": pal.get("id"), "ok": False, "failures": failures}
    t_ratio = wcag_contrast(roles["text"], roles["background"])
    t_lc = apca_lc(roles["text"], roles["background"])
    o_ratio = wcag_contrast(roles["outline"], roles["background"])
    if t_ratio < TEXT_MIN_WCAG:
        failures.append("text_wcag")
    if abs(t_lc) < TEXT_MIN_APCA:
        failures.append("text_apca")
    if o_ratio < OUTLINE_MIN_WCAG:
        failures.append("outline_wcag")
    print_rows = {}
    for p in profiles:
        settings = PrintSettings(profile=p)
        rows = {r: check_colour(hx, settings) for r, hx in roles.items()}
        print_rows[p] = {"max_delta_e2000": max(v["delta_e2000"] for v in rows.values()),
                         "max_tac": max(v["tac"] for v in rows.values()),
                         "cmyk": {r: list(v["cmyk"]) for r, v in rows.items()}}
        if any(v["warn_dull"] for v in rows.values()):
            failures.append(f"print_delta_e:{p}")
        if any(v["blocking"] for v in rows.values()):
            failures.append(f"print_tac:{p}")
    distinct = min(delta_e_ok(roles[a], roles[b]) for a, b in combinations(("primary", "secondary", "accent"), 2))
    if distinct < DISTINCT_MIN_OK:
        failures.append("roles_not_distinct")
    cvd_min = {}
    for kind in ("protan", "deutan", "tritan"):
        sims = [simulate_colour(roles[r], kind) for r in ("primary", "secondary", "accent")]
        cvd_min[kind] = round(min(delta_e_ok(a, b) for a, b in combinations(sims, 2)), 4)
    for field, allowed in (("ages", AGES),):
        if not set(pal.get(field, [])) <= set(allowed) or not pal.get(field):
            failures.append(f"bad_{field}")
    if not pal.get("themes") or not pal.get("moods") or not pal.get("name_ar") or not pal.get("name_en"):
        failures.append("missing_tags_or_names")
    return {"id": pal.get("id"), "ok": not failures, "failures": failures,
            "text_wcag": round(t_ratio, 2), "text_apca_lc": round(t_lc, 1), "outline_wcag": round(o_ratio, 2),
            "print": print_rows, "accent_distinct_ok": round(distinct, 4),
            "cvd_min_delta_e_ok": cvd_min}


def build_catalog(seeds_path: Path = SEEDS, out_path: Path = CATALOG) -> dict:
    seeds = json.loads(Path(seeds_path).read_text(encoding="utf-8"))
    palettes = []
    for seed in seeds["palettes"]:
        pal = build_palette(seed)
        pal["checks"] = validate_palette(pal)
        palettes.append(pal)
    profiles = {k: {"file": v["file"], "sha256": v["sha256"], "licence": v["licence"]}
                for k, v in known_profiles().items()}
    catalog = {
        "version": 1,
        "generated_by": "python -m mxstudio.colour.palettes build",
        "rules": {"text_min_wcag": TEXT_MIN_WCAG, "text_min_apca_abs": TEXT_MIN_APCA,
                  "outline_min_wcag": OUTLINE_MIN_WCAG, "print_delta_e2000_max": DELTA_E_WARN,
                  "tac_limit_percent": PrintSettings().tac_limit, "distinct_min_delta_e_ok": DISTINCT_MIN_OK,
                  "intent": "relative colorimetric, no black-point compensation"},
        "profiles": profiles,
        "licence": "CC0-1.0 (palettes curated for ModuleX Magazine Studio; colour values are facts)",
        "palettes": palettes,
    }
    Path(out_path).write_text(json.dumps(catalog, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return catalog


@lru_cache(maxsize=1)
def _load(path_str: str) -> dict:
    return json.loads(Path(path_str).read_text(encoding="utf-8"))


def load_catalog(path: Path = CATALOG) -> dict:
    return _load(str(path))


def list_palettes(theme: str | None = None, age: str | None = None, mood: str | None = None,
                  mode: str | None = None, path: Path = CATALOG) -> list[dict]:
    """Filter the curated catalogue by tags (all filters optional, combined with AND)."""
    out = []
    for pal in load_catalog(path)["palettes"]:
        if theme and theme not in pal["themes"]:
            continue
        if age and age not in pal["ages"]:
            continue
        if mood and mood not in pal["moods"]:
            continue
        if mode and pal["mode"] != mode:
            continue
        out.append(pal)
    return out


def get_palette(palette_id: str, path: Path = CATALOG) -> dict:
    for pal in load_catalog(path)["palettes"]:
        if pal["id"] == palette_id:
            return pal
    raise KeyError(palette_id)


def nearest_palettes(colours: Iterable[str], k: int = 5, path: Path = CATALOG) -> list[tuple[str, float]]:
    """Curated palettes closest to measured art colours (mean nearest-role OKLab ΔE)."""
    cols = list(colours)
    scored = []
    for pal in load_catalog(path)["palettes"]:
        roles = [pal["roles"][r] for r in ("primary", "secondary", "accent")]
        score = sum(min(delta_e_ok(c, r) for r in roles) for c in cols) / max(1, len(cols))
        scored.append((pal["id"], round(score, 4)))
    return sorted(scored, key=lambda x: x[1])[:k]


def validate_catalog(path: Path = CATALOG) -> dict:
    cat = json.loads(Path(path).read_text(encoding="utf-8"))
    results = [validate_palette(p) for p in cat["palettes"]]
    ids = [p["id"] for p in cat["palettes"]]
    themes = {t for p in cat["palettes"] for t in p["themes"]}
    return {"count": len(results), "failed": [r for r in results if not r["ok"]],
            "duplicate_ids": sorted({i for i in ids if ids.count(i) > 1}),
            "missing_required_themes": [t for t in REQUIRED_THEMES if t not in themes],
            "themes": sorted(themes)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mxstudio.colour.palettes")
    parser.add_argument("command", choices=["build", "check"])
    args = parser.parse_args(argv)
    if args.command == "build":
        cat = build_catalog()
        bad = [p["id"] for p in cat["palettes"] if not p["checks"]["ok"]]
        print(f"built {len(cat['palettes'])} palettes; failing: {bad}")
        return 1 if bad else 0
    report = validate_catalog()
    print(json.dumps({k: v for k, v in report.items() if k != "themes"}, ensure_ascii=False, indent=1))
    return 1 if report["failed"] or report["duplicate_ids"] or report["missing_required_themes"] else 0


if __name__ == "__main__":
    sys.exit(main())
