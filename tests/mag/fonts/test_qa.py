"""Font QA: measured facts → certified_print / screen_only / rejected with named reasons."""
from __future__ import annotations

import io
import shutil

import numpy as np
from fontTools.ttLib import TTFont

from mxstudio.fonts.qa import GlyphMask, _line_collisions, harakat_and_spacing, load_harakat_corpus, qa_font


def _ids(result) -> set[str]:
    return {r["finding"] for r in result["reasons"]}


def test_names_corpus_has_200_egyptian_names(committed):
    data = committed["egyptian_names"]
    boys = [n for n in data["names"] if n["gender"] == "boy"]
    girls = [n for n in data["names"] if n["gender"] == "girl"]
    assert len(data["names"]) >= 200 and len(boys) >= 100 and len(girls) >= 100
    arabic = {n["ar"] for n in data["names"]}
    assert {"عبد الرحمن", "فاطمة الزهراء", "نور الهدى", "منة الله"} <= arabic
    assert len(arabic) == len(data["names"])
    letters = set("".join(arabic))
    assert {chr(c) for c in range(0x0621, 0x063B)} <= letters | {"ء"}  # every base letter appears


def test_tajawal_is_certified_with_measured_spacing(fonts):
    result = qa_font(fonts["tajawal"], script="AR", roles=["body", "ui"])
    assert result["status"] == "certified_print" and _ids(result) == set()
    assert result["capabilities"] == {"vowelized_text": True, "vowelized_body": True, "lam_tatweel_dedication": True,
                                      "arabic_indic_digits": True}
    assert result["facts"]["shaping"]["names_with_notdef_count"] == 0
    assert result["min_safe_line_spacing"] >= 1.0
    assert result["on_device_export_proof"]["status"] == "pending"


def test_amiri_mark_overlap_is_measured(fonts):
    result = qa_font(fonts["amiri"], script="AR", roles=["body", "title"])
    assert result["status"] == "certified_print"
    assert "harakat_mark_mark_collision" in _ids(result)
    assert result["capabilities"]["vowelized_body"] is False
    assert "الحَبْلَ" in " ".join(result["facts"]["harakat"]["lines_with_collisions"])


def test_negative_control_colour_font_is_screen_only(fonts):
    result = qa_font(fonts["reemkufifun"], script="AR", roles=["title", "name"])
    assert result["status"] == "screen_only"
    assert "colour_font_quarantined" in _ids(result)
    assert result["capabilities"]["vowelized_body"] is False


def test_negative_control_font_without_tatweel_loses_dedication(fonts):
    result = qa_font(fonts["blaka"], script="AR", roles=["title", "handwriting"])
    assert "no_tatweel" in _ids(result)
    assert result["capabilities"]["lam_tatweel_dedication"] is False
    assert result["allowed_roles"] == ["title"]


def test_monospaced_arabic_is_limited_to_effect_titles(fonts):
    result = qa_font(fonts["thabit"], script="AR", roles=["title", "effect", "body"])
    assert {"monospace_arabic", "no_gpos_mkmk"} <= _ids(result)
    assert result["allowed_roles"] == ["title", "effect"]
    assert result["facts"]["arabic_advances"]["modal_share"] == 1.0


def test_latin_font_is_certified(fonts):
    result = qa_font(fonts["chewy"], script="EN", roles=["title", "name"])
    assert result["status"] == "certified_print" and result["capabilities"]["vowelized_body"] is None


def test_negative_control_restricted_embedding_is_rejected(fonts, tmp_path):
    font = TTFont(fonts["chewy"])
    font["OS/2"].fsType = 2
    out = io.BytesIO()
    font.save(out)
    path = tmp_path / "restricted.ttf"
    path.write_bytes(out.getvalue())
    result = qa_font(path, script="EN", roles=["title"])
    assert result["status"] == "rejected" and "embedding_refused" in _ids(result)
    assert result["allowed_roles"] == []


