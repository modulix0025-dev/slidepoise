"""Checks for full-page-scene layouts (overlay / storybook). Facts and named findings only — the look is the operator's.

* ``text_outside_safe``: a text box, rotated as it will print, leaves the safe zone;
* ``scene_placeholder``: a page that shows a scene has no ``<p:ph type="pic" idx="100">`` (or it is not a picture
  placeholder) — the operator's tools fill the scene by that index;
* ``low_contrast``: measured on the REAL art under the text (the page's sample art, cover-fitted like PowerPoint
  fills a placeholder, with the overlay gradient composited): the 10th-percentile contrast between the text colour and
  the pixels behind it is below 3:1. The finding suggests how dark the gradient must be, or where the same box reads
  better.
"""
from __future__ import annotations

import math
import re
import zipfile
from pathlib import Path

MIN_CONTRAST = 3.0
SCENE_IDX = "100"


def _rotated_bbox(box, degrees: float):
    x, y, w, h = box
    if not degrees:
        return x, y, w, h
    a = math.radians(degrees)
    cx, cy = x + w / 2, y + h / 2
    rw = abs(w * math.cos(a)) + abs(h * math.sin(a))
    rh = abs(w * math.sin(a)) + abs(h * math.cos(a))
    return cx - rw / 2, cy - rh / 2, rw, rh


def safe_zone_findings(spec: dict) -> list[dict]:
    page = spec["page"]
    bleed, safe = page["bleed_mm"], page["safe_mm"]
    tw, th = page["trim_mm"]
    sx, sy, sw, sh = bleed + safe, bleed + safe, tw - 2 * safe, th - 2 * safe
    out = []
    for slide in spec["slides"]:
        for obj in slide["objects"]:
            if obj.get("kind") != "textbox" or "box_mm" not in obj:
                continue
            x, y, w, h = _rotated_bbox(obj["box_mm"], (obj.get("fx") or {}).get("rotate", 0))
            tol = 0.05
            if x < sx - tol or y < sy - tol or x + w > sx + sw + tol or y + h > sy + sh + tol:
                out.append({"slide": slide["id"], "object": obj["id"], "box_mm": [round(v, 2) for v in (x, y, w, h)],
                            "safe_mm": [round(v, 2) for v in (sx, sy, sw, sh)]})
    return out


_PH = re.compile(rb'<p:sp>(?:(?!</p:sp>).)*?<p:cNvPr[^>]*name="([^"]*)"[^>]*?(?:descr="([^"]*)")?[^>]*/?>(?:(?!</p:sp>).)*?'
                 rb'<p:ph([^>]*)/>', re.S)


def scene_placeholder_findings(deck: Path, spec: dict) -> list[dict]:
    want = [n for n, slide in enumerate(spec["slides"], 1)
            if any(o.get("kind") == "picture_placeholder" and o.get("ph_idx") for o in slide["objects"])]
    out = []
    with zipfile.ZipFile(deck) as z:
        for number in want:
            xml = z.read(f"ppt/slides/slide{number}.xml")
            found = [(name, attrs) for name, _descr, attrs in _PH.findall(xml)
                     if b'type="pic"' in attrs and f'idx="{SCENE_IDX}"'.encode() in attrs]
            if not found or found[0][0] != f"Picture Placeholder {SCENE_IDX}".encode():
                out.append({"slide": number, "found": [n.decode() for n, _ in found]})
            elif b"<p:pic>" in xml:
                out.append({"slide": number, "baked_picture": True})
    return out


def _luminance(rgb):
    import numpy as np  # noqa: PLC0415
    c = rgb / 255.0
    c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * c[..., 0] + 0.7152 * c[..., 1] + 0.0722 * c[..., 2]


def _hex_lum(colour: str) -> float:
    import numpy as np  # noqa: PLC0415
    value = colour.lstrip("#")
    return float(_luminance(np.array([[int(value[i:i + 2], 16) for i in (0, 2, 4)]], dtype=float))[0])


def _cover(image, size):
    """Fill `size` keeping the aspect (PowerPoint's picture-placeholder fill): scale up, crop the centre."""
    from PIL import Image  # noqa: PLC0415
    w, h = image.size
    scale = max(size[0] / w, size[1] / h)
    resized = image.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
    left, top = (resized.width - size[0]) // 2, (resized.height - size[1]) // 2
    return resized.crop((left, top, left + size[0], top + size[1]))


