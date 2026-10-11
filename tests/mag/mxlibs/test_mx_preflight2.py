"""mx_preflight2 gate: one good PDF passes; nine named bad PDFs each fail with the right check id."""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

import pytest

from mxlibs.mx_preflight2 import CHECK_IDS, make_profile, run

ROOT = Path(__file__).resolve().parents[3]
PROFILE = {"size": "A5", "bleed_mm": 3.0, "safe_mm": 5.0, "expected_pages": 4}
ARABIC = re.compile("[؀-ۿ]")

#: name -> (builder kwargs, check id that must fail)
BAD = {
    "no_bleed": ({"background": "trim"}, "bleed"),
    "missing_font": ({"font": "standard"}, "fonts_embedded"),
    "low_dpi_96": ({"image_px": (192, 192)}, "image_dpi"),
    "text_in_safe_band": ({"text_at_mm": (5.0, 100.0)}, "safe_zone"),
    "wrong_size": ({"trim_mm": (210.0, 297.0)}, "page_size"),
    "encrypted": ({"encrypt": True}, "encryption"),
    "page_count_mismatch": ({"pages": 3}, "page_count"),
    "image_only": ({"font": None}, "image_only"),
    "cmyk_mismatch": ({"cmyk": True}, "colour_space"),
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_good_pdf_passes_every_check(pdf_factory):
    good = pdf_factory("good")
    result = run(good, PROFILE)
    assert result["ok"], result["failed"]
    assert [c["id"] for c in result["checks"]] == list(CHECK_IDS)
    assert result["pages"] == 4 and result["page_size_mm"] == [154.0, 216.0]
    assert result["sha256"] == _sha(good)
    for check in result["checks"]:
        assert set(check) >= {"id", "ok", "ar", "en", "detail"}
        assert ARABIC.search(check["ar"]) and check["en"]
    dpi = result["facts"]["images"][0]
    assert dpi["dpi"] == pytest.approx(300.0, abs=0.5) and dpi["px"] == [600, 600]
    assert result["facts"]["fonts"][0]["embedded"] and result["facts"]["fonts"][0]["file"] == "FontFile2"


@pytest.mark.parametrize("name", sorted(BAD))
def test_named_bad_pdf_fails_with_its_check(pdf_factory, name):
    kwargs, check_id = BAD[name]
    result = run(pdf_factory(name, **kwargs), PROFILE)
    assert not result["ok"]
    assert check_id in result["failed"], result["failed"]
    failing = next(c for c in result["checks"] if c["id"] == check_id)
    assert ARABIC.search(failing["ar"]) and failing["en"]
    if name != "wrong_size":  # an A4 page also moves the text outside the A5 safe area: a real second finding
        assert result["failed"] == [check_id]


def test_bad_messages_are_specific(pdf_factory):
    low = run(pdf_factory("low_dpi_96", **BAD["low_dpi_96"][0]), PROFILE)
    check = next(c for c in low["checks"] if c["id"] == "image_dpi")
    assert "96" in check["ar"] and check["detail"]["below_min"][0]["dpi"] == pytest.approx(96.0, abs=0.5)
    font = run(pdf_factory("missing_font", **BAD["missing_font"][0]), PROFILE)
    assert "Helvetica" in next(c for c in font["checks"] if c["id"] == "fonts_embedded")["ar"]
    bleed = run(pdf_factory("no_bleed", **BAD["no_bleed"][0]), PROFILE)
    assert "النزيف" in next(c for c in bleed["checks"] if c["id"] == "bleed")["ar"]


def test_page_without_any_bleed_area(pdf_factory):
    trim_only = pdf_factory("trim_only", media_mm=(148.0, 210.0), trimbox=False)
    result = run(trim_only, PROFILE)
    assert {"page_size", "bleed"} <= set(result["failed"])
    bleed = next(c for c in result["checks"] if c["id"] == "bleed")
    assert bleed["detail"]["first_failure"]["no_bleed_area"]
    # The same file is right for a no-bleed profile (P129's default bleed is 0): negative control.
    assert run(trim_only, {**PROFILE, "bleed_mm": 0})["ok"]


def test_white_edges_need_no_bleed(pdf_factory):
    result = run(pdf_factory("white_edges", background=None), PROFILE)
    assert result["ok"], result["failed"]


def test_important_box_in_safe_band(pdf_factory):
    good = pdf_factory("good")
    inside = [{"page": 2, "box_mm": [30, 30, 40, 20], "label": "child name"}]
    edge = [{"page": 2, "box_mm": [5, 30, 40, 20], "label": "child name"}]
    assert run(good, {**PROFILE, "important_boxes": inside})["ok"]
    result = run(good, {**PROFILE, "important_boxes": edge})
    assert result["failed"] == ["safe_zone"]
    violation = next(c for c in result["checks"] if c["id"] == "safe_zone")["detail"]["violations"][0]
    assert violation["kind"] == "box" and violation["page"] == 2 and violation["zone"] == "safe_band"


def test_cmyk_profile_rejects_the_rgb_record(pdf_factory):
    result = run(pdf_factory("good"), {**PROFILE, "colour": "cmyk"})
    assert result["failed"] == ["colour_space"]
    assert "RGB" in next(c for c in result["checks"] if c["id"] == "colour_space")["ar"]


def test_run_is_pure(pdf_factory):
    good = pdf_factory("good")
    before = (_sha(good), sorted(p.name for p in good.parent.iterdir()))
    run(good, PROFILE)
    assert before == (_sha(good), sorted(p.name for p in good.parent.iterdir()))


def test_unreadable_file(tmp_path):
    junk = tmp_path / "junk.pdf"
    junk.write_bytes(b"not a pdf")
    result = run(junk, PROFILE)
    assert result["failed"] == ["readable"]


def test_profile_validation():
    assert make_profile("A4")["trim_mm"] == (210.0, 297.0)
    with pytest.raises(ValueError):
        make_profile("B5")
    with pytest.raises(ValueError):
        make_profile("A5", colour="hexachrome")


def test_libreoffice_export_of_the_story_deck(render_deck, soffice, fixture_fontconfig, tmp_path, monkeypatch):
    """A real deck exported by the vendored pptx_to_pdf passes the structural checks."""
    sys.path.insert(0, str(ROOT / "vendor" / "modulex"))
    import pptx_to_pdf

    deck, spec = render_deck("ar_boy", "A5")
    monkeypatch.setenv("FONTCONFIG_FILE", str(fixture_fontconfig))
    monkeypatch.setenv("MODULEX_SOFFICE", soffice)
    pdf = tmp_path / "story.pdf"
    pptx_to_pdf.convert(deck, pdf, expect_pages=spec["_expected"]["slides"], engines=["soffice"])
    result = run(pdf, {**PROFILE, "expected_pages": spec["_expected"]["slides"]})
    by_id = {c["id"]: c for c in result["checks"]}
    for check_id in (
        "readable",
        "encryption",
        "page_count",
        "page_size",
        "fonts_embedded",
        "image_only",
        "safe_zone",
        "colour_space",
    ):
        assert by_id[check_id]["ok"], (check_id, by_id[check_id])
    assert any("Tajawal" in f["name"] for f in result["facts"]["fonts"])
    # Negative control on the same real file: an A4 printer profile refuses it by size.
    assert "page_size" in run(pdf, {**PROFILE, "size": "A4", "expected_pages": 4})["failed"]


def test_dpi_follows_nested_form_matrix(pdf_factory):
    """The CTM is tracked through a nested Form XObject /Matrix when computing effective dpi."""
    import pikepdf

    src = pdf_factory("nested_dpi", pages=1, image_px=None)
    with pikepdf.open(src, allow_overwriting_input=True) as pdf:
        page = pdf.pages[0]
        image = pdf.make_stream(
            b"\x80" * (300 * 300 * 3),
            Type=pikepdf.Name.XObject,
            Subtype=pikepdf.Name.Image,
            Width=300,
            Height=300,
            ColorSpace=pikepdf.Name.DeviceRGB,
            BitsPerComponent=8,
        )
        form = pdf.make_stream(
            b"q 72 0 0 72 0 0 cm /Im9 Do Q",
            Type=pikepdf.Name.XObject,
            Subtype=pikepdf.Name.Form,
            BBox=[0, 0, 72, 72],
            Matrix=[2, 0, 0, 2, 0, 0],
            Resources=pikepdf.Dictionary(XObject=pikepdf.Dictionary(Im9=image)),
        )
        page.Resources.XObject = pikepdf.Dictionary(Fm1=form)
        page.contents_add(pdf.make_stream(b"q 1 0 0 1 100 200 cm /Fm1 Do Q"), prepend=False)
        pdf.save(src)
    result = run(src, {**PROFILE, "expected_pages": 1})
    image = result["facts"]["images"][0]
    # 300 px over 1 in x 2 (form Matrix) = 2 in -> 150 dpi: passes the 150 floor, warns below the 300 ideal.
    assert image["dpi"] == pytest.approx(150.0, abs=0.5) and image["placed_mm"] == [50.8, 50.8]
    assert result["ok"] and any(w["id"] == "image_dpi" for w in result["warnings"])
    strict = run(src, {**PROFILE, "expected_pages": 1, "min_dpi": 200})
    assert strict["failed"] == ["image_dpi"]
