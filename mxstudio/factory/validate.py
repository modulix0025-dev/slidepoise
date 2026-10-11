"""Validators every variant must pass before it can be approved — each failure is named in Arabic and English.

Objective facts only (counts, sizes, fits, text proofs, licences). Visual
acceptance stays with the operator, who sees the contact sheet and the PDFs.
"""
from __future__ import annotations

import copy
import importlib
import sys
from pathlib import Path

from mxstudio.factory.forge import MM_TO_PT
from mxstudio.validators.operator_ports import deck_picture_slots, name_run_integrity, replay_generate_story
from mxstudio.validators.pdf_text import text_proof
from slidepoise.arabic.fit import fit_text
from slidepoise.arabic.fonts import FontRegistry, default_registry

VENDOR = Path(__file__).resolve().parents[2] / "vendor" / "modulex"
from mxstudio.factory.names import HAMZA_NAMES, LONGEST_NAMES  # noqa: E402,F401 - re-exported

MESSAGES = {
    "replacements": ("عدد استبدالات الاسم مش مظبوط — القالب هيطلع باسم غلط.",
                     "name replacement count differs from the expected count"),
    "name_runs": ("اسم الطفل متقسّم على أكتر من جزء نص.", "the sample name is split across runs"),
    "slots": ("أماكن الصور مش زي العقد.", "picture placeholder map differs from the contract"),
    "fit": ("فيه نص مش هيكفي مكانه.", "a text box does not fit"),
    "long_name": ("أطول اسم متوقع مش هيكفي مكانه.", "the longest expected name does not fit"),
    "export": ("تصدير الـPDF فشل أو طلع من غير نص.", "PDF export failed or carries no text"),
    "pages": ("عدد صفحات الـPDF غير عدد الشرائح.", "PDF page count differs from the slides"),
    "text_proof": ("الكلام اللي في الـPDF مش هو اللي في القالب.", "the PDF words differ from the deck"),
    "fonts": ("فيه خط مش متسطّب على الجهاز.", "a font used by the deck is not installed"),
    "text_outside_safe": ("فيه نص طالع برّه المنطقة الآمنة (بعد الميل) — ممكن يتقص في الطباعة.",
                          "a text box (as rotated) leaves the safe zone"),
    "scene_placeholder": ("صفحة المشهد مافيهاش Picture Placeholder 100 حقيقي (أو فيها صورة متثبّتة).",
                          "a scene page lacks the idx=100 picture placeholder (or has a baked picture)"),
    "low_contrast": ("الكلام مش باين كفاية على الصورة اللي تحته — شوف الاقتراح (تغميق التدرّج أو تحريك الكلام).",
                     "the words do not stand out from the art under them"),
    "font_substituted": ("الـPDF اتطبع بخط بديل مكان خط القالب — الخط مش متسجّل في ويندوز أو PowerPoint مفتوح من قبل "
                         "تسطيبه.", "the PDF uses a substitute font instead of a deck typeface"),
}


def _pptx_to_pdf():
    if str(VENDOR) not in sys.path:
        sys.path.insert(0, str(VENDOR))
    return importlib.import_module("pptx_to_pdf")


def _finding(code: str, detail) -> dict:
    ar, en = MESSAGES[code]
    return {"code": code, "ar": ar, "en": en, "detail": detail}


def expected_slots(spec: dict) -> dict[int, int]:
    out = {}
    for number, slide in enumerate(spec["slides"], 1):
        count = sum(1 for obj in slide["objects"] if obj.get("kind") == "picture_placeholder")
        if count:
            out[number] = count
    return out


def expected_replacements(spec: dict) -> int:
    return sum(1 for slide in spec["slides"] for obj in slide["objects"]
               if any(run.get("role") == "child_name" for run in obj.get("runs", []) or []))


def deck_typefaces(spec: dict) -> set[str]:
    return {obj["style"]["font_family"] for slide in spec["slides"] for obj in slide["objects"]
            if obj.get("kind") == "textbox"}


def long_name_findings(spec: dict, language: str, registry: FontRegistry) -> list[dict]:
    longest = LONGEST_NAMES[language]
    problems = []
    for slide in spec["slides"]:
        for obj in slide["objects"]:
            runs = obj.get("runs") or []
            if not any(run.get("role") == "child_name" for run in runs):
                continue
            text = "".join(longest if run.get("role") == "child_name" else run["text"] for run in runs)
            size = obj["style"]["font_size_pt"]
            _, _, w_mm, h_mm = obj["box_mm"]
            result = fit_text(text, w_mm * MM_TO_PT, h_mm * MM_TO_PT, obj["style"]["font_family"], registry=registry,
                              max_size_pt=size, min_size_pt=size, spacing=obj["style"].get("line_spacing_multiple", 1.0),
                              inset_pt=0.0)
            if not result.fits:
                problems.append({"object": obj["id"], "size_pt": size, "overflow_height_pt": result.overflow_height_pt})
    return problems


