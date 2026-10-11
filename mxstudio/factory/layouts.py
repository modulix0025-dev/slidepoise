"""Page layouts in millimetres on the print canvas (trim + bleed), turned into renderer objects.

A layout is authored once at a master size; the Variant Forge scales it by the
exact ISO-216 factor for the other size and re-fits every text box. Everything a
reader must see (text, faces, QR) stays inside the safe box; scene art is full
bleed. Text sits on a native treatment (rounded panel) so art never needs letters.
"""
from __future__ import annotations

from slidepoise.print_geometry import PageSpec

TYPE_SIZES_PT = {  # starting defaults from the operator's templates (brief §6.3), A4 master
    "A4": {"title": 40.0, "body": 20.0, "dedication": 30.0, "caption": 14.0},
    "A5": {"title": 28.0, "body": 15.0, "dedication": 22.0, "caption": 11.0},
}
MIN_SIZES_PT = {"A4": {"body": 15.0, "title": 26.0, "dedication": 20.0, "caption": 10.0},
                "A5": {"body": 11.0, "title": 18.0, "dedication": 14.0, "caption": 8.0}}


def _px(spec: PageSpec, box_mm):
    return [round(value, 2) for value in spec.box_px(box_mm)]


def layout_page(kind: str, spec: PageSpec, page_id: str, texts: dict, theme: dict) -> list[dict]:
    """Return renderer objects for one page. `texts` = {"body": runs-or-payloads, "title": …}."""
    cw, ch = spec.canvas_mm
    sx, sy, sw, sh = spec.safe_box_mm()
    size = spec.name or "A4"
    fonts, colours = theme["fonts"], theme["colours"]
    base_style = {"font_family": fonts["body"], "color": colours["text"], "line_spacing_multiple": 1.2,
                  "vertical_alignment": "middle", "alignment": "right"}
    objects: list[dict] = []

    def panel(oid, box, z=1):
        objects.append({"id": oid, "kind": "shape", "shape": "rounded_rectangle", "bbox_px": _px(spec, box), "z": z,
                        "box_mm": [round(v, 3) for v in box],
                        "round_rect_adjustment": 18000,
                        "style": {"fill": colours["panel"], "stroke": colours["outline"], "stroke_width_px": 3}})

    def text(oid, box, payload, role, z=2, align=None):
        style = dict(base_style, font_size_pt=TYPE_SIZES_PT[size][role])
        if role == "title":
            style["font_family"] = fonts["title"]
        if align:
            style["alignment"] = align
        obj = {"id": oid, "kind": "textbox", "bbox_px": _px(spec, box), "z": z, "style": style,
               "text_role": role, "box_mm": [round(v, 3) for v in box]}
        obj.update(payload)
        objects.append(obj)

    if kind in {"scene", "cover"}:
        art_h = ch * (0.66 if kind == "scene" else 0.72)
        objects.append({"id": f"{page_id}_scene", "kind": "picture_placeholder", "order": 1, "label": "scene",
                        "bbox_px": _px(spec, (0, 0, cw, art_h)), "box_mm": [0, 0, cw, round(art_h, 3)], "z": 0})
        pad = 6.0
        box = (sx + pad, art_h + 2, sw - 2 * pad, sy + sh - art_h - 2 - pad)
        panel(f"{page_id}_panel", (sx, art_h - 2, sw, sy + sh - art_h + 2))
        role = "title" if kind == "cover" else "body"
        text(f"{page_id}_{role}", box, texts["body"], role, align="center" if kind == "cover" else None)
    elif kind == "dedication":
        panel(f"{page_id}_panel", (sx + 6, ch * 0.33, sw - 12, ch * 0.34))
        text(f"{page_id}_dedication", (sx + 10, ch * 0.36, sw - 20, ch * 0.28), texts["body"], "dedication",
             align="center")
    elif kind == "back":
        objects.append({"id": f"{page_id}_photo_a", "kind": "picture_placeholder", "order": 1, "label": "back_a",
                        "bbox_px": _px(spec, (0, 0, cw, ch / 2)), "box_mm": [0, 0, cw, ch / 2], "z": 0})
        objects.append({"id": f"{page_id}_photo_b", "kind": "picture_placeholder", "order": 2, "label": "back_b",
                        "bbox_px": _px(spec, (0, ch / 2, cw, ch / 2)), "box_mm": [0, ch / 2, cw, ch / 2], "z": 0})
    else:
        raise ValueError(f"no layout for page kind {kind!r} (page kinds are added in Phase 7)")
    return objects


DEFAULT_THEME = {
    "name": "مرح كلاسيكي",
    "fonts": {"title": "Tajawal", "body": "Tajawal"},
    "colours": {"text": "#1B2A41", "panel": "#FFFDF6", "outline": "#1B2A41", "background": "#FFFFFF"},
}
