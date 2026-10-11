"""Institution sales deck: 16:9 editable PPTX, Arabic right-to-left, built with the forked SlidePoise renderer.

Every word is a native, editable text box (no text in pictures) fitted with the
shaping-aware fitter; sample pages are the watermarked preview images, never
the print file. Prices are the operator's SUGGESTED numbers — the Store decides.
"""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path

W, H = 1920, 1080  # px on a 13.333 × 7.5 in slide (16:9)
PT_PER_PX = (40 / 3 * 72) / W

DEFAULT_THEME = {"title_font": "Tajawal", "body_font": "Tajawal", "ink": "#23313F", "accent": "#F2A33A",
                 "panel": "#FFF6E6", "background": "#FFFFFF"}


def _text(oid: str, box: tuple[float, float, float, float], text: str, size_pt: float, theme: dict, *,
          font: str | None = None, bold: bool = False, colour: str | None = None, align: str = "right",
          min_pt: float = 12.0) -> dict:
    return {"id": oid, "kind": "textbox", "bbox_px": [round(v, 2) for v in box], "z": 3, "text": text,
            "min_pt": min_pt,
            "style": {"font_family": font or theme["body_font"], "font_size_pt": size_pt, "direction": "rtl",
                      "lang": "ar-EG", "alignment": align, "vertical_alignment": "middle",
                      "line_spacing_multiple": 1.15, "color": colour or theme["ink"], "margins_px": [0, 0, 0, 0],
                      "font_weight": "bold" if bold else "normal"}}


def _panel(oid: str, box, theme: dict, fill: str | None = None) -> dict:
    return {"id": oid, "kind": "shape", "shape": "rounded_rectangle", "bbox_px": [round(v, 2) for v in box], "z": 1,
            "round_rect_adjustment": 9000, "style": {"fill": fill or theme["panel"], "stroke": theme["accent"],
                                                     "stroke_width_px": 3}}


def _slide(sid: str, objects: list[dict], theme: dict) -> dict:
    return {"id": sid, "dimensions_px": [W, H], "background": theme["background"], "objects": objects}


def _image(oid: str, box, path: Path) -> dict:
    """Picture centred inside `box` at its own aspect ratio (the renderer stretches rasters to the box)."""
    from PIL import Image  # noqa: PLC0415

    data = Path(path).read_bytes()
    with Image.open(path) as image:
        ratio = image.width / image.height
    left, top, width, height = box
    shown_w = min(width, height * ratio)
    shown_h = shown_w / ratio
    fitted = (left + (width - shown_w) / 2, top + (height - shown_h) / 2, shown_w, shown_h)
    return {"id": oid, "kind": "image", "bbox_px": [round(v, 2) for v in fitted], "z": 2, "source_path": str(path),
            "source_sha256": hashlib.sha256(data).hexdigest()}