def test_negative_control_sha_mismatch_and_missing_letters(fonts, tmp_path):
    copy = tmp_path / "chewy.ttf"
    shutil.copy(fonts["chewy"], copy)
    result = qa_font(copy, script="AR", roles=["title"], expected_sha256="0" * 64)
    assert result["status"] == "rejected"
    assert {"file_sha256_mismatch", "arabic_base_missing", "names_notdef"} <= _ids(result)


def test_collision_counter_separates_contact_from_overlap():
    square = np.ones((10, 10), dtype=bool)
    base = (GlyphMask(square, 0, 10), 0, 10, False)
    touching = (GlyphMask(square.copy(), 0, 20), 0, 20, True)       # sits right on top: contact only
    overlapping = (GlyphMask(square.copy(), 0, 15), 0, 15, True)    # half inside the base
    assert _line_collisions([base, touching])["mark_base"] == 0
    assert _line_collisions([base, overlapping])["mark_base"] == 1
    other_mark = (GlyphMask(square.copy(), 3, 16), 3, 16, True)
    assert _line_collisions([base, overlapping, other_mark])["mark_mark"] == 2


def test_spacing_is_raised_for_tall_ink(fonts):
    facts = harakat_and_spacing(fonts["amiri"], load_harakat_corpus()["lines_ar"][:4])
    assert facts["min_safe_line_spacing"] >= 1.0 and facts["lines"] == 4
    assert facts["ink_ascent_em"] > 0 and facts["ink_descent_em"] > 0


def test_committed_qa_status(committed):
    qa = committed["qa_status"]
    assert qa["counts"]["certified_print"] + qa["counts"]["screen_only"] + qa["counts"]["rejected"] == 214
    by = {f["family"]: f for f in qa["families"]}
    assert {f for f, e in by.items() if e["status"] == "screen_only"} == {
        "Cairo Play", "Reem Kufi Fun", "Blaka Ink", "Reem Kufi Ink", "Aref Ruqaa Ink", "Bungee Spice", "Honk", "Nabla"}
    ids = lambda fam: {r["finding"] for r in by[fam]["reasons"]}  # noqa: E731
    for fam in ("Thabit", "Ruwudu", "Alkalami"):
        assert "no_gpos_mkmk" in ids(fam)
    for fam in ("Blaka", "Blaka Hollow", "Blaka Ink", "Gulzar"):
        assert "no_tatweel" in ids(fam)
    assert "monospace_arabic" in ids("Thabit") and "monospace_arabic" not in ids("Reem Kufi")
    assert by["Zain"]["facts"]["digits"]["identical_outlines"] == list("0123456789")
    assert by["Zain"]["facts"]["digits"]["look_western"] == list("023456789")  # «١» = «1» is normal design
    assert "arabic_indic_digits_look_western" in ids("Zain")
    assert "fsType_editable_embedding" in ids("Frijole")
    assert all(f["on_device_export_proof"]["status"] == "pending" for f in qa["families"])
    assert len(qa["families"]) == 214


def test_committed_qa_entries_are_reproducible_from_the_module(committed, fonts, catalog):
    """The fixture Tajawal/Amiri are the pinned-commit files, so a fresh QA run must equal what is committed."""
    from mxstudio.fonts.qa import pick_test_file
    by = {f["family"]: f for f in committed["qa_status"]["families"]}
    for family, key in (("Tajawal", "tajawal"), ("Amiri", "amiri")):
        fam = catalog.by_family(family)
        tested = pick_test_file(fam)
        assert by[family]["tested_file"] == fonts[key].name and tested["sha256"] == by[family]["facts"]["file_sha256"]
        fresh = qa_font(fonts[key], script="AR", roles=fam["roles"], expected_sha256=tested["sha256"])
        committed_entry = {k: v for k, v in by[family].items()
                           if k not in ("id", "family", "script", "tested_file", "tested_variable_default")}
        assert fresh == committed_entry
