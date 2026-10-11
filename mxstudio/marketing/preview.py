"""Shared preview helpers: render PDF pages small and stamp a visible watermark.

Previews are screen images. The long edge is capped (PREVIEW_MAX_PX) so an A4
page lands near 95 dpi: fine on a phone, useless as a print file. Every image
carries a tiled diagonal watermark.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PREVIEW_MAX_PX = 1100
WATERMARK_AR = "معاينة فقط"
WATERMARK_EN = "PREVIEW · ModuleX"
ARABIC_FAMILIES = ("Tajawal", "Cairo", "Noto Sans Arabic", "Amiri", "Baloo Bhaijaan 2")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _font(size: int) -> tuple[ImageFont.ImageFont, bool]:
    """(font, can_shape_arabic). Arabic needs a real Arabic font and Pillow's raqm layout."""
    from PIL import features  # noqa: PLC0415

    try:
        from slidepoise.arabic.fonts import default_registry  # noqa: PLC0415
        registry = default_registry()
        for family in ARABIC_FAMILIES:
            face = registry.resolve(family, bold=True)
            if face is not None:
                return ImageFont.truetype(face.path, size, index=face.index), bool(features.check("raqm"))
    except Exception:  # noqa: BLE001 - a missing font only drops the Arabic half of the watermark
        pass
    return ImageFont.load_default(size=size), False


def render_pdf_pages(pdf: Path, max_px: int = PREVIEW_MAX_PX) -> list[Image.Image]:
    import pypdfium2 as pdfium  # noqa: PLC0415

    document = pdfium.PdfDocument(str(pdf))
    try:
        pages = []
        for page in document:
            scale = max_px / max(page.get_width(), page.get_height())
            pages.append(page.render(scale=scale).to_pil().convert("RGB"))
        return pages
    finally:
        document.close()


def watermark(image: Image.Image, opacity: int = 70) -> Image.Image:
    """Tile the watermark diagonally across the whole image (it cannot be cropped away)."""
    base = image.convert("RGBA")
    size = max(16, base.width // 18)
    font, arabic = _font(size)
    text = f"{WATERMARK_AR}  ·  {WATERMARK_EN}" if arabic else WATERMARK_EN
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    left, top, right, bottom = probe.textbbox((0, 0), text, font=font, direction="rtl" if arabic else None)
    tile_w, tile_h = right - left + size * 3, (bottom - top) + size * 4
    span = int((base.width ** 2 + base.height ** 2) ** 0.5) + tile_w
    layer = Image.new("RGBA", (span, span), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for row, y in enumerate(range(0, span, tile_h)):
        for x in range(-(row % 2) * tile_w // 2, span, tile_w):
            draw.text((x, y), text, font=font, fill=(255, 255, 255, opacity + 40), stroke_width=max(1, size // 14),
                      stroke_fill=(40, 40, 40, opacity), direction="rtl" if arabic else None)
    layer = layer.rotate(30, resample=Image.BICUBIC)
    off_x, off_y = (layer.width - base.width) // 2, (layer.height - base.height) // 2
    base.alpha_composite(layer.crop((off_x, off_y, off_x + base.width, off_y + base.height)))
    return base.convert("RGB")
