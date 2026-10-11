"""Readability of text over real art: measure the pixels under each text box.

Rule: text sits on the accepted illustration, not on an average colour. For every text
box this module samples the actual pixels under it and reports

* contrast of the text colour against those pixels — WCAG 2.x ratio and APCA Lc, both at
  the median and at a low percentile (the worst patches, default 5th percentile);
* busy-ness facts — edge density, high-frequency luminance variation, gradient energy;

and, when the text would not be readable, it **proposes** a treatment (outline/shadow,
soft scrim, cloud bubble — the least intrusive one that the measurement says will work),
then simulates that treatment over the same pixels and re-measures it. The art itself is
never altered. Contrast below the WCAG floor is a named blocking finding on the untreated
layout (WCAG 2.x is the normative floor); an APCA shortfall alone, or texture alone, is
advisory — both still get a treatment proposal. Whether the treated page *looks* good stays with the
host Agent's visual review.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

import cv2
import numpy as np

from .contrast import apca_lc_from_y, apca_threshold, apca_y, wcag_ratio_from_luminance, wcag_threshold
from .oklch import ColourLike, parse_rgb, relative_luminance_array, srgb_array_to_oklab, to_hex

LOW_PERCENTILE = 5.0
BUSY = {"edge_density": 0.08, "textured_area": 0.35}
MODERATE = {"edge_density": 0.025, "textured_area": 0.12}
SCRIM_MAX_ALPHA = 0.85
TREATMENTS = ("none", "outline_shadow", "soft_scrim", "cloud_bubble")


def box_mm_to_px(box_mm: Sequence[float], canvas_mm: Sequence[float], image_size: Sequence[int]) -> tuple[int, int, int, int]:
    """(x, y, w, h) in mm on a canvas of (W, H) mm → pixel box on an image of (width, height)."""
    sx, sy = image_size[0] / canvas_mm[0], image_size[1] / canvas_mm[1]
    x, y, w, h = box_mm
    return int(round(x * sx)), int(round(y * sy)), max(1, int(round(w * sx))), max(1, int(round(h * sy)))


def region_under_box(image: Any, box_px: Sequence[float]) -> np.ndarray:
    """RGB uint8 crop (H, W, 3) under an (x, y, w, h) box; transparent pixels are composited on white paper."""
    from .extract import load_rgba

    rgba = load_rgba(image)
    x, y, w, h = (int(round(v)) for v in box_px)
    H, W = rgba.shape[:2]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
    if x1 <= x0 or y1 <= y0:
        raise ValueError("text box lies outside the image")
    crop = rgba[y0:y1, x0:x1].astype(np.float64)
    alpha = crop[..., 3:4] / 255.0
    rgb = crop[..., :3] * alpha + 255.0 * (1.0 - alpha)
    return (rgb + 0.5).astype(np.uint8)


def busyness(region: np.ndarray) -> dict:
    """Texture facts of an RGB crop. ``level`` is a bucket of these facts, not a quality verdict.

    * ``edge_density`` — share of Canny edge pixels on OKLab L;
    * ``textured_area`` — share of pixels whose local (glyph-scale window) L standard
      deviation exceeds 0.05: dense texture, not one isolated object edge;
    * ``gradient_mean`` / ``luminance_std`` / ``colour_spread_ok`` — reported for the host.
    """
    L = srgb_array_to_oklab(region)[..., 0].astype(np.float32)
    L8 = np.clip(L * 255.0, 0, 255).astype(np.uint8)
    edges = cv2.Canny(cv2.GaussianBlur(L8, (3, 3), 0), 40, 120)
    edge_density = float(np.count_nonzero(edges)) / edges.size
    win = max(3, int(round(min(region.shape[:2]) / 40.0)) | 1)
    mean = cv2.blur(L, (win, win))
    var = np.maximum(cv2.blur(L * L, (win, win)) - mean * mean, 0.0)
    textured_area = float(np.mean(np.sqrt(var) > 0.05))
    gx = cv2.Sobel(L, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(L, cv2.CV_32F, 0, 1, ksize=3)
    gradient = float(np.mean(np.hypot(gx, gy)))
    lab = srgb_array_to_oklab(region).reshape(-1, 3)
    colour_spread = float(np.mean(np.linalg.norm(lab - lab.mean(axis=0), axis=1)))
    if edge_density >= BUSY["edge_density"] or textured_area >= BUSY["textured_area"]:
        level = "busy"
    elif edge_density >= MODERATE["edge_density"] or textured_area >= MODERATE["textured_area"]:
        level = "moderate"
    else:
        level = "flat"
    return {"edge_density": round(edge_density, 4), "textured_area": round(textured_area, 4),
            "window_px": win, "gradient_mean": round(gradient, 4), "colour_spread_ok": round(colour_spread, 4),
            "luminance_std": round(float(np.std(L)), 4), "level": level}


def _contrast_stats(text_rgb: Sequence[int], pixels: np.ndarray, pct: float) -> dict:
    flat = pixels.reshape(-1, 3)
    t = np.array(text_rgb, dtype=np.uint8)
    ratio = wcag_ratio_from_luminance(relative_luminance_array(t), relative_luminance_array(flat))
    lc = apca_lc_from_y(apca_y(t), apca_y(flat))
    abs_lc = np.abs(lc)
    return {"wcag_p": float(np.percentile(ratio, pct)), "wcag_median": float(np.median(ratio)),
            "apca_abs_p": float(np.percentile(abs_lc, pct)), "apca_abs_median": float(np.median(abs_lc)),
            "polarity": "dark_on_light" if float(np.median(lc)) >= 0 else "light_on_dark",
            "mixed_polarity": bool(0.05 < float(np.mean(lc > 0)) < 0.95)}


def _composite(pixels: np.ndarray, fill_rgb: Sequence[int], alpha: float) -> np.ndarray:
    fill = np.array(fill_rgb, dtype=np.float64)
    return (pixels.astype(np.float64) * (1 - alpha) + fill * alpha + 0.5).astype(np.uint8)


def _passes(stats: dict, w_min: float, a_min: float) -> bool:
    return stats["wcag_p"] >= w_min and stats["apca_abs_p"] >= a_min


def assess(image: Any, box_px: Sequence[float], text_colour: ColourLike, font_size_pt: float,
           bold: bool = False, percentile: float = LOW_PERCENTILE) -> dict:
    """Measured facts for one text box on the untreated art."""
    region = region_under_box(image, box_px)
    text_rgb = parse_rgb(text_colour)
    stats = _contrast_stats(text_rgb, region, percentile)
    w_min, a_min = wcag_threshold(font_size_pt, bold), apca_threshold(font_size_pt, bold)
    return {"box_px": [int(round(v)) for v in box_px], "text_colour": to_hex(text_rgb),
            "font_size_pt": font_size_pt, "bold": bold, "percentile": percentile,
            "wcag_min": w_min, "apca_min_abs": a_min,
            **{k: (round(v, 3) if isinstance(v, float) else v) for k, v in stats.items()},
            "passes_wcag": stats["wcag_p"] >= w_min, "passes_apca": stats["apca_abs_p"] >= a_min,
            "passes": _passes(stats, w_min, a_min), "texture": busyness(region), "_region": region}


def _best_fill(text_rgb: Sequence[int], candidates: Sequence[ColourLike], prefer_ratio: float = 7.0) -> tuple[int, int, int]:
    """Fill colour for a scrim/bubble: the first candidate (deck roles first) whose contrast
    with the text reaches ``prefer_ratio``; otherwise the highest-contrast candidate."""
    t = np.array(text_rgb, dtype=np.uint8)
    best, best_ratio = None, -1.0
    for c in candidates:
        rgb = parse_rgb(c)
        r = float(wcag_ratio_from_luminance(relative_luminance_array(t),
                                            relative_luminance_array(np.array(rgb, dtype=np.uint8))))
        if r >= prefer_ratio:
            return rgb
        if r > best_ratio:
            best, best_ratio = rgb, r
    return best  # type: ignore[return-value]


def _min_alpha(region: np.ndarray, text_rgb, fill_rgb, w_min, a_min, pct) -> float | None:
    for alpha in np.round(np.arange(0.05, 1.0001, 0.05), 2):
        if _passes(_contrast_stats(text_rgb, _composite(region, fill_rgb, float(alpha)), pct), w_min, a_min):
            return float(alpha)
    return None


def propose_treatment(assessment: Mapping, roles: Mapping[str, str] | None = None) -> dict:
    """Least intrusive treatment that the measurement says will make the text readable.

    Order: none → outline/shadow (median contrast already fine, texture not busy; the
    outline lifts the few bad patches) → soft scrim (minimum alpha ≤ 0.85, texture not
    busy) → cloud bubble (opaque, for busy art or when a scrim would have to be nearly
    opaque). Each proposal carries its simulated result on the same pixels.
    """
    region = assessment["_region"]
    text_rgb = parse_rgb(assessment["text_colour"])
    w_min, a_min, pct = assessment["wcag_min"], assessment["apca_min_abs"], assessment["percentile"]
    level = assessment["texture"]["level"]
    fills = [c for c in ((roles or {}).get("background"), (roles or {}).get("outline")) if c] + ["#ffffff", "#000000"]
    fill = _best_fill(text_rgb, fills)
    size = float(assessment["font_size_pt"])

    if assessment["passes"] and level != "busy":
        return {"treatment": "none", "reason_en": "Text is readable on the art as measured.",
                "reason_ar": "الكلام مقروء على الرسمة زي ما هي."}

    median_ok = assessment["wcag_median"] >= w_min and assessment["apca_abs_median"] >= a_min
    if median_ok and level != "busy":
        width = round(max(0.6, 0.07 * size), 2)
        after = _contrast_stats(text_rgb, np.array([[fill]], dtype=np.uint8), pct)
        return {"treatment": "outline_shadow", "outline_colour": to_hex(fill), "outline_width_pt": width,
                "shadow": {"colour": to_hex(fill), "blur_pt": round(width * 1.5, 2), "opacity": 0.6},
                "predicted": {"text_vs_outline_wcag": round(after["wcag_p"], 2),
                              "text_vs_outline_apca_abs": round(after["apca_abs_p"], 1)},
                "verified": _passes(after, w_min, a_min),
                "reason_en": "Most of the area is readable; an outline in the fill colour rescues the dark/light patches.",
                "reason_ar": "معظم المساحة مقروءة؛ حدّ (outline) حوالين الحروف بلون الخلفية بيحل البقع الصعبة."}

    alpha = _min_alpha(region, text_rgb, fill, w_min, a_min, pct)
    if alpha is not None and alpha <= SCRIM_MAX_ALPHA and level != "busy":
        alpha = min(1.0, round(alpha + 0.05, 2))  # small safety margin
        after = _contrast_stats(text_rgb, _composite(region, fill, alpha), pct)
        return {"treatment": "soft_scrim", "fill": to_hex(fill), "alpha": alpha, "feather_pt": round(size * 0.6, 1),
                "padding_pt": round(size * 0.5, 1),
                "predicted": {"wcag_p": round(after["wcag_p"], 2), "apca_abs_p": round(after["apca_abs_p"], 1)},
                "verified": _passes(after, w_min, a_min),
                "reason_en": f"A soft scrim at {int(alpha * 100)}% lifts the worst patches over the floor.",
                "reason_ar": f"طبقة ناعمة شفافة {int(alpha * 100)}% تحت الكلام بتخلّي أصعب حتة مقروءة."}

    after = _contrast_stats(text_rgb, _composite(region, fill, 1.0), pct)
    return {"treatment": "cloud_bubble", "fill": to_hex(fill), "alpha": 1.0, "padding_pt": round(size * 0.8, 1),
            "outline_colour": (roles or {}).get("outline"),
            "predicted": {"wcag_p": round(after["wcag_p"], 2), "apca_abs_p": round(after["apca_abs_p"], 1)},
            "verified": _passes(after, w_min, a_min),
            "reason_en": "The art under the text is too busy or too close in tone; an opaque cloud bubble keeps the art untouched.",
            "reason_ar": "الرسمة تحت الكلام زحمة أو قريبة في الدرجة؛ سحابة (cloud bubble) مقفولة تحت الكلام من غير مانغيّر الرسمة."}


def alternative_text_colour(assessment: Mapping, roles: Mapping[str, str] | None = None) -> str | None:
    """A role colour for the text that passes on the untreated art, if one exists."""
    region = assessment["_region"]
    w_min, a_min, pct = assessment["wcag_min"], assessment["apca_min_abs"], assessment["percentile"]
    options = [c for c in ((roles or {}).get("text"), (roles or {}).get("background"), (roles or {}).get("outline")) if c]
    options += ["#1a1a1a", "#ffffff"]
    for c in options:
        if _passes(_contrast_stats(parse_rgb(c), region, pct), w_min, a_min):
            return to_hex(c)
    return None


def check_text_box(image: Any, box_px: Sequence[float], text_colour: ColourLike, font_size_pt: float,
                   bold: bool = False, roles: Mapping[str, str] | None = None, box_id: str = "text",
                   percentile: float = LOW_PERCENTILE) -> dict:
    """Facts + proposal + finding for one text box (the art is never changed)."""
    a = assess(image, box_px, text_colour, font_size_pt, bold, percentile)
    proposal = propose_treatment(a, roles)
    findings = []
    if not a["passes_wcag"]:
        findings.append({"finding": "text_contrast_below_minimum", "blocking": True, "box_id": box_id,
                         "wcag_p": a["wcag_p"], "wcag_min": a["wcag_min"], "apca_abs_p": a["apca_abs_p"],
                         "apca_min_abs": a["apca_min_abs"], "proposed": proposal["treatment"],
                         "ar": "الكلام مش مقروء كفاية على الرسمة في المكان ده — اتقترحت معالجة من غير تغيير الرسمة.",
                         "en": "Text is below the contrast floor over the art here — a treatment is proposed; the art "
                               "is not changed."})
    elif not a["passes_apca"]:
        findings.append({"finding": "text_contrast_apca_low", "blocking": False, "box_id": box_id,
                         "apca_abs_p": a["apca_abs_p"], "apca_min_abs": a["apca_min_abs"],
                         "proposed": proposal["treatment"],
                         "ar": "التباين ماشي بمقياس WCAG بس ضعيف بمقياس APCA — تنبيه، واتقترحت معالجة.",
                         "en": "Contrast meets WCAG but is low by APCA (advisory); a treatment is proposed."})
    elif a["texture"]["level"] == "busy":
        findings.append({"finding": "busy_background_under_text", "blocking": False, "box_id": box_id,
                         "proposed": proposal["treatment"],
                         "ar": "الخلفية تحت الكلام زحمة — تنبيه بس.", "en": "Busy art under the text (advisory)."})
    public = {k: v for k, v in a.items() if not k.startswith("_")}
    return {"box_id": box_id, "facts": public, "proposal": proposal,
            "alternative_text_colour": alternative_text_colour(a, roles) if not a["passes"] else None,
            "findings": findings, "blocking": any(f["blocking"] for f in findings)}


def check_page(image: Any, boxes: Sequence[Mapping], roles: Mapping[str, str] | None = None) -> dict:
    """``boxes``: [{"id", "box_px", "text_colour", "font_size_pt", "bold"?}]."""
    results = [check_text_box(image, b["box_px"], b["text_colour"], b["font_size_pt"], b.get("bold", False),
                              roles, b.get("id", f"text{i}")) for i, b in enumerate(boxes)]
    return {"boxes": results, "blocking": any(r["blocking"] for r in results),
            "findings": [f for r in results for f in r["findings"]]}
