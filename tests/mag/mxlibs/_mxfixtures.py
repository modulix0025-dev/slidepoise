"""PDF fixture builder for the mxlibs suites, built programmatically with pikepdf (no network, no binaries).

`build_pdf` writes a small magazine-like PDF: a full-bleed (or trim-only) background,
text set in the embedded OFL fixture font Tajawal (TrueType, FontFile2) or in a
non-embedded standard font, an optional RGB image placed at a chosen effective
resolution, optional DeviceCMYK colour and optional encryption.
"""

from __future__ import annotations

import zlib
from pathlib import Path

import numpy as np
import pikepdf

FONTS = Path(__file__).resolve().parents[1] / "fixtures" / "fonts"
TAJAWAL = FONTS / "tajawal" / "Tajawal-Regular.ttf"
PT_PER_MM = 72 / 25.4
FOGRA39 = Path("/usr/share/color/icc/colord/FOGRA39L_coated.icc")
GRACOL = Path("/usr/share/color/icc/colord/GRACoL_TR006_coated.icc")


def mm(value: float) -> float:
    return value * PT_PER_MM


def _truetype_font(pdf: pikepdf.Pdf) -> pikepdf.Dictionary:
    from fontTools.ttLib import TTFont

    font = TTFont(str(TAJAWAL))
    upem = font["head"].unitsPerEm
    cmap = font.getBestCmap()
    hmtx = font["hmtx"].metrics
    widths = [round(hmtx[cmap[c]][0] * 1000 / upem) if c in cmap else 0 for c in range(32, 127)]
    descriptor = pikepdf.Dictionary(
        Type=pikepdf.Name.FontDescriptor,
        FontName=pikepdf.Name("/Tajawal-Regular"),
        Flags=32,
        FontBBox=[-200, -400, 1200, 1000],
        ItalicAngle=0,
        Ascent=800,
        Descent=-300,
        CapHeight=700,
        StemV=80,
        FontFile2=pikepdf.Stream(pdf, TAJAWAL.read_bytes()),
    )
    font.close()
    return pdf.make_indirect(
        pikepdf.Dictionary(
            Type=pikepdf.Name.Font,
            Subtype=pikepdf.Name.TrueType,
            BaseFont=pikepdf.Name("/Tajawal-Regular"),
            FirstChar=32,
            LastChar=126,
            Widths=widths,
            Encoding=pikepdf.Name.WinAnsiEncoding,
            FontDescriptor=pdf.make_indirect(descriptor),
        )
    )


def _standard_font(pdf: pikepdf.Pdf) -> pikepdf.Dictionary:
    return pdf.make_indirect(
        pikepdf.Dictionary(
            Type=pikepdf.Name.Font,
            Subtype=pikepdf.Name.Type1,
            BaseFont=pikepdf.Name.Helvetica,
            Encoding=pikepdf.Name.WinAnsiEncoding,
        )
    )


