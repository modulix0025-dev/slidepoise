"""Small shared helpers for mx_impose: page boxes, forms, sha256, ICC facts.

Rule enforced: page geometry is read from the PDF's own boxes (TrimBox when
present, MediaBox otherwise), in points, and every output is identified by the
sha256 of its bytes.
"""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path

import pikepdf

PT_PER_MM = 72.0 / 25.4
SHEETS_MM = {
    "A3": (297.0, 420.0),
    "A4": (210.0, 297.0),
    "A5": (148.0, 210.0),
    "SRA3": (320.0, 450.0),
    "SRA4": (225.0, 320.0),
}


def mm(value: float) -> float:
    return float(value) * PT_PER_MM


def to_mm(value_pt: float) -> float:
    return float(value_pt) / PT_PER_MM


def sha256_file(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rect(box) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = (float(v) for v in box)
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def media_rect(page: pikepdf.Page) -> tuple[float, float, float, float]:
    return rect(page.mediabox)


def trim_rect(page: pikepdf.Page, bleed_mm: float | None = None) -> tuple[float, float, float, float]:
    """TrimBox if the page has one; else the MediaBox inset by ``bleed_mm`` (default 0)."""
    if "/TrimBox" in page.obj:
        return rect(page.obj.TrimBox)
    x0, y0, x1, y1 = media_rect(page)
    inset = mm(bleed_mm or 0.0)
    return (x0 + inset, y0 + inset, x1 - inset, y1 - inset)


def page_form(pdf: pikepdf.Pdf, page: pikepdf.Page) -> pikepdf.Object:
    """The page as an indirect Form XObject whose BBox is the whole MediaBox (bleed included)."""
    form = page.as_form_xobject(handle_transformations=True)
    form.BBox = pikepdf.Array([float(v) for v in media_rect(page)])
    return pdf.make_indirect(form) if not form.is_indirect else form


def sheet_size_mm(sheet, landscape: bool | None = None) -> tuple[float, float]:
    if isinstance(sheet, str):
        key = sheet.upper()
        if key not in SHEETS_MM:
            raise ValueError(f"unknown sheet size {sheet!r}; known: {sorted(SHEETS_MM)}")
        w, h = SHEETS_MM[key]
    else:
        w, h = (float(v) for v in sheet)
    if landscape is True and w < h or landscape is False and w > h:
        w, h = h, w
    return (w, h)


def icc_facts(data: bytes) -> dict:
    """sha256, description ('desc' tag, v2 or v4) and colour space of an ICC profile."""
    desc = ""
    try:
        count = struct.unpack(">I", data[128:132])[0]
        for i in range(min(count, 256)):
            sig, offset, size = struct.unpack(">4sII", data[132 + 12 * i : 144 + 12 * i])
            if sig != b"desc":
                continue
            tag = data[offset : offset + size]
            if tag[:4] == b"desc":
                length = struct.unpack(">I", tag[8:12])[0]
                desc = tag[12 : 12 + length].split(b"\x00", 1)[0].decode("latin-1", "replace").strip()
            elif tag[:4] == b"mluc" and struct.unpack(">I", tag[8:12])[0]:
                _l, _c, rlen, roff = struct.unpack(">2s2sII", tag[16:28])
                desc = tag[roff : roff + rlen].decode("utf-16-be", "replace").strip("\x00 ")
            break
    except (struct.error, IndexError):
        desc = ""
    return {
        "sha256": hashlib.sha256(data).hexdigest(),
        "description": desc,
        "colour_space": data[16:20].decode("latin-1").strip() if len(data) >= 20 else "",
        "bytes": len(data),
    }


def same_file(a, b) -> bool:
    try:
        return Path(a).resolve() == Path(b).resolve()
    except OSError:
        return str(a) == str(b)
