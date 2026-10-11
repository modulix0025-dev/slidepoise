"""Type themes (AR ↔ EN pairings) and their validator.

Each theme names catalog families for: Arabic title, body, child name,
dedication, a vowelized-body font, and English title and body.

Blocking rules (named findings):

* every font exists in the catalog and is ``certified_print`` (a colour /
  quarantined / rejected font fails — ``theme_font_quarantined``);
* the font's script matches the slot (Arabic slots take AR fonts);
* QA *limits* are respected — a monospaced Arabic font only in title slots,
  the dedication only in a font with tatweel;
* ``ar_body_vowelized`` must be certified for vowelized body text;
* an Arabic name font without tatweel must carry the ``no_lam_tatweel_prefix``
  constraint, so «لـ<name>» is never set in it.

A font used outside the roles appendix F lists for it is a *warning*
(``theme_font_outside_appendix_roles``): pairing is a design decision the
operator owns, the validator only records it.
"""
from __future__ import annotations

import json
from pathlib import Path

from mxstudio.fonts.catalog import Catalog
from mxstudio.fonts.paths import THEMES_JSON

SLOTS = {  # slot → (script, typography role, appendix roles that fit)
    "ar_title": ("AR", "title", ("title", "effect", "name")),
    "ar_body": ("AR", "body", ("body",)),
    "ar_body_vowelized": ("AR", "body", ("body",)),
    "ar_name": ("AR", "child-name", ("name", "title")),
    "ar_dedication": ("AR", "handwriting-dedication", ("handwriting", "dedication", "name", "title", "body")),
    "en_title": ("EN", "title", ("title", "effect", "name")),
    "en_body": ("EN", "body", ("body",)),
}
TITLE_SLOTS = ("ar_title", "ar_name", "en_title")


def load_themes(path: Path = THEMES_JSON) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate_themes(data: dict, catalog: Catalog, qa: dict, *, minimum: int = 30) -> tuple[list[dict], list[dict]]:
    """(errors, warnings) — errors block, warnings are recorded for the operator."""
    qa_by_family = {f["family"]: f for f in qa.get("families", [])}
    errors: list[dict] = []
    warnings: list[dict] = []
    themes = data.get("themes", [])
    if len(themes) < minimum:
        errors.append({"finding": "theme_count_below_minimum", "detail": f"{len(themes)} < {minimum}"})
    seen = set()
    for theme in themes:
        tid = theme.get("id", "?")
        if tid in seen:
            errors.append({"finding": "theme_duplicate_id", "theme": tid})
        seen.add(tid)
        constraints = set(theme.get("constraints", []))
        overrides = theme.get("slot_roles", {})
        for slot, (script, _role, fit_roles) in SLOTS.items():
            family = theme.get(slot)
            err = lambda f, d="": errors.append({"finding": f, "theme": tid, "slot": slot,  # noqa: E731
                                                 "font": family, "detail": d})
            if not family:
                err("theme_slot_empty")
                continue
            fam = catalog.by_family(family)
            if fam is None:
                err("theme_font_not_in_catalog")
                continue
            entry = qa_by_family.get(family)
            if entry is None:
                err("theme_font_not_in_qa")
                continue
            if entry["status"] != "certified_print":
                err("theme_font_quarantined" if entry["status"] == "screen_only" else "theme_font_rejected",
                    entry["status"])
                continue
            if fam["script"] != script:
                err("theme_font_script_mismatch", f"{fam['script']} font in a {script} slot")
            allowed = set(entry.get("allowed_roles", []))
            caps = entry.get("capabilities", {})
            limit_ids = {r["finding"] for r in entry.get("reasons", []) if r["severity"] == "limit"}
            if "monospace_arabic" in limit_ids and slot not in TITLE_SLOTS:
                err("theme_monospace_outside_titles", "monospaced Arabic: effect titles only")
            if slot == "ar_dedication" and not caps.get("lam_tatweel_dedication"):
                err("theme_dedication_without_tatweel")
            if slot == "ar_body_vowelized" and not caps.get("vowelized_body"):
                err("theme_vowelized_body_not_certified")
            if slot == "ar_name" and not caps.get("lam_tatweel_dedication") and "no_lam_tatweel_prefix" not in constraints:
                err("theme_name_font_needs_no_lam_prefix_constraint")
            wanted = set(overrides.get(slot, fit_roles)) if isinstance(overrides.get(slot), list) else (
                {overrides[slot]} if slot in overrides else set(fit_roles))
            if not wanted & set(fam["roles"]):
                warnings.append({"finding": "theme_font_outside_appendix_roles", "theme": tid, "slot": slot,
                                 "font": family, "detail": f"appendix roles {fam['roles']}"})
            elif not wanted & allowed and allowed:
                warnings.append({"finding": "theme_font_role_limited_by_qa", "theme": tid, "slot": slot,
                                 "font": family, "detail": f"QA allows {sorted(allowed)}"})
    return errors, warnings


def theme_fonts(theme: dict) -> set[str]:
    return {theme[slot] for slot in SLOTS if theme.get(slot)}
