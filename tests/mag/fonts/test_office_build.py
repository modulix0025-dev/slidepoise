"""Office-safe builds: static instances, RIBBI name IDs, mandatory RFN rename, byte-for-byte determinism."""
from __future__ import annotations

import io

import pytest
from fontTools.ttLib import TTFont

from slidepoise.arabic.fonts import FontRegistry

from mxstudio.fonts.office_build import (RfnInModifiedName, RfnRenameRequired, build_family, build_instance,
                                         check_modified_names, plan_weights, style_names)
from mxstudio.fonts.rfn import rfn_conflicts

RFN = ["Josefin Sans"]


def _names(blob: bytes) -> dict[int, str]:
    font = TTFont(io.BytesIO(blob))
    return {i: str(font["name"].getName(i, 3, 1, 0x409)) for i in (1, 2, 4, 6, 16, 17)}


def test_reem_kufi_builds_renamed_regular_and_bold(fonts, tmp_path):
    built = build_family(fonts["reemkufi"], tmp_path, font_id="F019", family="Reem Kufi", rfns=RFN, roles=["title"])
    assert [(b.family, b.subfamily, b.weight) for b in built] == [
        ("MX Kids F019 Reem Kufi", "Regular", 400), ("MX Kids F019 Reem Kufi", "Bold", 700)]
    bold = TTFont(tmp_path / built[1].file)
    assert "fvar" not in bold and "gvar" not in bold and "STAT" not in bold
    assert bold["OS/2"].usWeightClass == 700 and bold["OS/2"].fsSelection & (1 << 5)
    assert bold["head"].macStyle & 1
    regular = TTFont(tmp_path / built[0].file)
    assert regular["OS/2"].fsSelection & (1 << 6) and not regular["OS/2"].fsSelection & (1 << 5)
    assert _names((tmp_path / built[1].file).read_bytes()) == {
        1: "MX Kids F019 Reem Kufi", 2: "Bold", 4: "MX Kids F019 Reem Kufi Bold", 6: "MXKidsF019ReemKufi-Bold",
        16: "MX Kids F019 Reem Kufi", 17: "Bold"}
    for record in bold["name"].names:
        if record.nameID in (1, 3, 4, 6, 16, 17):
            assert not rfn_conflicts(record.toUnicode(), RFN)
    registry = FontRegistry(directories=[tmp_path])
    assert registry.resolve("MX Kids F019 Reem Kufi", bold=True).subfamily == "Bold"
    assert registry.resolve("MX Kids F019 Reem Kufi").subfamily == "Regular"


def test_builds_are_deterministic(fonts):
    a, fa = build_instance(fonts["reemkufi"], font_id="F019", family="Reem Kufi", rfns=RFN, weight=700)
    b, fb = build_instance(fonts["reemkufi"], font_id="F019", family="Reem Kufi", rfns=RFN, weight=700)
    assert a == b and fa.sha256 == fb.sha256


def test_negative_control_rfn_build_without_rename_is_refused(fonts):
    with pytest.raises(RfnRenameRequired, match="Reserved Font Name"):
        build_instance(fonts["reemkufi"], font_id="F019", family="Reem Kufi", rfns=RFN, weight=400, rename=False)


def test_negative_control_modified_name_still_using_rfn_is_refused(fonts):
    blob, _ = build_instance(fonts["reemkufi"], font_id="F019", family="Reem Kufi", rfns=RFN, weight=400)
    font = TTFont(io.BytesIO(blob))
    font["name"].setName("Josefin Sans Kids Regular", 4, 3, 1, 0x409)
    with pytest.raises(RfnInModifiedName):
        check_modified_names(font, "Reem Kufi", RFN)
    font["name"].setName("Reem Kufi", 16, 3, 1, 0x409)
    with pytest.raises(RfnRenameRequired):
        check_modified_names(font, "Reem Kufi", RFN)


def test_no_rfn_keeps_the_family_name(fonts):
    _blob, built = build_instance(fonts["reemkufi"], font_id="F019", family="Reem Kufi", rfns=[], weight=400)
    assert built.family == "Reem Kufi"


def test_style_names_and_weight_plan():
    assert style_names("X", 800, False) == {1: "X ExtraBold", 2: "Regular", 4: "X ExtraBold", 16: "X",
                                            17: "ExtraBold"}
    assert style_names("X", 700, True)[2] == "Bold Italic"
    assert plan_weights((400, 400, 700), ["title"]) == [400, 700]
    assert plan_weights((400, 400, 800), ["title", "body"]) == [400, 700, 800]
    assert plan_weights((300, 400, 650), ["body"]) == [400, 600]
    assert plan_weights((100, 400, 900), ["effect"]) == [400, 800, 900]


def test_committed_office_builds_are_deterministic_and_rename_rfn(committed, catalog):
    report = committed["office_builds"]
    assert report["determinism"]["mismatched"] == [] and report["determinism"]["rebuilt_and_compared"] == 43
    for plan in report["families"]:
        fam = catalog.by_family(plan["family"])
        rfns = fam["reserved_font_names"]
        if plan["source"] == "office_build":
            assert plan["files"], plan["family"]
            assert plan["renamed"] == bool(rfns)
            for item in plan["files"]:
                assert not rfn_conflicts(item["family"], rfns) and not rfn_conflicts(item["postscript_name"], rfns)
                assert item["source_sha256"] == plan["from_sha256"]
        if plan["qa_status"] != "certified_print":
            assert plan["files"] == []
    assert {p["family"] for p in report["families"] if p["source"] == "none"} == {
        "Cairo Play", "Reem Kufi Fun", "Blaka Ink", "Reem Kufi Ink", "Aref Ruqaa Ink", "Bungee Spice", "Honk", "Nabla"}
