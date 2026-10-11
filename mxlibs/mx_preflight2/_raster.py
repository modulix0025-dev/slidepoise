"""pypdfium2 measurements: page rasters for the bleed test and text-run boxes for the safe zone.

Rule enforced: bleed is judged on rendered pixels (what the press will print),
and text positions come from the PDF's own text layer. Both are facts; no
visual-quality score is produced.
"""

from __future__ import annotations

import numpy as np

MM_PER_PT = 25.4 / 72.0
INK_LEVEL = 245  # a pixel is "ink" if any channel is below this (0-255)


def open_document(path: str, password: str | None = None):
    import pypdfium2 as pdfium

    # Opened through a Python file handle: Arabic (non-ANSI) Windows paths never reach pdfium as bytes.
    return pdfium.PdfDocument(open(path, "rb"), password=password, autoclose=True)  # noqa: SIM115


def render_media(doc, index: int, dpi: float) -> np.ndarray:
    """RGB raster of the whole MediaBox (the crop box is widened in memory only; nothing is saved)."""
    page = doc[index]
    try:
        page.set_cropbox(*page.get_mediabox())
        bitmap = page.render(scale=dpi / 72.0, may_draw_forms=True)
        image = bitmap.to_pil().convert("RGB")
        return np.asarray(image)
    finally:
        page.close()


def text_rects(doc, index: int) -> list[tuple[float, float, float, float, str]]:
    """Text-run rectangles in pt, relative to the MediaBox lower-left: (x0, y0, x1, y1, text)."""
    page = doc[index]
    out = []
    try:
        mx0, my0, _mx1, _my1 = page.get_mediabox()
        textpage = page.get_textpage()
        try:
            for i in range(textpage.count_rects()):
                a, b, c, d = textpage.get_rect(i)
                x0, x1 = sorted((a, c))
                y0, y1 = sorted((b, d))
                text = textpage.get_text_bounded(x0, y0, x1, y1) or ""
                if text.strip():
                    out.append((x0 - mx0, y0 - my0, x1 - mx0, y1 - my0, text.strip()))
        finally:
            textpage.close()
    finally:
        page.close()
    return out


def bleed_edges(image: np.ndarray, media_mm: tuple, trim_mm: tuple, dpi: float, gap_tolerance: float = 0.05) -> dict:
    """Per side: does ink that touches the trim edge continue through the bleed band?

    media_mm / trim_mm are (x0, y0, x1, y1) in mm, PDF orientation (y up).
    """
    height, width = image.shape[:2]
    ink = image.min(axis=2) < INK_LEVEL
    mx0, my0, mx1, my1 = media_mm
    tx0, ty0, tx1, ty1 = trim_mm
    px = lambda mm: mm / 25.4 * dpi
    col = lambda x_mm: int(round(px(x_mm - mx0)))
    row = lambda y_mm: int(round(px(my1 - y_mm)))
    left, right = col(tx0), col(tx1)
    top, bottom = row(ty1), row(ty0)
    margin = max(1, int(round(px(0.3))))
    inner_lo, inner_hi = max(1, int(round(px(0.5)))), max(2, int(round(px(1.5))))
    sides = {}
    spans = {
        # side: (band slice, inner slice, along-edge slice, axis to reduce)
        "left": (
            (slice(top, bottom), slice(margin, left - margin)),
            (slice(top, bottom), slice(left + inner_lo, left + inner_hi)),
            1,
        ),
        "right": (
            (slice(top, bottom), slice(right + margin, width - margin)),
            (slice(top, bottom), slice(right - inner_hi, right - inner_lo)),
            1,
        ),
        "top": (
            (slice(margin, top - margin), slice(left, right)),
            (slice(top + inner_lo, top + inner_hi), slice(left, right)),
            0,
        ),
        "bottom": (
            (slice(bottom + margin, height - margin), slice(left, right)),
            (slice(bottom - inner_hi, bottom - inner_lo), slice(left, right)),
            0,
        ),
    }
    for side, (band_sl, inner_sl, axis) in spans.items():
        band = ink[band_sl]
        inner = ink[inner_sl]
        depth = band.shape[axis] if band.size else 0
        bleed_mm = (tx0 - mx0, mx1 - tx1, my1 - ty1, ty0 - my0)[("left", "right", "top", "bottom").index(side)]
        if depth < 1 or bleed_mm < 0.5:
            sides[side] = {
                "bleed_mm": round(bleed_mm, 2),
                "band_px": int(depth),
                "edge_ink": None,
                "band_coverage": 0.0,
                "gap_ratio": 1.0,
                "ok": False,
                "no_bleed_area": True,
            }
            continue
        inner_ink = inner.any(axis=axis)
        band_cov = band.mean(axis=axis) >= 0.9
        with_ink = int(inner_ink.sum())
        gaps = int((inner_ink & ~band_cov).sum())
        ratio = gaps / with_ink if with_ink else 0.0
        sides[side] = {
            "bleed_mm": round(bleed_mm, 2),
            "band_px": int(depth),
            "edge_ink": round(with_ink / max(1, inner_ink.size), 3),
            "band_coverage": round(float(band.mean()), 3),
            "gap_ratio": round(ratio, 3),
            "ok": ratio <= gap_tolerance,
            "no_bleed_area": False,
        }
    return sides
