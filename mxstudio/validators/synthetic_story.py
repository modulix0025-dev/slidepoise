"""Synthetic story pages shaped like the operator's real templates (brief Appendix A).

Used by the Phase-1 gate and as a fixture for later validators: an A5 or A4
portrait page with bleed, a full-width picture placeholder, a right-to-left
Arabic body whose hero name is one whole run, a dedication page, and a back page
with two picture placeholders and no text (like slides 15–16 of the A5 rabbit
deck).
"""
from __future__ import annotations

import json
from pathlib import Path

from mxstudio.proc import run_hidden
from mxstudio.runtime_paths import node_executable, renderer_env, renderer_script

from slidepoise.print_geometry import PageSpec

REPO = Path(__file__).resolve().parents[2]
RENDERER = renderer_script()

BASE_NAMES = {"ar_boy": "إياد", "ar_girl": "جيداء", "en_boy": "Eyad", "en_girl": "Gaidaa"}
_STORY = {
    "ar_boy": ("كان يا ما كان، كان هناك ولد اسمه ", " يحب البحر كثيرًا ويحلم بسمكة ذهبية."),
    "ar_girl": ("كان يا ما كان، كانت هناك بنت اسمها ", " تحب البحر كثيرًا وتحلم بسمكة ذهبية."),
}
_PAGE2 = {
    "ar_boy": ("في الصباح ذهب ", " إلى الشاطئ ومعه شبكة صغيرة."),
    "ar_girl": ("في الصباح ذهبت ", " إلى الشاطئ ومعها شبكة صغيرة."),
}
DEDICATION_PREFIX = "بكل الحب تهدى لـ"  # tatweel joiner: STEP 1 alone turns it into «لـ<child>»


def _px(spec: PageSpec, box_mm):
    return [round(value, 2) for value in spec.box_px(box_mm)]


def build_spec(variant: str = "ar_boy", size: str = "A5", font: str = "Tajawal", bleed_mm: float = 3.0,
               safe_mm: float = 5.0) -> dict:
    if variant not in _STORY:
        raise ValueError(f"synthetic pages exist for {sorted(_STORY)}")
    page = PageSpec.preset(size, bleed_mm=bleed_mm, safe_mm=safe_mm, dpi=300)
    width_px, height_px = page.canvas_px
    sx, sy, sw, sh = page.safe_box_mm()
    cw, ch = page.canvas_mm
    name = BASE_NAMES[variant]
    body_pt = 16 if size.upper() == "A5" else 22
    style = {"font_family": font, "font_size_pt": body_pt, "direction": "rtl", "lang": "ar-EG", "color": "#1A1A1A",
             "line_spacing_multiple": 1.15, "vertical_alignment": "top"}

    def text_page(page_id, before, after, art_ratio=0.62):
        art_h = ch * art_ratio
        return {
            "id": page_id, "dimensions_px": [width_px, height_px], "background": "#FFFFFF",
            "objects": [
                {"id": f"{page_id}_scene", "kind": "picture_placeholder", "order": 1, "label": "scene",
                 "bbox_px": _px(page, (0, 0, cw, art_h)), "z": 0},
                {"id": f"{page_id}_body", "kind": "textbox", "z": 1,
                 "bbox_px": _px(page, (sx, art_h + 4, sw, sy + sh - art_h - 4)),
                 "runs": [{"text": before}, {"text": name, "role": "child_name"}, {"text": after}],
                 "style": style},
            ],
        }

    dedication = {
        "id": "p3", "dimensions_px": [width_px, height_px], "background": "#FFFFFF",
        "objects": [{"id": "p3_dedication", "kind": "textbox", "z": 1,
                     "bbox_px": _px(page, (sx, ch * 0.4, sw, ch * 0.2)),
                     "runs": [{"text": DEDICATION_PREFIX + name, "role": "dedication"}],
                     "style": {**style, "font_size_pt": body_pt + 8, "alignment": "center",
                               "vertical_alignment": "middle"}}],
    }
    back = {
        "id": "p4", "dimensions_px": [width_px, height_px], "background": "#FFFFFF",
        "objects": [
            {"id": "p4_photo_a", "kind": "picture_placeholder", "order": 1, "bbox_px": _px(page, (0, 0, cw, ch / 2)), "z": 0},
            {"id": "p4_photo_b", "kind": "picture_placeholder", "order": 2, "bbox_px": _px(page, (0, ch / 2, cw, ch / 2)), "z": 0},
        ],
    }
    return {
        "title": f"synthetic {variant} {size}", "language": "ar-EG",
        "page": {"canvas_mm": [cw, ch], "trim_mm": list(page.trim_mm), "bleed_mm": bleed_mm, "safe_mm": safe_mm},
        "slides": [text_page("p1", *_STORY[variant]), text_page("p2", *_PAGE2[variant]), dedication, back],
        "_expected": {
            "base_name": name,
            "picture_slots": {1: 1, 2: 1, 4: 2},
            # OM counts replaced PARAGRAPHS: p1 body, p2 body, p3 dedication.
            "step1_replacements": 3,
            "slides": 4,
        },
    }


def render(spec: dict, output: Path, python: str | None = None) -> Path:
    """Render a spec with the forked PptxGenJS renderer + post-processor."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    spec_path = output.with_suffix(".spec.json")
    payload = {key: value for key, value in spec.items() if not key.startswith("_")}
    spec_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    env = renderer_env()
    if python:
        env["PYTHON"] = python
    proc = run_hidden([node_executable(), str(RENDERER), "--input", str(spec_path), "--output", str(output)],
                      env=env, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(f"renderer failed: {(proc.stderr or proc.stdout).decode('utf-8', 'replace')}")
    return output
