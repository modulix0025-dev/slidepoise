"""Saddle-stitch imposition: reader pages -> printer spreads on folded, nested sheets.

Rules enforced:

* Page count is padded to a multiple of 4 with blank pages (never dropped).
* Sheet ``i`` (0 = outermost) carries, for LEFT-TO-RIGHT binding
  front ``n-2i | 1+2i`` and back ``2+2i | n-1-2i`` (16 pages: 16|1, 2|15, 14|3 ...).
  RIGHT-TO-LEFT binding (Arabic) is the mirror: front ``1+2i | n-2i``, back ``n-1-2i | 2+2i``.
* Back sides assume duplex flipped on the SHORT edge (landscape sheet). For a
  long-edge flip the back side is turned 180 degrees.
* Creep: inner sheets stick out at the fore-edge once folded, so their page
  content is shifted toward the spine. The shift grows linearly from 0 on the
  outermost sheet to ``creep_mm`` on the innermost one (monotonic).
* Pages are placed 1:1 (never scaled) and clipped to their cell; the trim of
  each page meets the spine.
"""

from __future__ import annotations

import pikepdf

from ._pdfutil import media_rect, mm, page_form, same_file, sha256_file, sheet_size_mm, to_mm, trim_rect


def padded_count(n_pages: int) -> int:
    if n_pages < 1:
        raise ValueError("at least one page is needed")
    return (n_pages + 3) // 4 * 4


