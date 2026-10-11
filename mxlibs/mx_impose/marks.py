"""Crop (trim) marks: each page centred on a larger sheet with marks at the trim corners.

Rules enforced: the page is placed 1:1 (never scaled); its bleed is kept; marks
start ``offset_mm`` outside the trim (never less than the bleed, so they never
print into the art) and are drawn in the registration colour (Separation /All).
TrimBox and BleedBox of the output sheet point at the placed page, so a later
preflight or RIP can find the trim.
"""

from __future__ import annotations

import pikepdf

from ._pdfutil import media_rect, mm, page_form, same_file, sha256_file, to_mm, trim_rect

MARK_WIDTH_PT = 0.25


def _registration(pdf: pikepdf.Pdf) -> pikepdf.Object:
    tint = pikepdf.Dictionary(FunctionType=2, Domain=[0, 1], C0=[0, 0, 0, 0], C1=[1, 1, 1, 1], N=1)
    return pdf.make_indirect(pikepdf.Array([pikepdf.Name.Separation, pikepdf.Name.All, pikepdf.Name.DeviceCMYK, tint]))


def crop_marks(
    pdf_in,
    pdf_out,
    *,
    bleed_mm: float | None = None,
    mark_len_mm: float = 5.0,
    offset_mm: float | None = None,
    margin_mm: float = 2.0,
) -> dict:
    """Write ``pdf_out`` with every page of ``pdf_in`` on a sheet carrying crop marks. Returns the record."""
    if same_file(pdf_in, pdf_out):
        raise ValueError("pdf_out must differ from pdf_in (the source is never overwritten)")
    src_sha = sha256_file(pdf_in)
    pages_out = []
    with pikepdf.open(pdf_in) as pdf:
        registration = _registration(pdf)
        count = len(pdf.pages)
        for index in range(count):
            page = pdf.pages[index]
            media = media_rect(page)
            trim = trim_rect(page, bleed_mm)
            page_bleed = max(
                to_mm(trim[0] - media[0]),
                to_mm(media[2] - trim[2]),
                to_mm(trim[1] - media[1]),
                to_mm(media[3] - trim[3]),
                0.0,
            )
            offset = max(offset_mm if offset_mm is not None else 3.0, page_bleed)
            reach = mm(offset + mark_len_mm + margin_mm)
            trim_w, trim_h = trim[2] - trim[0], trim[3] - trim[1]
            sheet_w, sheet_h = trim_w + 2 * reach, trim_h + 2 * reach
            dx, dy = reach - trim[0], reach - trim[1]  # moves the trim's lower-left to (reach, reach)
            form = page_form(pdf, page)
            tx0, ty0, tx1, ty1 = reach, reach, reach + trim_w, reach + trim_h
            gap, length = mm(offset), mm(mark_len_mm)
            lines = []
            for x in (tx0, tx1):
                for y, sign in ((ty0, -1), (ty1, 1)):
                    lines.append((x, y + sign * gap, x, y + sign * (gap + length)))  # vertical mark
            for y in (ty0, ty1):
                for x, sign in ((tx0, -1), (tx1, 1)):
                    lines.append((x + sign * gap, y, x + sign * (gap + length), y))  # horizontal mark
            ops = [
                b"q 1 0 0 1 %.4f %.4f cm /MxPage Do Q" % (dx, dy),
                b"q /MxReg CS 1 SCN %.2f w 0 J [] 0 d" % MARK_WIDTH_PT,
            ]
            ops += [b"%.4f %.4f m %.4f %.4f l S" % line for line in lines]
            ops.append(b"Q")
            sheet = pikepdf.Dictionary(
                Type=pikepdf.Name.Page,
                MediaBox=[0, 0, sheet_w, sheet_h],
                TrimBox=[tx0, ty0, tx1, ty1],
                BleedBox=[media[0] + dx, media[1] + dy, media[2] + dx, media[3] + dy],
                Resources=pikepdf.Dictionary(
                    XObject=pikepdf.Dictionary(MxPage=form), ColorSpace=pikepdf.Dictionary(MxReg=registration)
                ),
                Contents=pikepdf.Stream(pdf, b"\n".join(ops)),
            )
            pdf.pages.append(pikepdf.Page(sheet))
            pages_out.append(
                {
                    "page": index + 1,
                    "sheet_mm": [round(to_mm(sheet_w), 2), round(to_mm(sheet_h), 2)],
                    "trim_mm": [round(to_mm(trim_w), 2), round(to_mm(trim_h), 2)],
                    "bleed_mm": round(page_bleed, 2),
                    "mark_offset_mm": round(offset, 2),
                    "marks": len(lines),
                }
            )
        del pdf.pages[0:count]
        pdf.save(pdf_out, compress_streams=True)
    return {
        "kind": "crop_marks",
        "source_path": str(pdf_in),
        "source_sha256": src_sha,
        "output_path": str(pdf_out),
        "output_sha256": sha256_file(pdf_out),
        "pages": pages_out,
        "mark_len_mm": mark_len_mm,
        "colour": "Separation /All (registration)",
    }
