"""16:9 landscape storybook pages: the scene fills the page, the words sit on it.

Two layouts (reference: designs/lulu_world, designs/pyramid_landscape):

* ``overlay``  — full-page scene; a dark gradient on the text side (default right, as the operator asked) and the
  story text over it;
* ``storybook`` — full-page scene; centred story text tilted a little in the empty part of the art, and the child's
  name as big «name art» (gradient fill, glow, white outline) inside the scene.

Rules:
* the scene is ALWAYS a real picture placeholder — ``<p:ph type="pic" idx="100">`` named «Picture Placeholder 100»,
  descr «scene» — on the layout and the slide, empty in the template; never a baked-in picture;
* where the text and the name go, their tilt and the name style live in the story JSON per page (``text_box`` /
  ``name_box`` as fractions of the trimmed page, ``rotate`` / ``name_rotate`` in degrees, ``name_style`` gold | ice |
  pink, ``text_side``, ``ink``) with sensible defaults;
* effects are OOXML the operator's PowerPoint renders (mxstudio.factory.textfx) — gradFill on runs, glow, a white
  outline for the name, an alpha gradient for the overlay, rotation, rtl="1" on Arabic paragraphs;
* everything a reader must see stays inside the safe zone (validated, never silently moved).
"""
from __future__ import annotations

from slidepoise.print_geometry import PageSpec

SCENE_IDX = 100
TYPE_SIZES_PT = {"A4": {"title": 44.0, "body": 20.0, "dedication": 30.0, "name": 72.0},
                 "A5": {"title": 31.0, "body": 14.0, "dedication": 21.0, "name": 51.0}}
WHITE, INK, SHADE = "#FFFFFF", "#2B2D42", "#0B1020"
NAME_COLOURS = {"gold": "#FFD54A", "ice": "#BFF4FF", "pink": "#FF8AD8"}
DEFAULTS = {
    "overlay": {"text_right": [0.56, 0.10, 0.39, 0.78], "text_left": [0.05, 0.10, 0.39, 0.78],
                "cover_title": [0.10, 0.68, 0.80, 0.22], "dedication": [0.15, 0.25, 0.70, 0.50]},
    "storybook": {"text": [0.55, 0.06, 0.40, 0.32], "name": [0.04, 0.05, 0.38, 0.24],
                  "cover_name": [0.08, 0.04, 0.84, 0.30], "cover_title": [0.18, 0.34, 0.64, 0.14],
                  "dedication": [0.15, 0.08, 0.70, 0.34]},
}


def _box(spec: PageSpec, frac) -> list[float]:
    """Fractions of the TRIMMED page → mm on the canvas (trim + bleed)."""
    tx, ty, tw, th = spec.trim_box_mm()
    x, y, w, h = frac
    return [round(tx + x * tw, 3), round(ty + y * th, 3), round(w * tw, 3), round(h * th, 3)]


def _px(spec: PageSpec, box_mm):
    return [round(v, 2) for v in spec.box_px(tuple(box_mm))]


def _inside_safe(spec: PageSpec, box: list[float], rotate: float) -> list[float]:
    """A DEFAULT box pulled inside the safe zone as it will print (rotation included): shrunk, then shifted.
    Boxes the story JSON sets are left exactly as written (the validator names them if they leave the zone)."""
    import math  # noqa: PLC0415
    sx, sy, sw, sh = spec.safe_box_mm()
    # the A5 variant is the A4 master scaled by 1/sqrt(2) from the trim corner while the safe margin stays the same
    # millimetres: keep sqrt(2) times the margin on the master so the box is still inside after scaling
    extra = spec.safe_mm * (math.sqrt(2) - 1) + 0.5
    sx, sy, sw, sh = sx + extra, sy + extra, sw - 2 * extra, sh - 2 * extra
    x, y, w, h = box
    a = math.radians(rotate or 0)
    for _ in range(40):
        rw = abs(w * math.cos(a)) + abs(h * math.sin(a))
        rh = abs(w * math.sin(a)) + abs(h * math.cos(a))
        if rw <= sw and rh <= sh:
            break
        w, h = w * 0.95, h * 0.95
    rw = abs(w * math.cos(a)) + abs(h * math.sin(a))
    rh = abs(w * math.sin(a)) + abs(h * math.cos(a))
    cx = min(max(x + w / 2, sx + rw / 2 + 0.1), sx + sw - rw / 2 - 0.1)
    cy = min(max(y + h / 2, sy + rh / 2 + 0.1), sy + sh - rh / 2 - 0.1)
    return [round(cx - w / 2, 3), round(cy - h / 2, 3), round(w, 3), round(h, 3)]


