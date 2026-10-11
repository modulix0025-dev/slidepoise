"""Variant Forge: one master layout → every variant the operator's pipeline consumes.

* A4 ↔ A5 is an exact ISO-216 scale (1/√2) of geometry AND type sizes, measured
  from the trim box; anything that touched the canvas edge (full-bleed art) is
  extended to the new canvas edge so it stays full bleed.
* ولد/بنت and عربي/English swap the authored payloads (never find/replace).
* Every text box is re-fitted with the HarfBuzz fitter after scaling and after
  the payload swap; a box that cannot fit at the size's minimum is a named finding.
* Filenames follow one scheme and are registered exactly:
  ``<story_key>_<ar|en>_<boy|girl>_<A4|A5>.pptx``.
"""
from __future__ import annotations

import copy
import math
from pathlib import Path

from mxstudio.factory.layouts import DEFAULT_THEME, MIN_SIZES_PT, layout_page
from mxstudio.factory.payloads import VARIANTS, resolve_spec
from mxstudio.factory.story import Story, runs_for
from slidepoise.arabic.fit import fit_text
from slidepoise.arabic.fonts import FontRegistry, default_registry
from slidepoise.print_geometry import PageSpec, iso216_scale

MM_TO_PT = 72 / 25.4
EDGE_MM = 0.05


def variant_filename(story_key: str, variant: str, size: str) -> str:
    language, gender = variant.split("_")
    return f"{story_key}_{language}_{gender}_{size.upper()}.pptx"


def page_payloads(story: Story, page) -> dict:
    """Payload dicts per text role. Bilingual pages carry both languages in every variant, both using the
    variant's own base name (OM replaces one name per order)."""
    def payloads(texts: dict, forced: str | None = None) -> dict:
        out = {}
        for variant in story.variants:
            source = f"{forced}_{variant.split('_')[1]}" if forced else variant
            if texts.get(source):
                payload = {"runs": runs_for(texts[source], story.base_names[variant])}
                if forced:
                    payload["style"] = {"direction": "rtl" if forced == "ar" else "ltr",
                                        "lang": "ar-EG" if forced == "ar" else "en-US",
                                        "alignment": "right" if forced == "ar" else "left"}
                out[variant] = payload
        return {"payloads": out}

    roles = {"body": payloads(page.texts)}
    if page.title:
        roles["title"] = payloads({v: page.title.get(v.split("_")[0], "") for v in story.variants})
    if page.kind == "bilingual":
        roles["body_ar"], roles["body_en"] = payloads(page.texts, "ar"), payloads(page.texts, "en")
    return roles


def build_master(story: Story, size: str = "A4", theme: dict | None = None, bleed_mm: float = 3.0,
                 safe_mm: float = 5.0) -> dict:
    """The semantic page map with payloads for every variant (geometry at the master size)."""
    theme = theme or DEFAULT_THEME
    spec_page = PageSpec.preset(size, bleed_mm=bleed_mm, safe_mm=safe_mm)
    slides = []
    for number, page in enumerate(story.pages, 1):
        page_id = f"p{number}"
        objects = layout_page(page.kind, spec_page, page_id, page_payloads(story, page), theme)
        slides.append({"id": page_id, "kind": page.kind, "dimensions_px": list(spec_page.canvas_px),
                       "background": theme["colours"]["background"], "objects": objects})
    return {"title": story.title.get("ar", story.key), "language": "ar-EG", "size": size,
            "page": {"canvas_mm": list(spec_page.canvas_mm), "trim_mm": list(spec_page.trim_mm), "bleed_mm": bleed_mm,
                     "safe_mm": safe_mm},
            "slides": slides, "story_key": story.key, "theme": theme.get("name")}


