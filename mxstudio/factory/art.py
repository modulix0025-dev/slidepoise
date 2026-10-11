"""Art Desk: briefs for the image model, target checks, and contact sheets for the operator.

* The brief always asks for NO letters, words or signs: image models draw Arabic
  badly and pixels cannot be personalised. Text zones are described as calm,
  empty areas; every word is rebuilt later as native text.
* Character consistency comes from the story's figure prompts and reference
  images (passed to the provider), never from altering a customer photo.
* Targets are checked for glyph-like marks inside text slots (named finding).
* Contact sheets (rendered from the exported PDFs) are what the operator looks at.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from mxstudio.validators.art_text import inspect_target

NO_TEXT = ("no text, no letters, no words, no numbers, no signs, no captions, no watermark, no logo; "
           "leave the marked zone calm and empty for text added later")


def art_brief(story, page_index: int, variant: str, size: str, text_zone_mm: tuple | None = None,
              style: str = "warm children's picture-book illustration, soft shapes, friendly faces") -> dict:
    page = story.pages[page_index]
    gender = variant.split("_")[1]
    figure = story.figure_prompt_male if gender == "boy" else story.figure_prompt_female
    zone = ""
    if text_zone_mm:
        x, y, w, h = text_zone_mm
        zone = f" Keep a calm empty area at x={x:.0f}mm y={y:.0f}mm w={w:.0f}mm h={h:.0f}mm for the text panel."
    prompt = f"{page.scene}. {('Main character: ' + figure + '.') if page.figure and figure else ''} {style}.{zone}"
    return {"page": page_index + 1, "variant": variant, "size": size, "prompt": " ".join(prompt.split()),
            "negative": NO_TEXT, "figure": page.figure, "extra_characters": list(page.extra_characters)}


def check_target(image_path: Path, text_slots_px: dict) -> dict:
    findings = inspect_target(image_path, text_slots_px)
    return {"image": str(image_path), "slots": findings, "blocking": [f for f in findings if f["blocking"]]}


def contact_sheet(pdf_paths: list[Path], out_path: Path, thumb_height: int = 360, columns: int = 8,
                  labels: list[str] | None = None) -> Path:
    """Render every page of every PDF into one labelled sheet (pypdfium2 — permissive, no Poppler)."""
    import pypdfium2 as pdfium  # noqa: PLC0415

    thumbs: list[tuple[str, Image.Image]] = []
    for index, pdf in enumerate(pdf_paths):
        document = pdfium.PdfDocument(str(pdf))
        try:
            for number, page in enumerate(document, 1):
                scale = thumb_height / page.get_height()
                image = page.render(scale=scale).to_pil().convert("RGB")
                label = (labels[index] if labels else Path(pdf).stem) + f" · {number}"
                thumbs.append((label, image))
        finally:
            document.close()
    if not thumbs:
        raise ValueError("no pages to show")
    cell_w = max(img.width for _, img in thumbs) + 16
    cell_h = thumb_height + 34
    rows = (len(thumbs) + columns - 1) // columns
    sheet = Image.new("RGB", (cell_w * min(columns, len(thumbs)), cell_h * rows), (244, 244, 242))
    draw = ImageDraw.Draw(sheet)
    for i, (label, image) in enumerate(thumbs):
        x, y = (i % columns) * cell_w + 8, (i // columns) * cell_h + 8
        sheet.paste(image, (x, y))
        draw.rectangle((x - 1, y - 1, x + image.width, y + image.height), outline=(10, 10, 10))
        draw.text((x, y + image.height + 6), label, fill=(10, 10, 10))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)
    return out_path
