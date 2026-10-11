"""M7 customer font choice: «اختار خط اسم طفلك» + dedication font, from an operator-curated subset.

Rules:

* the operator curates **12–24** fonts in total; every one is
  ``certified_print`` and already installed (by its exact install name) on
  **every** export machine that acknowledged the sync;
* the choice applies only to roles marked customer-styleable in
  :mod:`mxstudio.fonts.typography` (child name, dedication); a dedication
  option in Arabic must have tatweel («لـ<name>»);
* the preview uses the real fitter (``slidepoise.arabic.fit_text``) on the
  installed font, never an approximation;
* an optional price per role (EGP, ≥ 0);
* if the chosen font is missing on the exporting machine (or was never an
  option), the template default is used and a **visible note** says so.
"""
from __future__ import annotations

from dataclasses import asdict

import jsonschema

from slidepoise.arabic.fit import fit_text
from slidepoise.arabic.fonts import FontRegistry, normalize_family

from mxstudio.fonts.typography import CUSTOMER_STYLEABLE, font_allowed

MIN_OPTIONS, MAX_OPTIONS = 12, 24
PROMPT_AR = {"child-name": "اختار خط اسم طفلك", "handwriting-dedication": "اختار خط الإهداء"}
FALLBACK_NOTE_AR = "الخط اللي اخترته مش متاح على جهاز الطباعة، فاستخدمنا خط القالب الأصلي «{default}»."
FALLBACK_NOTE_EN = "The chosen font is not available on the print machine; the template font «{default}» was used."

SCHEMA = {
    "type": "object", "required": ["set_id", "script", "roles"], "additionalProperties": False,
    "properties": {
        "schema": {"const": "mx.fonts.customer_choice/1"},
        "set_id": {"type": "string", "minLength": 1},
        "script": {"enum": ["ar", "en"]},
        "roles": {"type": "object", "minProperties": 1, "additionalProperties": {
            "type": "object", "required": ["prompt_ar", "default", "options"], "additionalProperties": False,
            "properties": {
                "prompt_ar": {"type": "string"},
                "default": {"type": "object", "required": ["family", "install_name"]},
                "price_egp": {"type": ["number", "null"], "minimum": 0},
                "options": {"type": "array", "minItems": 1, "items": {
                    "type": "object", "required": ["family", "install_name"], "additionalProperties": False,
                    "properties": {"family": {"type": "string"}, "install_name": {"type": "string"},
                                   "label_ar": {"type": "string"}}}},
            }}},
    },
}


class ChoiceRefused(ValueError):
    def __init__(self, findings: list[dict]):
        self.findings = findings
        super().__init__("; ".join(f"{f['finding']}: {f.get('font', f.get('detail', ''))}" for f in findings))


def build_payload(set_id: str, script: str, curated: dict[str, list[str]], defaults: dict[str, str],
                  install_names: dict[str, str], qa: dict, installed_by_machine: dict[str, set[str]],
                  prices: dict[str, float] | None = None) -> dict:
    """`curated`: role → catalog families. Refuses (named) anything the rules above forbid."""
    findings: list[dict] = []
    total = {fam for fams in curated.values() for fam in fams}
    if not MIN_OPTIONS <= len(total) <= MAX_OPTIONS:
        findings.append({"finding": "choice_subset_size", "detail": f"{len(total)} fonts; must be "
                                                                      f"{MIN_OPTIONS}–{MAX_OPTIONS}"})
    roles = {}
    for role, families in curated.items():
        if role not in CUSTOMER_STYLEABLE:
            findings.append({"finding": "choice_role_not_customer_styleable", "detail": role})
            continue
        options = []
        for family in [*families, defaults[role]]:
            ok, reasons = font_allowed(family, role, script, qa)
            for reason in reasons:
                findings.append({"finding": f"choice_{reason}", "font": family, "role": role})
            name = install_names.get(family)
            if not name:
                findings.append({"finding": "choice_font_has_no_install_name", "font": family, "role": role})
                continue
            for machine, names in sorted(installed_by_machine.items()):
                if normalize_family(name) not in {normalize_family(n) for n in names}:
                    findings.append({"finding": "choice_font_not_installed_on_machine", "font": family,
                                     "role": role, "detail": machine})
            if family in families:
                options.append({"family": family, "install_name": name})
        roles[role] = {"prompt_ar": PROMPT_AR[role], "options": options,
                       "default": {"family": defaults[role], "install_name": install_names.get(defaults[role], "")},
                       "price_egp": (prices or {}).get(role)}
    if findings:
        raise ChoiceRefused(findings)
    payload = {"schema": "mx.fonts.customer_choice/1", "set_id": set_id, "script": script, "roles": roles}
    jsonschema.validate(payload, SCHEMA)
    return payload


def resolve_choice(payload: dict, role: str, chosen_family: str | None, installed_on_exporter) -> dict:
    """The font actually used for `role` on this exporter, with a visible note when it falls back."""
    spec = payload["roles"][role]
    default = spec["default"]
    has = installed_on_exporter.has if isinstance(installed_on_exporter, FontRegistry) else (
        lambda n: normalize_family(n) in {normalize_family(x) for x in installed_on_exporter})
    option = next((o for o in spec["options"] if o["family"] == chosen_family), None)
    if chosen_family is None:
        return {"family": default["family"], "install_name": default["install_name"], "fallback": False}
    if option and has(option["install_name"]):
        return {"family": option["family"], "install_name": option["install_name"], "fallback": False}
    return {"family": default["family"], "install_name": default["install_name"], "fallback": True,
            "reason": "choice_not_an_option" if option is None else "choice_not_installed_on_exporter",
            "note_ar": FALLBACK_NOTE_AR.format(default=default["family"]),
            "note_en": FALLBACK_NOTE_EN.format(default=default["family"])}


def preview(install_name: str, text: str, box_w_pt: float, box_h_pt: float, registry: FontRegistry, *,
            max_size_pt: float = 48.0, min_size_pt: float = 14.0) -> dict:
    """Live preview through the real fitter on the installed font (raises LookupError if not installed)."""
    return asdict(fit_text(text, box_w_pt, box_h_pt, install_name, registry=registry, max_size_pt=max_size_pt,
                           min_size_pt=min_size_pt))
