"""Typography system: role × page size × age band × script → starting size range, spacing and font eligibility.

Starting defaults come from today's templates (brief): body ≈13–16 pt on A5
Arabic, 16–22 pt on A4 Arabic, 11–13 pt on A5 English, titles 24–56 pt. Younger
readers get the top of each range. English A4 body is *derived* (A5 × ≈1.3,
the A4/A5 linear ratio is √2 but pages are read from further away) and marked
as such until the operator confirms it on printed proofs. These are starting
points for the fitter (``slidepoise.arabic.fit_text`` shrinks within
[min, max]), not a visual verdict.

Font eligibility rules:

* only ``certified_print`` fonts, and only for roles their QA allows;
* Arabic **vowelized body** text only in fonts whose QA capability
  ``vowelized_body`` is true (harakat collision test clean);
* the dedication and any «لـ<name>» form only in fonts that have tatweel;
* line spacing is never below the font's measured minimum safe spacing.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

ROLES = ("title", "child-name", "body", "bubble", "sound-effect", "handwriting-dedication", "caption",
         "coloring-outline")
PAGES = ("A5", "A4")
AGES = ("3-5", "6-8", "9-12")
SCRIPTS = ("ar", "en")
CUSTOMER_STYLEABLE = ("child-name", "handwriting-dedication")
#: typography role → catalog roles (appendix F `roles` column) a font must carry to take it
CATALOG_ROLES = {"title": ("title",), "child-name": ("name", "title"), "body": ("body",),
                 "bubble": ("bubble", "body"), "sound-effect": ("effect", "title"),
                 "handwriting-dedication": ("handwriting", "dedication", "name", "title"), "caption": ("body", "ui"),
                 "coloring-outline": ("coloring",)}
#: role → (A5 min, A5 max, A4 min, A4 max, line spacing, weight) per script, sizes in pt
_BASE = {
    "ar": {"title": (24, 40, 32, 56, 1.0, 700), "child-name": (28, 48, 36, 56, 1.0, 700),
           "body": (13, 16, 16, 22, 1.2, 400), "bubble": (13, 17, 16, 22, 1.15, 400),
           "sound-effect": (28, 56, 36, 72, 1.0, 800), "handwriting-dedication": (16, 24, 20, 30, 1.2, 400),
           "caption": (10, 12, 12, 14, 1.15, 400), "coloring-outline": (36, 56, 48, 72, 1.0, 400)},
    "en": {"title": (24, 40, 32, 56, 1.0, 700), "child-name": (28, 48, 36, 56, 1.0, 700),
           "body": (11, 13, 14, 17, 1.2, 400), "bubble": (11, 14, 14, 18, 1.15, 400),
           "sound-effect": (28, 56, 36, 72, 1.0, 800), "handwriting-dedication": (14, 22, 18, 28, 1.2, 400),
           "caption": (9, 10, 11, 12, 1.15, 400), "coloring-outline": (36, 56, 48, 72, 1.0, 400)},
}
DERIVED = {("en", "A4", "body"), ("en", "A4", "bubble"), ("en", "A4", "caption")}
_AGE_POSITION = {"3-5": 1.0, "6-8": 0.5, "9-12": 0.0}  # where the default sits inside [min, max]


@dataclass(frozen=True)
class RoleSpec:
    role: str
    page: str
    age: str
    script: str
    min_pt: float
    default_pt: float
    max_pt: float
    line_spacing: float
    weight: int
    vowelized: bool
    customer_styleable: bool
    source: str

    def as_dict(self) -> dict:
        return asdict(self)


def _half(value: float) -> float:
    return round(value * 2) / 2


def defaults(role: str, page: str, age: str, script: str) -> RoleSpec:
    if role not in ROLES or page not in PAGES or age not in AGES or script not in SCRIPTS:
        raise ValueError(f"unknown cell {role}/{page}/{age}/{script}")
    a5_min, a5_max, a4_min, a4_max, spacing, weight = _BASE[script][role]
    lo, hi = (a5_min, a5_max) if page == "A5" else (a4_min, a4_max)
    position = _AGE_POSITION[age]
    default = _half(lo + (hi - lo) * position)
    # the youngest readers get the upper part of the range as their floor too
    floor = _half(lo + (hi - lo) * position * 0.5)
    vowelized = script == "ar" and age in ("3-5", "6-8") and role in ("body", "bubble", "caption")
    source = "derived: A5 × ≈1.3, confirm on printed proof" if (script, page, role) in DERIVED else "brief defaults"
    return RoleSpec(role=role, page=page, age=age, script=script, min_pt=floor, default_pt=default, max_pt=float(hi),
                    line_spacing=spacing, weight=weight, vowelized=vowelized,
                    customer_styleable=role in CUSTOMER_STYLEABLE, source=source)


def table() -> list[dict]:
    """The full role × page × age × script grid (for the Console and the specimen)."""
    return [defaults(r, p, a, s).as_dict() for s in SCRIPTS for r in ROLES for p in PAGES for a in AGES]


def _qa_entry(qa: dict, family: str) -> dict | None:
    return next((f for f in qa.get("families", []) if f["family"] == family), None)


def font_allowed(family: str, role: str, script: str, qa: dict, *, vowelized: bool = False,
                 lam_prefix: bool = False) -> tuple[bool, list[str]]:
    """(allowed, named reasons) for using `family` in `role`."""
    entry = _qa_entry(qa, family)
    if entry is None:
        return False, ["font_not_in_qa"]
    reasons = []
    if entry["status"] != "certified_print":
        reasons.append(f"font_{entry['status']}")
    if (entry["script"] == "AR") != (script == "ar"):
        reasons.append("font_script_mismatch")
    if not set(CATALOG_ROLES[role]) & set(entry.get("allowed_roles", [])):
        reasons.append("role_not_allowed_for_font")
    caps = entry.get("capabilities", {})
    if script == "ar" and vowelized and role in ("body", "bubble", "caption") and not caps.get("vowelized_body"):
        reasons.append("font_not_certified_for_vowelized_body")
    if script == "ar" and vowelized and role not in ("body", "bubble", "caption") and not caps.get("vowelized_text"):
        reasons.append("font_not_certified_for_vowelized_text")
    if script == "ar" and (lam_prefix or role == "handwriting-dedication") and not caps.get("lam_tatweel_dedication"):
        reasons.append("font_has_no_tatweel")
    return not reasons, reasons


def line_spacing(family: str, spec: RoleSpec, qa: dict) -> float:
    """Role spacing, raised to the font's measured minimum safe spacing (never lowered)."""
    entry = _qa_entry(qa, family) or {}
    measured = entry.get("min_safe_line_spacing") or 1.0
    return round(max(spec.line_spacing, float(measured)), 3)