def layout_landscape_page(page, kind: str, spec: PageSpec, page_id: str, texts: dict, theme: dict,
                          layout: str) -> list[dict]:
    """Renderer objects for one landscape page (overlay | storybook). `page` is the story Page (its per-page boxes)."""
    cw, ch = spec.canvas_mm
    size = spec.name or "A4"
    fonts = theme["fonts"]
    name_font = fonts.get("name") or fonts["title"]
    colour = INK if page.ink else WHITE
    objects: list[dict] = []

    def scene():
        objects.append({"id": f"{page_id}_scene", "kind": "picture_placeholder", "order": 1, "label": "scene",
                        "ph_idx": SCENE_IDX, "bbox_px": _px(spec, (0, 0, cw, ch)), "box_mm": [0, 0, cw, ch], "z": 0})

    def text(oid, frac, payload, role, rotate=0.0, font=None, fx=None, z=3, default=False):
        box = _box(spec, frac)
        if default:
            box = _inside_safe(spec, box, rotate or 0)
        style = {"font_family": font or (fonts["title"] if role in ("title", "dedication") else fonts["body"]),
                 "font_size_pt": TYPE_SIZES_PT[size][role], "color": colour, "line_spacing_multiple": 1.08,
                 "vertical_alignment": "middle", "alignment": "center"}
        obj = {"id": oid, "kind": "textbox", "bbox_px": _px(spec, box), "box_mm": box, "z": z, "style": style,
               "text_role": "title" if role == "name" else role,
               "fx": {"rotate": float(rotate or 0), "shadow": not page.ink, "rtl": True, **(fx or {})}}
        obj.update(payload)
        objects.append(obj)

    def shade(side: str, alpha: int = 78):
        """Dark alpha gradient under the text (overlay): clear on the art side, full strength 40 % in, flat under the
        words. side: right | left | bottom | full (an even veil, e.g. the dedication)."""
        if side in ("right", "left"):
            width = cw * 0.55
            box = [round(cw - width if side == "right" else 0.0, 3), 0.0, round(width, 3), ch]
        elif side == "bottom":
            box = [0.0, round(ch * 0.45, 3), cw, round(ch * 0.55, 3)]
        else:
            box = [0.0, 0.0, cw, ch]
        objects.append({"id": f"{page_id}_shade", "kind": "shape", "shape": "rectangle", "z": 1, "box_mm": box,
                        "bbox_px": _px(spec, box), "style": {"fill": SHADE, "stroke": "none"},
                        "fx": {"gradient": {"color": SHADE, "toward": side, "from_alpha": 0, "to_alpha": alpha}}})

    def name_art(oid, frac, rotate, style_name, payload, cover=False):
        style_name = style_name or "gold"
        given = frac is not None
        frac = frac if given else (defaults["cover_name"] if cover else defaults["name"])
        text(oid, frac, payload, "name", rotate, font=name_font,
             fx={"name_style": style_name, "shadow": False}, z=4, default=not given)
        objects[-1]["style"]["color"] = NAME_COLOURS[style_name]
        if cover:
            objects[-1]["style"]["font_size_pt"] = TYPE_SIZES_PT[size]["name"] * 1.4

    defaults = DEFAULTS[layout]
    if kind in ("scene", "cover", "dedication", "back", "coloring"):
        scene()
    if kind == "back" or kind == "coloring":
        return objects
    if layout == "overlay":
        if kind == "cover":
            shade("bottom")
            text(f"{page_id}_title", page.text_box or defaults["cover_title"], texts["body"], "title", page.rotate, default=page.text_box is None)
        elif kind == "dedication":
            shade("full", 60)
            text(f"{page_id}_dedication", page.text_box or defaults["dedication"], texts["body"], "dedication",
                 page.rotate)
        else:
            side = page.text_side or "right"
            shade(side)
            text(f"{page_id}_body", page.text_box or defaults[f"text_{side}"], texts["body"], "body", page.rotate, default=page.text_box is None)
        return objects
    # storybook
    if kind == "cover":
        name_art(f"{page_id}_name_art", page.name_box, page.name_rotate or -2,
                 page.name_style, texts["name"], cover=True)
        text(f"{page_id}_title", page.text_box or defaults["cover_title"], texts["body"], "title", page.rotate or 0, default=page.text_box is None)
    elif kind == "dedication":
        text(f"{page_id}_dedication", page.text_box or defaults["dedication"], texts["body"], "dedication",
             page.rotate or 0)
    else:
        rotate = page.rotate if page.rotate is not None else -2.0
        text(f"{page_id}_body", page.text_box or defaults["text"], texts["body"], "body", rotate, default=page.text_box is None)
        if page.name_art is not False:
            name_art(f"{page_id}_name_art", page.name_box,
                     page.name_rotate if page.name_rotate is not None else 3.0, page.name_style, texts["name"])
    return objects


def landscape_kinds() -> tuple[str, ...]:
    return ("cover", "scene", "dedication", "back", "coloring")
