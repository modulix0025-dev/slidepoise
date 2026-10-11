"""One semantic page map, four payloads: ar_boy, ar_girl, en_boy, en_girl.

A text object may carry ``payloads: {variant: {runs|text, style?}}``. Resolving
a spec for one variant produces an ordinary renderer spec: the payload's words
replace the object's, Arabic variants are right-to-left (``ar-EG``) and English
ones left-to-right (``en-US``) unless the payload says otherwise. Geometry is
shared; every variant is re-fitted afterwards by the fitter, never assumed to fit.

Gendered Arabic is *written* per variant by the author (verbs, pronouns,
adjectives), not produced by find/replace on a boy's text.
"""
from __future__ import annotations

import copy

VARIANTS = ("ar_boy", "ar_girl", "en_boy", "en_girl")
_DIRECTION = {"ar": ("rtl", "ar-EG"), "en": ("ltr", "en-US")}


def _language(variant: str) -> str:
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}; expected one of {VARIANTS}")
    return variant.split("_", 1)[0]


def resolve_object(obj: dict, variant: str) -> dict:
    language = _language(variant)
    if "payloads" not in obj:
        return copy.deepcopy(obj)
    payloads = obj["payloads"]
    if variant not in payloads:
        raise ValueError(f"object {obj.get('id')!r} has no payload for {variant}")
    payload = payloads[variant]
    resolved = {key: copy.deepcopy(value) for key, value in obj.items() if key != "payloads"}
    for key in ("text", "runs"):
        resolved.pop(key, None)
    if "runs" in payload:
        resolved["runs"] = copy.deepcopy(payload["runs"])
    elif "text" in payload:
        resolved["text"] = payload["text"]
    else:
        raise ValueError(f"payload {variant} of {obj.get('id')!r} has neither runs nor text")
    direction, lang = _DIRECTION[language]
    style = {**resolved.get("style", {}), **payload.get("style", {})}
    style.setdefault("direction", direction)
    style.setdefault("lang", lang)
    if "alignment" not in payload.get("style", {}) and "alignment" in style:
        # A shared alignment written for one direction is mirrored for the other.
        mirrored = {"left": "right", "right": "left"}
        base_dir = obj.get("style", {}).get("direction", "rtl")
        if base_dir != style["direction"]:
            style["alignment"] = mirrored.get(style["alignment"], style["alignment"])
    resolved["style"] = style
    return resolved


def resolve_spec(spec: dict, variant: str, base_names: dict[str, str] | None = None) -> dict:
    out = {key: copy.deepcopy(value) for key, value in spec.items() if key != "slides"}
    out["language"] = _DIRECTION[_language(variant)][1]
    out["slides"] = [{**{k: copy.deepcopy(v) for k, v in slide.items() if k != "objects"},
                      "objects": [resolve_object(obj, variant) for obj in slide.get("objects", [])]}
                     for slide in spec.get("slides", [])]
    if base_names:
        problems = name_token_findings(out, base_names[variant])
        if problems:
            raise ValueError(f"{variant}: " + "; ".join(problems))
    return out


def name_token_findings(spec: dict, base_name: str) -> list[str]:
    """Every child_name run must be exactly the variant's base_name."""
    problems = []
    for slide in spec.get("slides", []):
        for obj in slide.get("objects", []):
            for run in obj.get("runs", []) or []:
                if run.get("role") == "child_name" and run.get("text") != base_name:
                    problems.append(f"{obj.get('id')}: child_name run is {run.get('text')!r}, expected {base_name!r}")
    return problems


def coverage_findings(spec: dict, variants: tuple[str, ...] = VARIANTS) -> list[str]:
    """Objects with payloads must cover every variant the template set ships."""
    missing = []
    for slide in spec.get("slides", []):
        for obj in slide.get("objects", []):
            if "payloads" in obj:
                gaps = [variant for variant in variants if variant not in obj["payloads"]]
                if gaps:
                    missing.append(f"{obj.get('id')}: missing {', '.join(gaps)}")
    return missing