def page_background(art_path: Path, slide: dict, canvas_mm, px_per_mm: float = 2.0):
    """The art as it sits behind the words: cover-fitted to the canvas with the overlay gradients composited."""
    import numpy as np  # noqa: PLC0415
    from PIL import Image  # noqa: PLC0415
    width, height = round(canvas_mm[0] * px_per_mm), round(canvas_mm[1] * px_per_mm)
    with Image.open(art_path) as image:
        rgb = np.asarray(_cover(image.convert("RGB"), (width, height)), dtype=float)
    for obj in slide["objects"]:
        gradient = (obj.get("fx") or {}).get("gradient")
        if not gradient:
            continue
        x, y, w, h = (round(v * px_per_mm) for v in obj["box_mm"])
        colour = gradient.get("color", "#0B1020").lstrip("#")
        shade = np.array([int(colour[i:i + 2], 16) for i in (0, 2, 4)], dtype=float)
        a0, a1 = gradient.get("from_alpha", 0) / 100, gradient.get("to_alpha", 78) / 100
        toward = gradient.get("toward", "right")
        if toward == "full":
            a0 = a1
        span = w if toward in ("right", "left") else h
        knee = max(1, round(span * 0.4))  # same stops as textfx: clear → full strength at 40 % → flat
        ramp = np.concatenate([np.linspace(a0, a1, knee), np.full(max(span - knee, 0), a1)])
        if toward in ("left", "top"):
            ramp = ramp[::-1]
        region = rgb[y:y + h, x:x + w]
        alpha = ramp[None, :, None] if toward in ("right", "left") else ramp[:, None, None]
        alpha = alpha[:region.shape[0], :region.shape[1]] if alpha.ndim == 3 else alpha
        rgb[y:y + h, x:x + w] = region * (1 - alpha[: region.shape[0], : region.shape[1]]) + shade * alpha[
            : region.shape[0], : region.shape[1]]
    return rgb


def contrast_in_box(background, box_mm, text_colour: str, px_per_mm: float = 2.0, percentile: float = 10.0) -> float:
    import numpy as np  # noqa: PLC0415
    x, y, w, h = (max(0, round(v * px_per_mm)) for v in box_mm)
    region = background[y:y + h, x:x + w]
    if region.size == 0:
        return float("inf")
    lum = _luminance(region).ravel()
    text = _hex_lum(text_colour)
    ratio = (np.maximum(lum, text) + 0.05) / (np.minimum(lum, text) + 0.05)
    return float(np.percentile(ratio, percentile))


def contrast_findings(spec: dict, resolve_art=None) -> tuple[list[dict], dict]:
    """(findings, facts). Pages without sample art are listed as unmeasured (facts), never guessed."""
    facts: dict = {"measured": {}, "unmeasured": []}
    findings = []
    canvas = spec["page"]["canvas_mm"]
    for slide in spec["slides"]:
        art = slide.get("art")
        texts = [o for o in slide["objects"] if o.get("kind") == "textbox"]
        if not texts:
            continue
        path = resolve_art(art) if (art and resolve_art) else (Path(art) if art else None)
        if not path or not Path(path).is_file():
            facts["unmeasured"].append(slide["id"])
            continue
        background = page_background(Path(path), slide, canvas)
        for obj in texts:
            colour = obj["style"].get("color", "#FFFFFF")
            ratio = contrast_in_box(background, obj["box_mm"], colour)
            facts["measured"][obj["id"]] = round(ratio, 2)
            if ratio >= MIN_CONTRAST:
                continue
            findings.append({"slide": slide["id"], "object": obj["id"], "contrast_p10": round(ratio, 2),
                             "needed": MIN_CONTRAST, "suggest": _suggest(path, slide, canvas, obj, colour)})
    return findings, facts


def _suggest(path, slide, canvas, obj, colour) -> dict:
    """How to fix it: a darker overlay (alpha %), or the best place for the same box on this art."""
    import copy  # noqa: PLC0415
    suggestion: dict = {}
    for alpha in (60, 70, 80, 90, 95):
        trial = copy.deepcopy(slide)
        shades = [o for o in trial["objects"] if (o.get("fx") or {}).get("gradient")]
        if not shades:
            break
        for shade in shades:
            shade["fx"]["gradient"]["to_alpha"] = alpha
            shade["fx"]["gradient"]["from_alpha"] = max(shade["fx"]["gradient"].get("from_alpha", 0), alpha // 2)
        if contrast_in_box(page_background(Path(path), trial, canvas), obj["box_mm"], colour) >= MIN_CONTRAST:
            suggestion["darken_overlay_to_alpha"] = alpha
            break
    background = page_background(Path(path), slide, canvas)
    _, _, w, h = obj["box_mm"]
    best = None
    for fx in (0.05, 0.2, 0.35, 0.5, 0.6):
        for fy in (0.05, 0.25, 0.45, 0.6):
            x, y = 3 + fx * (canvas[0] - 6), 3 + fy * (canvas[1] - 6)
            if x + w > canvas[0] - 8 or y + h > canvas[1] - 8:
                continue
            ratio = contrast_in_box(background, (x, y, w, h), colour)
            if best is None or ratio > best[0]:
                best = (ratio, fx, fy)
    if best and best[0] >= MIN_CONTRAST:
        suggestion["move_text_box_to"] = {"x": best[1], "y": best[2], "contrast_p10": round(best[0], 2)}
    if not suggestion:
        suggestion["ink_or_overlay"] = "use dark text (ink: true) or add an overlay"
    return suggestion
