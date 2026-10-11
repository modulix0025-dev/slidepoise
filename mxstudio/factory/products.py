"""Themes, new products and their Store candidates (M3).

* A theme = type theme + palette + frame set applied to the same story.
* New page kinds (about_me, certificate, qr_back, coloring, bilingual, class_page)
  go through the same factory and validators as every other page.
* The class magazine is a PLAN for the operator's existing institution orders
  (one personalised order per child + group pages) — never a new order engine.
* QR codes are made per order (pure function); the template only reserves a
  picture placeholder labelled "qr".
"""
from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

PAGE_KIND_PRODUCTS = {
    "dedication": {"title_ar": "صفحة إهداء", "title_en": "Dedication page", "suggested_tokens": 0},
    "about_me": {"title_ar": "صفحة «أنا مين» بصورة طفلك", "title_en": "\"About me\" page with your photo",
                 "suggested_tokens": 20},
    "certificate": {"title_ar": "شهادة تقدير باسم طفلك", "title_en": "Certificate with your child's name",
                    "suggested_tokens": 20},
    "qr_back": {"title_ar": "غلاف خلفي بكود فيلم طفلك", "title_en": "Back cover with a QR to the video",
                "suggested_tokens": 10},
    "coloring": {"title_ar": "نسخة تلوين", "title_en": "Coloring edition", "suggested_tokens": 60},
    "bilingual": {"title_ar": "نسخة عربي/إنجليزي", "title_en": "Bilingual edition", "suggested_tokens": 40},
    "class_page": {"title_ar": "مجلة الفصل", "title_en": "Class magazine", "suggested_tokens": 0},
}


@dataclass
class Theme:
    key: str
    name_ar: str
    name_en: str
    type_theme: dict           # {"title": family, "body": family, "name": family}
    palette: dict              # {"text","panel","outline","background", ...}
    frame_set: str = "rounded_panel"
    tags: list[str] = field(default_factory=list)

    def layout_theme(self) -> dict:
        return {"name": self.name_ar, "fonts": {"title": self.type_theme["title"], "body": self.type_theme["body"]},
                "colours": {"text": self.palette["text"], "panel": self.palette["panel"],
                            "outline": self.palette["outline"], "background": self.palette.get("background", "#FFFFFF")}}


def theme_from_type_theme(type_theme_id: str, palette: dict, *, language: str = "ar", key: str | None = None,
                          frame_set: str = "rounded_panel") -> Theme:
    """A factory Theme whose fonts come from a Phase-4 type theme (catalog/fonts/type_themes.json).

    Only themes that pass the fonts validator are shipped there, so every family is certified_print.
    """
    from mxstudio.fonts.themes import load_themes  # noqa: PLC0415
    found = next((t for t in load_themes()["themes"] if t["id"] == type_theme_id), None)
    if found is None:
        raise ValueError(f"unknown type theme {type_theme_id!r}")
    prefix = "ar" if language == "ar" else "en"
    fonts = {"title": found[f"{prefix}_title"], "body": found[f"{prefix}_body"],
             "name": found["ar_name"] if prefix == "ar" else found["en_title"]}
    return Theme(key=key or type_theme_id, name_ar=found["name_ar"], name_en=found["name_en"], type_theme=fonts,
                 palette=palette, frame_set=frame_set, tags=["type_theme:" + type_theme_id])

def m3_candidate(kind: str, story_key: str | None = None, theme: Theme | None = None,
                 previews: list[str] | None = None) -> dict:
    """Store product candidate: presentation + previews + a SUGGESTED price (the Store decides)."""
    if kind not in PAGE_KIND_PRODUCTS and kind != "theme":
        raise ValueError(f"unknown product kind {kind!r}")
    base = PAGE_KIND_PRODUCTS.get(kind, {"title_ar": theme.name_ar if theme else "", "title_en": theme.name_en
                                         if theme else "", "suggested_tokens": 0})
    return {"contract": "mag/v1/m3", "schema_version": 1, "product_key": f"{kind}:{story_key or 'any'}"
            + (f":{theme.key}" if theme else ""), "kind": kind, "title_ar": base["title_ar"],
            "title_en": base["title_en"], "suggested_price_tokens": base["suggested_tokens"],
            "requires_story_keys": [story_key] if story_key else [], "previews": previews or [],
            "theme": asdict(theme) if theme else None, "created_at": time.time(),
            "note": "price is a suggestion; the Store owns prices and the token economy"}


def make_qr_png(url: str, out_path: Path, box_size: int = 20, border: int = 4) -> Path:
    """Per-order QR (to the child's video / narrated audio, or the "make it a video" offer)."""
    if not re.match(r"^https?://[^\s]+$", url or ""):
        raise ValueError("QR target must be an http(s) URL")
    import qrcode  # noqa: PLC0415 - BSD licence
    image = qrcode.make(url, box_size=box_size, border=border, error_correction=qrcode.constants.ERROR_CORRECT_M)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path)
    return out_path


def class_magazine_plan(story_key: str, roster: list[dict], class_name: str, language: str = "ar",
                        size: str = "A4") -> dict:
    """One personalised order per child through the EXISTING institution flow, plus group pages."""
    orders, problems = [], []
    for index, child in enumerate(roster, 1):
        name = str(child.get("name", "")).strip()
        gender = child.get("gender")
        if not name or gender not in {"male", "female"}:
            problems.append(f"row {index}: needs a name and gender male/female")
            continue
        orders.append({"child_name": name, "gender": gender, "story_name": story_key, "language": language,
                       "size": size})
    return {"class_name": class_name, "story_key": story_key, "orders": orders, "problems": problems,
            "group_pages": ["class_page"], "engine": "existing institution orders (generate_story per child)"}