def _image(pdf: pikepdf.Pdf, px: tuple[int, int], cmyk: bool = False) -> pikepdf.Stream:
    w, h = px
    yy, xx = np.mgrid[0:h, 0:w]
    if cmyk:
        arr = np.stack(
            [(xx * 255 // max(1, w - 1)), (yy * 255 // max(1, h - 1)), np.full_like(xx, 40), np.full_like(xx, 10)],
            axis=-1,
        ).astype(np.uint8)
        cs = pikepdf.Name.DeviceCMYK
    else:
        arr = np.stack(
            [(xx * 255 // max(1, w - 1)), (yy * 255 // max(1, h - 1)), np.full_like(xx, 128)], axis=-1
        ).astype(np.uint8)
        cs = pikepdf.Name.DeviceRGB
    return pikepdf.Stream(
        pdf,
        zlib.compress(arr.tobytes()),
        Type=pikepdf.Name.XObject,
        Subtype=pikepdf.Name.Image,
        Width=w,
        Height=h,
        ColorSpace=cs,
        BitsPerComponent=8,
        Filter=pikepdf.Name.FlateDecode,
    )


def build_pdf(
    path: Path,
    *,
    pages: int = 4,
    trim_mm=(148.0, 210.0),
    bleed_mm: float = 3.0,
    media_mm=None,
    background: str | None = "full",
    bg_rgb=(0.20, 0.55, 0.85),
    font: str | None = "embedded",
    text_at_mm=None,
    text: str = "ModuleX Magazine",
    image_px: tuple | None = (600, 600),
    image_place_mm=(40.0, 60.0, 50.8, 50.8),
    cmyk: bool = False,
    encrypt: bool = False,
    trimbox: bool = True,
    extra_content: bytes = b"",
    extra_resources: dict | None = None,
) -> Path:
    """Write a fixture PDF. Positions are canvas mm from the lower-left corner of the MediaBox.

    ``text`` may contain ``{n}`` (the 1-based page number), so imposition tests can find each page.
    """
    trim_w, trim_h = trim_mm
    media_w, media_h = media_mm or (trim_w + 2 * bleed_mm, trim_h + 2 * bleed_mm)
    off_x, off_y = (media_w - trim_w) / 2, (media_h - trim_h) / 2
    pdf = pikepdf.new()
    font_obj = None
    if font == "embedded":
        font_obj = _truetype_font(pdf)
    elif font == "standard":
        font_obj = _standard_font(pdf)
    image_obj = pdf.make_indirect(_image(pdf, image_px, cmyk=cmyk)) if image_px else None
    for number in range(1, pages + 1):
        ops = []
        fill = b"0.1 0.4 0.6 0.1 k" if cmyk else ("%.3f %.3f %.3f rg" % bg_rgb).encode()
        if background == "full":
            ops.append(b"q " + fill + b" 0 0 %.3f %.3f re f Q" % (mm(media_w), mm(media_h)))
        elif background == "trim":
            ops.append(b"q " + fill + b" %.3f %.3f %.3f %.3f re f Q" % (mm(off_x), mm(off_y), mm(trim_w), mm(trim_h)))
        if image_obj is not None:
            x, y, w, h = image_place_mm
            ops.append(b"q %.4f 0 0 %.4f %.4f %.4f cm /Im1 Do Q" % (mm(w), mm(h), mm(x), mm(y)))
        if font_obj is not None:
            tx, ty = text_at_mm or (off_x + 20.0, off_y + 30.0)
            colour = b"0 0 0 1 k" if cmyk else b"0 0 0 rg"
            ops.append(
                b"q "
                + colour
                + b" BT /F1 14 Tf %.3f %.3f Td (" % (mm(tx), mm(ty))
                + text.format(n=number).encode("latin-1")
                + b") Tj ET Q"
            )
        if extra_content:
            ops.append(extra_content)
        resources = pikepdf.Dictionary()
        if font_obj is not None:
            resources.Font = pikepdf.Dictionary(F1=font_obj)
        if image_obj is not None:
            resources.XObject = pikepdf.Dictionary(Im1=image_obj)
        for key, value in (extra_resources or {}).items():
            resources[key] = value
        page = pikepdf.Dictionary(
            Type=pikepdf.Name.Page,
            MediaBox=[0, 0, mm(media_w), mm(media_h)],
            Resources=resources,
            Contents=pikepdf.Stream(pdf, b"\n".join(ops)),
        )
        if trimbox:
            page.TrimBox = [mm(off_x), mm(off_y), mm(off_x + trim_w), mm(off_y + trim_h)]
            page.BleedBox = [0, 0, mm(media_w), mm(media_h)]
        pdf.pages.append(pikepdf.Page(page))
    kwargs = {}
    if encrypt:
        kwargs["encryption"] = pikepdf.Encryption(owner="operator-secret", user="", R=6)
    path = Path(path)
    pdf.save(path, **kwargs)
    pdf.close()
    return path