def saddle_stitch_order(n_pages: int, binding: str = "ltr") -> list[dict]:
    """Printer spreads for a saddle-stitched booklet. Page numbers > n_pages are blanks (None)."""
    if binding not in ("ltr", "rtl"):
        raise ValueError("binding must be 'ltr' or 'rtl'")
    total = padded_count(n_pages)
    spreads = []
    for i in range(total // 4):
        front = (total - 2 * i, 1 + 2 * i)
        back = (2 + 2 * i, total - 1 - 2 * i)
        if binding == "rtl":
            front, back = front[::-1], back[::-1]
        for side, (left, right) in (("front", front), ("back", back)):
            spreads.append(
                {
                    "sheet": i + 1,
                    "side": side,
                    "left": left if left <= n_pages else None,
                    "right": right if right <= n_pages else None,
                    "left_slot": left,
                    "right_slot": right,
                }
            )
    return spreads


def creep_offsets(n_sheets: int, creep_mm: float) -> list[float]:
    """Shift toward the spine per sheet, outermost first: 0 ... creep_mm, linear and monotonic."""
    if n_sheets < 1:
        return []
    if n_sheets == 1:
        return [0.0]
    return [round(creep_mm * i / (n_sheets - 1), 4) for i in range(n_sheets)]


def impose_saddle(
    pdf_in,
    pdf_out,
    *,
    binding: str = "ltr",
    sheet="auto",
    creep_mm: float = 0.0,
    duplex: str = "short_edge",
    bleed_mm: float | None = None,
) -> dict:
    """Write the imposed booklet (one output page per sheet side). Returns the record.

    sheet: "auto" (A4 landscape when two trims fit it, else exactly two trims wide),
           a name ("A4", "A3", "SRA3" ...) used landscape, or (width_mm, height_mm).
    """
    if same_file(pdf_in, pdf_out):
        raise ValueError("pdf_out must differ from pdf_in (the source is never overwritten)")
    if duplex not in ("short_edge", "long_edge"):
        raise ValueError("duplex must be 'short_edge' or 'long_edge'")
    src_sha = sha256_file(pdf_in)
    with pikepdf.open(pdf_in) as pdf:
        n = len(pdf.pages)
        first = pdf.pages[0]
        trim = trim_rect(first, bleed_mm)
        trim_w, trim_h = trim[2] - trim[0], trim[3] - trim[1]
        if sheet == "auto":
            a4w, a4h = sheet_size_mm("A4", landscape=True)
            need_w, need_h = to_mm(2 * trim_w), to_mm(trim_h)
            sheet_w_mm, sheet_h_mm = (a4w, a4h) if need_w <= a4w + 0.01 and need_h <= a4h + 0.01 else (need_w, need_h)
        else:
            sheet_w_mm, sheet_h_mm = sheet_size_mm(sheet, landscape=True)
        sheet_w, sheet_h = mm(sheet_w_mm), mm(sheet_h_mm)
        if 2 * trim_w > sheet_w + 0.5 or trim_h > sheet_h + 0.5:
            raise ValueError(
                f"two {to_mm(trim_w):.1f}x{to_mm(trim_h):.1f} mm pages do not fit a "
                f"{sheet_w_mm:.1f}x{sheet_h_mm:.1f} mm sheet"
            )
        forms = {}
        geometry = {}
        for index in range(n):
            page = pdf.pages[index]
            forms[index + 1] = page_form(pdf, page)
            geometry[index + 1] = (media_rect(page), trim_rect(page, bleed_mm))
        spreads = saddle_stitch_order(n, binding)
        n_sheets = len(spreads) // 2
        offsets = creep_offsets(n_sheets, creep_mm)
        spine_x = sheet_w / 2
        margin_x = (sheet_w - 2 * trim_w) / 2
        y_trim = (sheet_h - trim_h) / 2
        out_sides = []
        for spread in spreads:
            shift = mm(offsets[spread["sheet"] - 1])
            ops = []
            xobjects = pikepdf.Dictionary()
            for slot in ("left", "right"):
                number = spread[slot]
                if number is None:
                    continue
                media, ptrim = geometry[number]
                p_trim_w = ptrim[2] - ptrim[0]
                if slot == "left":
                    cell_x0, cell_x1 = spine_x - p_trim_w, spine_x
                    clip = (cell_x0 - min(margin_x, ptrim[0] - media[0]), cell_x1)
                    target_x = cell_x0 + shift
                else:
                    cell_x0, cell_x1 = spine_x, spine_x + p_trim_w
                    clip = (cell_x0, cell_x1 + min(margin_x, media[2] - ptrim[2]))
                    target_x = cell_x0 - shift
                bleed_y = min(y_trim, ptrim[1] - media[1], media[3] - ptrim[3])
                clip_y = (y_trim - bleed_y, y_trim + (ptrim[3] - ptrim[1]) + bleed_y)
                dx, dy = target_x - ptrim[0], y_trim - ptrim[1]
                name = f"/P{number}"
                xobjects[name] = forms[number]
                ops.append(
                    b"q %.4f %.4f %.4f %.4f re W n 1 0 0 1 %.4f %.4f cm %s Do Q"
                    % (clip[0], clip_y[0], clip[1] - clip[0], clip_y[1] - clip_y[0], dx, dy, name.encode())
                )
            side = pikepdf.Dictionary(
                Type=pikepdf.Name.Page,
                MediaBox=[0, 0, sheet_w, sheet_h],
                Resources=pikepdf.Dictionary(XObject=xobjects),
                Contents=pikepdf.Stream(pdf, b"\n".join(ops)),
            )
            if duplex == "long_edge" and spread["side"] == "back":
                side.Rotate = 180
            pdf.pages.append(pikepdf.Page(side))
            out_sides.append(
                {
                    **{k: spread[k] for k in ("sheet", "side", "left", "right")},
                    "creep_shift_mm": offsets[spread["sheet"] - 1],
                }
            )
        del pdf.pages[0:n]
        pdf.save(pdf_out, compress_streams=True)
    return {
        "kind": "saddle_stitch",
        "binding": binding,
        "duplex": duplex,
        "source_path": str(pdf_in),
        "source_sha256": src_sha,
        "output_path": str(pdf_out),
        "output_sha256": sha256_file(pdf_out),
        "source_pages": n,
        "padded_pages": padded_count(n),
        "blank_pages": padded_count(n) - n,
        "sheets": n_sheets,
        "output_pages": len(out_sides),
        "sheet_mm": [round(sheet_w_mm, 2), round(sheet_h_mm, 2)],
        "page_trim_mm": [round(to_mm(trim_w), 2), round(to_mm(trim_h), 2)],
        "creep_mm": creep_mm,
        "creep_offsets_mm": offsets,
        "sides": out_sides,
    }