def deck_spec(institution: str, offer: dict, sample_images: list[Path], theme: dict | None = None) -> dict:
    theme = dict(DEFAULT_THEME, **(theme or {}))
    title_font = theme["title_font"]
    m = 96  # outer margin (px)
    slides = []
    slides.append(_slide("s1", [
        _panel("s1_band", (0, H - 220, W, 220), theme, fill=theme["accent"]),
        _text("s1_title", (m, 250, W - 2 * m, 220), f"مجلة لكل طفل في {institution}", 54, theme, font=title_font,
              bold=True, min_pt=28),
        _text("s1_sub", (m, 490, W - 2 * m, 140),
              "قصة مطبوعة باسم طفلك وصورته — من ModuleX، معمولة مخصوص لمدرستكم", 28, theme, min_pt=16),
        _text("s1_footer", (m, H - 190, W - 2 * m, 140), offer.get("tagline", "كل طفل بطل حكايته"), 30, theme,
              colour="#FFFFFF", bold=True, min_pt=16),
    ], theme))
    steps = offer.get("steps") or ["المدرسة بتبعت أسماء الأطفال وصورهم بموافقة أولياء الأمور",
                                   "بنعمل لكل طفل مجلته باسمه وصورته",
                                   "بنبعت بروفة للمراجعة قبل الطباعة",
                                   "بنطبع ونسلّم المجلات للمدرسة"]
    objects = [_text("s2_title", (m, 60, W - 2 * m, 130), "إزاي بتشتغل؟", 44, theme, font=title_font, bold=True,
                     min_pt=24)]
    step_h = (H - 260 - m) / len(steps)
    for i, step in enumerate(steps):
        top = 220 + i * step_h
        objects.append(_panel(f"s2_p{i + 1}", (m, top, W - 2 * m, step_h - 24), theme))
        objects.append(_text(f"s2_n{i + 1}", (W - m - 120, top, 100, step_h - 24), str(i + 1), 36, theme,
                             font=title_font, bold=True, colour=theme["accent"], align="center", min_pt=18))
        objects.append(_text(f"s2_t{i + 1}", (m + 40, top + 10, W - 2 * m - 200, step_h - 44), step, 26, theme,
                             min_pt=14))
    slides.append(_slide("s2", objects, theme))
    if sample_images:
        objects = [_text("s3_title", (m, 60, W - 2 * m, 130), "صفحات من القصة", 44, theme, font=title_font,
                         bold=True, min_pt=24)]
        shown = sample_images[:3]
        gap = 48
        cell_w = (W - 2 * m - gap * (len(shown) - 1)) / len(shown)
        for i, image in enumerate(shown):  # right to left: the first page sits on the right
            left = W - m - (i + 1) * cell_w - i * gap
            objects.append(_image(f"s3_img{i + 1}", (left, 220, cell_w, H - 220 - m - 80), Path(image)))
        objects.append(_text("s3_note", (m, H - m - 70, W - 2 * m, 60),
                             "معاينة — النسخة المطبوعة بجودة كاملة ومن غير علامة", 20, theme, align="center",
                             min_pt=12))
        slides.append(_slide("s3", objects, theme))
    benefits = offer.get("benefits") or ["كل طفل بياخد مجلته الخاصة باسمه",
                                         "صفحة جماعية للفصل كله",
                                         "شهادة تقدير باسم كل طفل",
                                         "صور الأطفال عمرها ما بتتعدّل بالذكاء الاصطناعي"]
    objects = [_text("s4_title", (m, 60, W - 2 * m, 130), "مجلة الفصل", 44, theme, font=title_font, bold=True,
                     min_pt=24)]
    for i, line in enumerate(benefits):  # the bullet is a shape on the right: a "•" character can land on the left
        top = 230 + i * 170
        objects.append({"id": f"s4_dot{i + 1}", "kind": "shape", "shape": "ellipse", "z": 2,
                        "bbox_px": [W - m - 28, top + 60, 28, 28],
                        "style": {"fill": theme["accent"], "stroke": theme["accent"], "stroke_width_px": 1}})
        objects.append(_text(f"s4_b{i + 1}", (m, top, W - 2 * m - 60, 140), line, 28, theme, min_pt=14))
    slides.append(_slide("s4", objects, theme))
    price = offer.get("suggested_price_egp")
    lines = [f"سعر مقترح للطفل: {price} جنيه" if price is not None else "السعر حسب عدد الأطفال",
             f"أقل عدد: {offer['min_children']} طفل" if offer.get("min_children") else "",
             f"التسليم خلال {offer['delivery_days']} يوم" if offer.get("delivery_days") else ""]
    objects = [_text("s5_title", (m, 60, W - 2 * m, 130), "العرض", 44, theme, font=title_font, bold=True, min_pt=24),
               _panel("s5_panel", (m, 220, W - 2 * m, 560), theme)]
    for i, line in enumerate([x for x in lines if x]):
        objects.append(_text(f"s5_l{i + 1}", (m + 60, 260 + i * 170, W - 2 * m - 120, 140), line, 32, theme,
                             min_pt=16))
    objects.append(_text("s5_note", (m, 820, W - 2 * m, 80), "الأسعار مقترحة وبيتم تأكيدها في عرض السعر الرسمي", 18,
                         theme, min_pt=12))
    slides.append(_slide("s5", objects, theme))
    contact = offer.get("contact") or "تواصلوا معانا لعرض سعر لمدرستكم"
    slides.append(_slide("s6", [
        _panel("s6_panel", (m, 260, W - 2 * m, 420), theme),
        _text("s6_title", (m + 40, 300, W - 2 * m - 80, 160), "يلا نبدأ؟", 54, theme, font=title_font, bold=True,
              align="center", min_pt=28),
        _text("s6_contact", (m + 40, 480, W - 2 * m - 80, 160), contact, 30, theme, align="center", min_pt=16),
    ], theme))
    return {"title": f"ModuleX — {institution}", "language": "ar-EG", "slides": slides,
            "theme": {"display_font": title_font, "body_font": theme["body_font"]}}


def fit_deck(spec: dict, registry=None) -> tuple[dict, list[dict]]:
    """Shrink every text box (half points, not below its minimum) until it fits; report the facts."""
    from slidepoise.arabic.fit import fit_text  # noqa: PLC0415
    from slidepoise.arabic.fonts import default_registry  # noqa: PLC0415

    registry = registry or default_registry()
    out = copy.deepcopy(spec)
    facts = []
    for slide in out["slides"]:
        for obj in slide["objects"]:
            if obj.get("kind") != "textbox":
                continue
            style = obj["style"]
            _, _, w, h = obj["bbox_px"]
            result = fit_text(obj["text"], w * PT_PER_PX, h * PT_PER_PX, style["font_family"],
                              bold=style.get("font_weight") == "bold", registry=registry,
                              max_size_pt=style["font_size_pt"], min_size_pt=obj.pop("min_pt", 12.0),
                              spacing=style["line_spacing_multiple"], inset_pt=0.0)
            style["font_size_pt"] = result.size_pt
            facts.append({"slide": slide["id"], "object": obj["id"], "fits": result.fits, "size_pt": result.size_pt,
                          "font": result.font_family})
    return out, facts


def build_sales_deck(out_pptx: Path, institution: str, offer: dict, sample_images: list[Path],
                     theme: dict | None = None, registry=None, render=None) -> dict:
    spec = deck_spec(institution, offer, sample_images, theme)
    fitted, facts = fit_deck(spec, registry)
    overflow = [f for f in facts if not f["fits"]]
    if overflow:
        raise ValueError(f"text does not fit: {[f['object'] for f in overflow]}")
    if render is None:
        from mxstudio.validators.synthetic_story import render  # noqa: PLC0415
    out_pptx = Path(out_pptx)
    render(fitted, out_pptx)
    texts = [obj["text"] for slide in fitted["slides"] for obj in slide["objects"] if obj["kind"] == "textbox"]
    return {"pptx": str(out_pptx), "slides": len(fitted["slides"]), "fit": facts, "texts": texts}