def validate_variant(entry: dict, out_dir: Path, registry: FontRegistry | None = None, export: bool = True,
                     engines: list[str] | None = None) -> dict:
    registry = registry or default_registry()
    deck = Path(entry["path"])
    spec = entry["spec"]
    language = entry["variant"].split("_")[0]
    findings, facts = [], {}

    replay = replay_generate_story(deck, entry["base_name"], "محمد" if language == "ar" else "Omar")
    facts["replacements"] = {"expected": expected_replacements(spec), "step1": replay["step1"]}
    if replay["step1"] != facts["replacements"]["expected"]:
        findings.append(_finding("replacements", facts["replacements"]))
    integrity = name_run_integrity(deck, entry["base_name"])
    if not all(item["ok"] for item in integrity):
        findings.append(_finding("name_runs", [i for i in integrity if not i["ok"]]))

    facts["slots"] = {"expected": expected_slots(spec), "measured": deck_picture_slots(deck)}
    if facts["slots"]["expected"] != facts["slots"]["measured"]:
        findings.append(_finding("slots", facts["slots"]))

    not_fitting = [f for f in entry.get("fit", []) if not f["fits"]]
    if not_fitting:
        findings.append(_finding("fit", not_fitting))
    long_name = long_name_findings(spec, language, registry)
    facts["longest_name"] = LONGEST_NAMES[language]
    if long_name:
        findings.append(_finding("long_name", long_name))

    if spec.get("page", {}).get("format") == "landscape_169":
        from mxstudio.validators import landscape as checks  # noqa: PLC0415
        outside = checks.safe_zone_findings(spec)
        if outside:
            findings.append(_finding("text_outside_safe", outside))
        placeholders = checks.scene_placeholder_findings(deck, spec)
        if placeholders:
            findings.append(_finding("scene_placeholder", placeholders))
        low, facts["contrast"] = checks.contrast_findings(spec, entry.get("resolve_art"))
        if low:
            findings.append(_finding("low_contrast", low))

    missing_fonts = sorted(face for face in deck_typefaces(spec) if not registry.has(face))
    facts["typefaces"] = sorted(deck_typefaces(spec))
    if missing_fonts:
        findings.append(_finding("fonts", missing_fonts))

    if export:
        converter = _pptx_to_pdf()
        pdf = Path(out_dir) / (deck.stem + ".pdf")
        try:
            record = converter.convert(deck, pdf, expect_pages=len(spec["slides"]), engines=engines)
        except converter.ConversionError as exc:
            findings.append(_finding("export", {"error": str(exc), "attempts": exc.attempts}))
        else:
            facts["export"] = {k: record[k] for k in ("engine", "pages", "fonts", "has_text", "sha256")}
            if record["pages"] != len(spec["slides"]):
                findings.append(_finding("pages", {"pdf": record["pages"], "slides": len(spec["slides"])}))
            texts = ["".join(run["text"] for run in obj.get("runs", [])) for slide in spec["slides"]
                     for obj in slide["objects"] if obj.get("kind") == "textbox"]
            from mxstudio.validators.pdf_text import boxes_from_spec  # noqa: PLC0415
            proof = text_proof(texts, pdf, names=[entry["base_name"], LONGEST_NAMES[language], *HAMZA_NAMES],
                               boxes=boxes_from_spec(spec))
            facts["text_proof"] = proof
            if not proof["ok"]:
                findings.append(_finding("text_proof", proof))
            facts["pdf"] = str(pdf)
            from mxstudio.validators.pdf_fonts import check_pdf  # noqa: PLC0415
            fonts = check_pdf(pdf, deck_typefaces(spec))
            facts["pdf_fonts"] = fonts
            if not fonts["ok"]:
                findings.append(_finding("font_substituted", {k: fonts[k] for k in ("missing", "unexpected")}))
            if record["engine"] != "powerpoint":
                facts["powerpoint_proof"] = "pending on device (On-Device Proof Runner)"
    return {"variant": entry["variant"], "size": entry["size"], "file": entry["file"], "ok": not findings,
            "findings": findings, "facts": facts}


def validate_set(built: dict, out_dir: Path, registry: FontRegistry | None = None, export: bool = True,
                 engines: list[str] | None = None) -> dict:
    results = {key: validate_variant(entry, out_dir, registry, export, engines)
               for key, entry in built["variants"].items()}
    return {"story_key": built["story_key"], "ok": all(r["ok"] for r in results.values()), "variants": results}


def strip_specs(built: dict) -> dict:
    """A JSON-safe summary of a forge result (specs are large and stay in the workspace)."""
    out = copy.deepcopy(built)
    for entry in out["variants"].values():
        entry.pop("spec", None)
    return out
