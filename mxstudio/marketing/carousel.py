"""Social carousels, 4:5 (1080×1350) and 1:1 (1080×1080), from watermarked preview pages.

Child data rule: a source that carries a real child's name or photo (an order
render, anything not an approved template sample) is used only with an explicit
consent record: granted=True, who granted it, a reference to where it was given,
and "social" in its scope. The record's reference — never the child's data — is
written to the carousel manifest. Template samples use the story's demo names.
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

from mxstudio.marketing.preview import WATERMARK_EN, _font, render_pdf_pages, sha256_file, watermark

ASPECTS = {"4:5": (1080, 1350), "1:1": (1080, 1080)}


class ConsentRequired(ValueError):
    code = "CONSENT_REQUIRED"
    ar = "الصفحات دي فيها بيانات طفل حقيقي — لازم موافقة صريحة من وليّ الأمر للنشر على السوشيال."
    en = "These pages carry a real child's data; explicit guardian consent for social use is required."


def check_consent(contains_child_data: bool, consent: dict | None) -> dict | None:
    """Return the consent facts to record, or raise ConsentRequired."""
    if not contains_child_data:
        return None
    consent = consent or {}
    ok = (consent.get("granted") is True and str(consent.get("granted_by", "")).strip()
          and str(consent.get("reference", "")).strip() and "social" in (consent.get("scope") or []))
    if not ok:
        raise ConsentRequired(ConsentRequired.en)
    return {"granted": True, "granted_by": str(consent["granted_by"])[:120],
            "reference": str(consent["reference"])[:120], "scope": list(consent["scope"])}


def _slide(page: Image.Image, size: tuple[int, int], caption: str, number: int, total: int, background: str,
           ink: str) -> Image.Image:
    width, height = size
    canvas = Image.new("RGB", size, background)
    band = int(height * 0.12)
    margin = int(width * 0.06)
    box_w, box_h = width - 2 * margin, height - band - 2 * margin
    scale = min(box_w / page.width, box_h / page.height)
    shown = page.resize((max(1, int(page.width * scale)), max(1, int(page.height * scale))), Image.LANCZOS)
    canvas.paste(shown, ((width - shown.width) // 2, margin + (box_h - shown.height) // 2))
    draw = ImageDraw.Draw(canvas)
    font, arabic = _font(max(18, width // 30))
    text = caption if arabic or caption.isascii() else WATERMARK_EN
    y = height - band + band // 4
    draw.text((width - margin, y), text, font=font, fill=ink, anchor="ra", direction="rtl" if arabic else None)
    draw.text((margin, y), f"{number}/{total}", font=font, fill=ink, anchor="la")
    return canvas


def build_carousel(pdf: Path, out_dir: Path, aspect: str, *, caption: str, contains_child_data: bool,
                   consent: dict | None = None, pages: list[int] | None = None, background: str = "#FFF8EC",
                   ink: str = "#2B2B2B") -> dict:
    if aspect not in ASPECTS:
        raise ValueError(f"aspect must be one of {sorted(ASPECTS)}")
    consent_facts = check_consent(contains_child_data, consent)  # before anything is rendered
    rendered = render_pdf_pages(Path(pdf))
    chosen = [rendered[i - 1] for i in (pages or range(1, len(rendered) + 1)) if 1 <= i <= len(rendered)][:10]
    if not chosen:
        raise ValueError("no pages selected")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for number, page in enumerate(chosen, 1):
        slide = _slide(watermark(page), ASPECTS[aspect], caption, number, len(chosen), background, ink)
        name = f"carousel_{aspect.replace(':', 'x')}_{number:02d}.png"
        slide.save(out_dir / name, optimize=True)
        files.append(name)
    manifest = {"kind": "social_carousel", "aspect": aspect, "size_px": list(ASPECTS[aspect]), "slides": files,
                "caption": caption, "contains_child_data": contains_child_data, "consent": consent_facts,
                "source_pdf_sha256": sha256_file(Path(pdf)), "watermarked": True}
    record = out_dir / f"carousel_{aspect.replace(':', 'x')}.json"
    record.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return dict(manifest, folder=str(out_dir))
