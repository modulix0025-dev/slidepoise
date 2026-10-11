"""mx_impose: saddle-stitch order (LTR/RTL), creep, output sizes, crop marks, CMYK derivative."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import numpy as np
import pikepdf
import pypdfium2 as pdfium
import pytest
from _mxfixtures import FOGRA39, GRACOL, mm

from mxlibs.mx_impose import (
    ColourConverter,
    cmyk_derivative,
    creep_offsets,
    crop_marks,
    impose_saddle,
    padded_count,
    saddle_stitch_order,
)
from mxlibs.mx_preflight2 import run as preflight

PAGE_LABEL = re.compile(r"Page (\d+)")
needs_icc = pytest.mark.skipif(
    not (FOGRA39.is_file() and GRACOL.is_file()), reason="colord-data press profiles (CC0) are installed in mag-ci only"
)
NEON_GREEN = (57 / 255, 1.0, 20 / 255)


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# --------------------------------------------------------------------------- order
def test_sixteen_page_ltr_order():
    spreads = saddle_stitch_order(16, "ltr")
    assert len(spreads) == 8
    assert (spreads[0]["left"], spreads[0]["right"]) == (16, 1)  # outer sheet, front
    assert (spreads[1]["left"], spreads[1]["right"]) == (2, 15)  # outer sheet, back
    assert (spreads[2]["left"], spreads[2]["right"]) == (14, 3)
    assert (spreads[7]["left"], spreads[7]["right"]) == (8, 9)  # centre spread
    assert all(s["left"] + s["right"] == 17 for s in spreads)


def test_sixteen_page_rtl_order_is_the_mirror():
    ltr, rtl = saddle_stitch_order(16, "ltr"), saddle_stitch_order(16, "rtl")
    assert (rtl[0]["left"], rtl[0]["right"]) == (1, 16)
    assert (rtl[1]["left"], rtl[1]["right"]) == (15, 2)
    for a, b in zip(ltr, rtl, strict=True):
        assert (a["sheet"], a["side"]) == (b["sheet"], b["side"])
        assert (a["left"], a["right"]) == (b["right"], b["left"])


def test_every_page_once_and_blank_padding():
    for n in (4, 8, 12, 16, 20):
        pages = [p for s in saddle_stitch_order(n) for p in (s["left"], s["right"])]
        assert sorted(pages) == list(range(1, n + 1))
    padded = saddle_stitch_order(10, "rtl")
    assert padded_count(10) == 12
    assert [p for s in padded for p in (s["left"], s["right"])].count(None) == 2
    with pytest.raises(ValueError):
        saddle_stitch_order(16, "ttb")


def test_creep_offsets_are_monotonic():
    offsets = creep_offsets(4, 0.6)
    assert offsets == [0.0, 0.2, 0.4, 0.6]
    assert all(b >= a for a, b in zip(offsets, offsets[1:], strict=False))
    assert creep_offsets(1, 0.5) == [0.0] and creep_offsets(0, 1) == []


# --------------------------------------------------------------------------- imposed file
def _labels_by_half(path: Path) -> list[tuple[int | None, int | None, float | None, float | None]]:
    """For each output page: (left page no, right page no, left label x0, right label x0) in pt."""
    out = []
    doc = pdfium.PdfDocument(str(path))
    try:
        for page in doc:
            width, height = page.get_size()
            textpage = page.get_textpage()
            row = []
            xs = []
            for x0, x1 in ((0, width / 2), (width / 2, width)):
                found = PAGE_LABEL.search(textpage.get_text_bounded(x0, 0, x1, height) or "")
                row.append(int(found.group(1)) if found else None)
                hits = textpage.search(found.group(0)) if found else None
                pos = None
                if hits is not None:
                    hit = hits.get_next()
                    while hit is not None:
                        box = textpage.get_charbox(hit[0])
                        if x0 <= box[0] < x1:
                            pos = box[0]
                            break
                        hit = hits.get_next()
                xs.append(pos)
            out.append((row[0], row[1], xs[0], xs[1]))
            textpage.close()
    finally:
        doc.close()
    return out


@pytest.mark.parametrize("binding", ["ltr", "rtl"])
def test_impose_sixteen_a5_on_four_a4_sheets(pdf_factory, tmp_path, binding):
    src = pdf_factory("book16", pages=16, text="Page {n}", image_px=None)
    out = tmp_path / f"imposed_{binding}.pdf"
    record = impose_saddle(src, out, binding=binding, creep_mm=0.6)
    assert record["sheets"] == 4 and record["output_pages"] == 8 and record["sheet_mm"] == [297.0, 210.0]
    assert record["source_sha256"] == _sha(src) and record["output_sha256"] == _sha(out)
    with pikepdf.open(out) as pdf:
        assert len(pdf.pages) == 8
        for page in pdf.pages:
            w, h = (float(v) for v in page.mediabox[2:])
            assert w == pytest.approx(mm(297), abs=0.01) and h == pytest.approx(mm(210), abs=0.01)
    found = _labels_by_half(out)
    expected = saddle_stitch_order(16, binding)
    assert [(left, right) for left, right, _, _ in found] == [(s["left"], s["right"]) for s in expected]


def test_creep_moves_inner_pages_toward_the_spine(pdf_factory, tmp_path):
    src = pdf_factory("book16", pages=16, text="Page {n}", image_px=None)
    impose_saddle(src, tmp_path / "flat.pdf", binding="ltr")
    impose_saddle(src, tmp_path / "crept.pdf", binding="ltr", creep_mm=0.6)
    flat, crept = _labels_by_half(tmp_path / "flat.pdf"), _labels_by_half(tmp_path / "crept.pdf")
    # Outer sheet (output page 0) does not move; innermost (output page 6) moves 0.6 mm toward the spine.
    assert crept[0][2] == pytest.approx(flat[0][2], abs=0.05)
    assert crept[6][2] - flat[6][2] == pytest.approx(mm(0.6), abs=0.05)  # left page moves right
    assert flat[6][3] - crept[6][3] == pytest.approx(mm(0.6), abs=0.05)  # right page moves left


def test_impose_refuses_to_overwrite_and_oversize(pdf_factory, tmp_path):
    src = pdf_factory("book16", pages=16, text="Page {n}", image_px=None)
    with pytest.raises(ValueError):
        impose_saddle(src, src)
    with pytest.raises(ValueError):
        impose_saddle(src, tmp_path / "small.pdf", sheet="A5")


# --------------------------------------------------------------------------- crop marks
def test_crop_marks_sheet_boxes_and_marks(pdf_factory, tmp_path):
    src = pdf_factory("good", pages=4)
    before = _sha(src)
    out = tmp_path / "marks.pdf"
    record = crop_marks(src, out, mark_len_mm=5)
    assert _sha(src) == before and record["output_sha256"] == _sha(out)
    page = record["pages"][0]
    assert page["sheet_mm"] == [168.0, 230.0] and page["trim_mm"] == [148.0, 210.0] and page["marks"] == 8
    with pikepdf.open(out) as pdf:
        first = pdf.pages[0]
        trim = [float(v) for v in first.obj.TrimBox]
        assert trim == pytest.approx([mm(10), mm(10), mm(158), mm(220)], abs=0.01)
    doc = pdfium.PdfDocument(str(out))
    image = np.asarray(doc[0].render(scale=300 / 72).to_pil().convert("L"))
    doc.close()
    px = lambda v: int(round(v / 25.4 * 300))
    h = image.shape[0]
    # vertical mark below the lower-left trim corner (x = 10 mm, y from 0 to 2 mm from the sheet bottom)
    assert image[h - px(3.5), px(10)] < 128
    # the gap between mark and trim (bleed zone corner) shows the art, not a mark: art is blue, not black
    assert image[h - px(8.5), px(10)] > 60
    # nothing outside the marks: sheet corner is white
    assert image[2, 2] > 250
    # the trimmed result is still a valid page: preflight on the sheet's TrimBox finds the A5 trim
    result = preflight(out, {"size": "A5", "bleed_mm": 0, "check_text_in_safe": False})
    assert "page_size" in result["failed"]  # the sheet is bigger than A5 by design (negative control)


# --------------------------------------------------------------------------- CMYK derivative
@needs_icc
def test_neon_green_page_becomes_cmyk_with_output_intent(pdf_factory, tmp_path):
    src = pdf_factory("neon", pages=2, bg_rgb=NEON_GREEN)
    before = _sha(src)
    out = tmp_path / "neon_cmyk.pdf"
    record = cmyk_derivative(src, out, FOGRA39)
    assert _sha(src) == before  # the approved RGB file is untouched
    assert record["source_sha256"] == before == record["derived_from_sha256"]
    assert record["output_sha256"] == _sha(out)
    assert (
        record["icc_profile"]["sha256"] == _sha(FOGRA39) and record["icc_profile"]["description"] == "FOGRA39L Coated"
    )
    assert record["pdfx_certified"] is False and record["rasterised_pages"] == []
    assert record["remaining_rgb"] == {"operators": 0, "images": 0}
    assert record["converted"]["images"] == 1 and record["max_tac_seen"] <= 300.0
    with pikepdf.open(out) as pdf:
        content = pdf.pages[0].Contents.read_bytes()
        assert b" rg" not in content and b" k\n" in content
        assert b"0.6 0 0.9333 0 k" in content  # neon green (57,255,20) -> C60 M0 Y93 K0 in FOGRA39
        intent = pdf.Root.OutputIntents[0]
        assert str(intent.S) == "/GTS_PDFX" and str(intent.OutputConditionIdentifier) == "FOGRA39L Coated"
        assert hashlib.sha256(intent.DestOutputProfile.read_bytes()).hexdigest() == _sha(FOGRA39)
        assert "/GTS_PDFXVersion" not in pdf.docinfo
        assert str(pdf.docinfo["/MxDerivedFromSha256"]) == before
        image = pdf.pages[0].Resources.XObject.Im1
        assert str(image.ColorSpace) == "/DeviceCMYK"


@needs_icc
def test_cmyk_derivative_passes_cmyk_preflight_and_mismatch_fails(pdf_factory, tmp_path):
    src = pdf_factory("neon4", pages=4, bg_rgb=NEON_GREEN)
    out = tmp_path / "neon4_cmyk.pdf"
    cmyk_derivative(src, out, FOGRA39)
    profile = {"size": "A5", "expected_pages": 4, "colour": "cmyk", "icc_path": str(FOGRA39)}
    assert preflight(out, profile)["ok"]
    mismatch = preflight(out, {**profile, "icc_path": str(GRACOL)})
    assert mismatch["failed"] == ["colour_space"]
    assert preflight(src, profile)["failed"] == ["colour_space"]  # the RGB record is not a CMYK file


@needs_icc
def test_tac_limit_caps_rich_black(pdf_factory, tmp_path):
    src = pdf_factory("black", pages=1, bg_rgb=(0.0, 0.0, 0.0), image_px=None)
    record = cmyk_derivative(src, tmp_path / "black_cmyk.pdf", FOGRA39, tac_limit=260)
    assert record["tac_capped_samples"] > 0
    with pikepdf.open(tmp_path / "black_cmyk.pdf") as pdf:
        for item in pikepdf.parse_content_stream(pdf.pages[0]):
            if str(item.operator) == "k":
                assert sum(float(v) for v in item.operands) * 100 <= 260.5


@needs_icc
def test_colour_converter_known_values():
    conv = ColourConverter(FOGRA39)
    c, m, y, k = conv.colour(1.0, 0.0, 0.0)
    assert c < 0.05 and m > 0.9 and y > 0.9 and k < 0.05
    with pytest.raises(ValueError):
        ColourConverter(Path("/usr/share/color/icc/colord/AdobeRGB1998.icc"))  # an RGB profile is refused


def _shaded(pdf_factory, name: str) -> Path:
    shading = pikepdf.Dictionary(
        ShadingType=2,
        ColorSpace=pikepdf.Name.DeviceRGB,
        Coords=[0, 0, 85, 0],
        Function=pikepdf.Dictionary(FunctionType=2, Domain=[0, 1], C0=[1, 0, 0], C1=[0, 0, 1], N=1),
        Extend=[True, True],
    )
    return pdf_factory(
        name,
        pages=2,
        trim_mm=(24.0, 24.0),
        bleed_mm=3.0,
        image_px=None,
        font=None,
        extra_content=b"q 0 0 85 85 re W n /Sh0 sh Q",
        extra_resources={"/Shading": pikepdf.Dictionary(Sh0=shading)},
    )


@needs_icc
def test_shading_page_is_rasterised_at_600_dpi_and_flagged(pdf_factory, tmp_path):
    src = _shaded(pdf_factory, "shaded")
    out = tmp_path / "shaded_cmyk.pdf"
    record = cmyk_derivative(src, out, FOGRA39)
    assert [r["page"] for r in record["rasterised_pages"]] == [1, 2]
    assert record["rasterised_pages"][0]["reasons"] == ["shading"] and record["rasterised_pages"][0]["dpi"] == 600
    with pikepdf.open(out) as pdf:
        image = pdf.pages[0].Resources.XObject.MxRaster
        assert str(image.ColorSpace) == "/DeviceCMYK"
        assert int(image.Width) == round(30 / 25.4 * 600) and int(image.Height) == round(30 / 25.4 * 600)
        assert "/Shading" not in pdf.pages[0].Resources
    assert record["remaining_rgb"] == {"operators": 0, "images": 0}


@needs_icc
def test_transparency_group_page_is_rasterised(pdf_factory, tmp_path):
    src = pdf_factory("group", pages=2, trim_mm=(24.0, 24.0), image_px=None)
    with pikepdf.open(src, allow_overwriting_input=True) as pdf:
        pdf.pages[1].obj.Group = pikepdf.Dictionary(S=pikepdf.Name.Transparency, CS=pikepdf.Name.DeviceRGB)
        pdf.save(src)
    record = cmyk_derivative(src, tmp_path / "group_cmyk.pdf", FOGRA39, raster_dpi=300)
    assert [r["page"] for r in record["rasterised_pages"]] == [2]
    assert record["pages"][0]["mode"] == "vector" and record["pages"][1]["mode"] == "raster"


@needs_icc
def test_cmyk_refuses_to_overwrite_the_record(pdf_factory):
    src = pdf_factory("neon", pages=2, bg_rgb=NEON_GREEN)
    with pytest.raises(ValueError):
        cmyk_derivative(src, src, FOGRA39)


@needs_icc
def test_arabic_paths_end_to_end(tmp_path):
    """Operator estate lives under Arabic folders: every lib must read and write such paths."""
    from _mxfixtures import build_pdf

    folder = tmp_path / "المشروع" / "مجلة إياد"
    folder.mkdir(parents=True)
    src = build_pdf(folder / "الملف المعتمد.pdf", pages=4, bg_rgb=NEON_GREEN)
    assert preflight(src, {"size": "A5", "expected_pages": 4})["ok"]
    record = cmyk_derivative(src, folder / "نسخة المطبعة.pdf", FOGRA39, raster_dpi=150, force_raster_pages=[2])
    assert record["rasterised_pages"][0]["page"] == 2
    assert impose_saddle(src, folder / "تجميع.pdf", binding="rtl")["output_pages"] == 2
    assert crop_marks(src, folder / "علامات القص.pdf")["pages"][0]["marks"] == 8


@needs_icc
def test_form_xobjects_and_icc_rgb_spaces_are_converted(pdf_factory, tmp_path):
    src = pdf_factory("forms", pages=1, image_px=None)
    with pikepdf.open(src, allow_overwriting_input=True) as pdf:
        srgb = pdf.make_stream(Path("/usr/share/color/icc/colord/sRGB.icc").read_bytes(), N=3)
        form = pdf.make_stream(
            b"0 1 0 rg 0 0 50 50 re f /CS0 cs 1 0 0 sc 10 10 20 20 re f",
            Type=pikepdf.Name.XObject,
            Subtype=pikepdf.Name.Form,
            BBox=[0, 0, 50, 50],
            Resources=pikepdf.Dictionary(
                ColorSpace=pikepdf.Dictionary(CS0=pikepdf.Array([pikepdf.Name.ICCBased, srgb]))
            ),
        )
        page = pdf.pages[0]
        page.Resources.XObject = pikepdf.Dictionary(Fm0=form)
        page.contents_add(pdf.make_stream(b"q 1 0 0 1 100 100 cm /Fm0 Do Q"), prepend=False)
        pdf.save(src)
    out = tmp_path / "forms_cmyk.pdf"
    record = cmyk_derivative(src, out, FOGRA39)
    assert record["remaining_rgb"]["operators"] == 0 and record["converted"]["colour_spaces"] == 1
    with pikepdf.open(out) as pdf:
        parsed = pikepdf.parse_content_stream(pdf.pages[0].Resources.XObject.Fm0)
        ops = [(str(i.operator), [float(v) for v in i.operands if not isinstance(v, pikepdf.Object)]) for i in parsed]
        names = [str(i.operands[0]) for i in parsed if str(i.operator) == "cs"]
    assert names == ["/DeviceCMYK"]
    assert [op for op, _ in ops].count("k") == 1 and "rg" not in [op for op, _ in ops]
    sc = next(values for op, values in ops if op == "sc")
    assert len(sc) == 4 and sc[1] > 0.9  # red -> mostly magenta