def scale_spec(master: dict, to_size: str) -> dict:
    """Exact ISO-216 scaling of a master spec to another A size (same bleed and safe zone)."""
    from_size = master["size"]
    if from_size == to_size:
        return copy.deepcopy(master)
    factor = iso216_scale(from_size, to_size)
    bleed, safe = master["page"]["bleed_mm"], master["page"]["safe_mm"]
    src = PageSpec.preset(from_size, bleed_mm=bleed, safe_mm=safe)
    dst = PageSpec.preset(to_size, bleed_mm=bleed, safe_mm=safe)
    scw, sch = src.canvas_mm
    dcw, dch = dst.canvas_mm
    out = copy.deepcopy(master)
    out["size"] = to_size
    out["page"].update({"canvas_mm": list(dst.canvas_mm), "trim_mm": list(dst.trim_mm)})
    for slide in out["slides"]:
        slide["dimensions_px"] = list(dst.canvas_px)
        for obj in slide["objects"]:
            x, y, w, h = obj["box_mm"]
            left, top, right, bottom = x <= EDGE_MM, y <= EDGE_MM, x + w >= scw - EDGE_MM, y + h >= sch - EDGE_MM
            nx = bleed + (x - bleed) * factor
            ny = bleed + (y - bleed) * factor
            nr = bleed + (x + w - bleed) * factor
            nb = bleed + (y + h - bleed) * factor
            nx, ny = (0.0 if left else nx), (0.0 if top else ny)
            nr, nb = (dcw if right else nr), (dch if bottom else nb)
            obj["box_mm"] = [round(nx, 3), round(ny, 3), round(nr - nx, 3), round(nb - ny, 3)]
            obj["bbox_px"] = [round(v, 2) for v in dst.box_px(tuple(obj["box_mm"]))]
            style = obj.get("style")
            if style and "font_size_pt" in style:
                style["font_size_pt"] = math.floor(style["font_size_pt"] * factor * 2) / 2
            if style and "stroke_width_px" in style:
                style["stroke_width_px"] = max(1, round(style["stroke_width_px"] * factor, 2))
    return out


def fit_spec(spec: dict, registry: FontRegistry | None = None) -> tuple[dict, list[dict]]:
    """Re-fit every text box of a resolved (single-variant) spec. Returns (spec, fit facts)."""
    registry = registry or default_registry()
    size = spec.get("size", "A4")
    out = copy.deepcopy(spec)
    facts = []
    for slide in out["slides"]:
        for obj in slide["objects"]:
            if obj.get("kind") != "textbox":
                continue
            text = "".join(run["text"] for run in obj.get("runs", [])) or obj.get("text", "")
            style = obj["style"]
            _, _, w_mm, h_mm = obj["box_mm"]
            minimum = MIN_SIZES_PT[size].get(obj.get("text_role", "body"), 8.0)
            result = fit_text(text, w_mm * MM_TO_PT, h_mm * MM_TO_PT, style["font_family"], registry=registry,
                              max_size_pt=style["font_size_pt"], min_size_pt=minimum,
                              spacing=style.get("line_spacing_multiple", 1.0), inset_pt=0.0)
            style["font_size_pt"] = result.size_pt
            facts.append({"slide": slide["id"], "object": obj["id"], "fits": result.fits, "size_pt": result.size_pt,
                          "lines": len(result.lines), "overflow_height_pt": result.overflow_height_pt,
                          "unbreakable_words": result.unbreakable_words, "font": result.font_family})
    return out, facts


def renderer_spec(spec: dict) -> dict:
    """Drop authoring-only keys the renderer does not know."""
    out = copy.deepcopy(spec)
    for slide in out["slides"]:
        slide.pop("kind", None)
        for obj in slide["objects"]:
            for key in ("box_mm", "text_role"):
                obj.pop(key, None)
            if obj.get("kind") == "textbox":
                obj["style"].setdefault("margins_px", [0, 0, 0, 0])
    return out


def forge(story: Story, out_dir: Path, sizes=("A4", "A5"), master_size: str = "A4", theme: dict | None = None,
          registry: FontRegistry | None = None, render=None) -> dict:
    """Build every variant deck. `render(spec, path)` defaults to the forked PptxGenJS renderer."""
    if render is None:
        from mxstudio.validators.synthetic_story import render as default_render  # noqa: PLC0415
        render = default_render  # Node + a Python for the post-processor come from mxstudio.runtime_paths
    problems = story.validate()
    if problems:
        raise ValueError("story is not ready: " + "; ".join(problems))
    master = build_master(story, master_size, theme)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    built = {}
    for size in sizes:
        sized = scale_spec(master, size)
        for variant in story.variants:
            resolved = resolve_spec(sized, variant, story.base_names)
            resolved["size"] = size
            fitted, facts = fit_spec(resolved, registry)
            path = out_dir / variant_filename(story.key, variant, size)
            render(renderer_spec(fitted), path)
            built[f"{variant}_{size}"] = {"file": path.name, "path": str(path), "size": size, "variant": variant,
                                          "base_name": story.base_names[variant], "fit": facts,
                                          "spec": fitted}
    return {"story_key": story.key, "master_size": master_size, "variants": built}


__all__ = ["VARIANTS", "build_master", "fit_spec", "forge", "renderer_spec", "scale_spec", "variant_filename"]
