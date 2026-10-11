"""Catalog DB: pinned, complete, every file hashed and URL-pinned; builder re-derives facts and refuses drift."""
from __future__ import annotations

import copy
import shutil

import pytest

from mxstudio.fonts.build_catalog import CatalogBuildError, build_catalog, parse_metadata_pb
from mxstudio.fonts.catalog import validate_catalog
from mxstudio.fonts.paths import PINNED_COMMIT, raw_url
from mxstudio.fonts.rfn import parse_reserved_font_names, renamed_family, rfn_conflicts

COLOUR = {"Cairo Play", "Reem Kufi Fun", "Blaka Ink", "Reem Kufi Ink", "Aref Ruqaa Ink", "Bungee Spice", "Honk", "Nabla"}


def test_committed_catalog_is_valid_and_pinned(committed):
    data = committed["catalog"]
    assert validate_catalog(data) == []
    assert data["source"]["commit"] == PINNED_COMMIT
    counts = data["counts"]
    assert (counts["families"], counts["arabic"], counts["latin"]) == (214, 54, 160)
    assert (counts["ofl"], counts["apache"], counts["files"]) == (197, 17, 311)
    assert counts["fsType_nonzero"] == ["Frijole"]
    assert {f["family"] for f in data["families"] if f["is_colour"]} == COLOUR


def test_raw_urls_percent_encode_brackets():
    url = raw_url("ofl/nabla", "Nabla[EDPT,EHLT].ttf")
    assert url == (f"https://raw.githubusercontent.com/google/fonts/{PINNED_COMMIT}/ofl/nabla/"
                   "Nabla%5BEDPT%2CEHLT%5D.ttf")


def test_rfn_parser_reads_only_the_header():
    text = ("Copyright 2023 The Varela Round Project Authors, with Reserved Font Names 'Varela' and ‘Varela "
            "Round’.\n\nThis Font Software is licensed under the SIL Open Font License, Version 1.1.\n"
            "\"Reserved Font Name\" refers to any names specified as such after the copyright statement(s).")
    assert parse_reserved_font_names(text) == ["Varela", "Varela Round"]
    assert parse_reserved_font_names("Copyright 2015, with Reserved Font Name EURM10.\n\nThis Font Software is "
                                     "licensed") == ["EURM10"]
    assert parse_reserved_font_names("Copyright 2010 The Amiri Project Authors.\n\nThis Font Software is licensed "
                                     "... \"Reserved Font Name\" refers to") == []


def test_varela_round_rfn_corrects_phase0(committed):
    fam = next(f for f in committed["catalog"]["families"] if f["family"] == "Varela Round")
    assert fam["reserved_font_names"] == ["Varela", "Varela Round"]
    assert any(d["field"] == "reserved_font_names" for d in fam["drift"])


def test_renamed_family_never_contains_an_rfn():
    assert renamed_family("F056", "Lexend", ["RevReading Lexend"]) == "MX Kids F056"
    assert renamed_family("F019", "Reem Kufi", ["Josefin Sans"]) == "MX Kids F019 Reem Kufi"
    name = renamed_family("F037", "IBM Plex Sans Arabic", ["Plex"])
    assert not rfn_conflicts(name, ["Plex"]) and name.startswith("MX Kids F037")
    assert rfn_conflicts("MXKidsF037IBMPlexSans-Bold", ["Plex"]) == ["Plex"]


def test_metadata_pb_parser_handles_escapes():
    meta = parse_metadata_pb('name: "Caf\\303\\251"\nlicense: "OFL"\nsubsets: "arabic"\nsubsets: "latin"\n'
                             'fonts {\n  name: "X"\n  filename: "X[wght].ttf"\n}\n')
    assert meta["name"] == "Café" and meta["subsets"] == ["arabic", "latin"]
    assert meta["fonts"][0]["filename"] == "X[wght].ttf"


@pytest.fixture()
def tiny_checkout(tmp_path, fonts):
    root = tmp_path / "gfonts"
    (root / ".git").mkdir(parents=True)
    (root / ".git" / "HEAD").write_text(PINNED_COMMIT + "\n", encoding="utf-8")
    folder = root / "ofl" / "reemkufi"
    folder.mkdir(parents=True)
    shutil.copy(fonts["reemkufi"], folder)
    shutil.copy(fonts["reemkufi"].parent / "OFL.txt", folder)
    (folder / "METADATA.pb").write_text('name: "Reem Kufi"\ndesigner: "Khaled Hosny"\nlicense: "OFL"\n'
                                        'category: "SANS_SERIF"\nsubsets: "arabic"\n', encoding="utf-8")
    tsv = tmp_path / "appendix.tsv"
    tsv.write_text("id\tfamily\tscript\trepo_dir\troles\tthemes\tlicence\tflags\tobservation\n"
                   "F019\tReem Kufi\tAR\tofl/reemkufi\ttitle\theritage\tOFL\tVAR RFN\t\n", encoding="utf-8")
    return root, tsv


def test_builder_rederives_facts_from_a_checkout(tiny_checkout):
    root, tsv = tiny_checkout
    data = build_catalog(root, tsv=tsv, measured_path=None)
    fam = data["families"][0]
    assert fam["reserved_font_names"] == ["Josefin Sans"] and fam["flags"] == ["RFN", "VAR"]
    assert fam["files"][0]["axes"]["wght"] == [400.0, 400.0, 700.0]
    assert fam["files"][0]["url"].endswith("ReemKufi%5Bwght%5D.ttf")
    assert fam["drift"] == []
    assert build_catalog(root, tsv=tsv, measured_path=None) == data  # deterministic


def test_negative_control_builder_refuses_other_commit(tiny_checkout):
    root, tsv = tiny_checkout
    (root / ".git" / "HEAD").write_text("0" * 40, encoding="utf-8")
    with pytest.raises(CatalogBuildError, match="pinned"):
        build_catalog(root, tsv=tsv, measured_path=None)


def test_negative_control_builder_refuses_missing_licence(tiny_checkout):
    root, tsv = tiny_checkout
    (root / "ofl" / "reemkufi" / "OFL.txt").unlink()
    with pytest.raises(CatalogBuildError, match="licence file missing"):
        build_catalog(root, tsv=tsv, measured_path=None)


def test_negative_control_builder_records_flag_drift(tiny_checkout):
    root, tsv = tiny_checkout
    tsv.write_text(tsv.read_text(encoding="utf-8").replace("VAR RFN", "VAR"), encoding="utf-8")
    fam = build_catalog(root, tsv=tsv, measured_path=None)["families"][0]
    assert {"field": "flags", "appendix": ["VAR"], "measured": ["RFN", "VAR"]} in fam["drift"]


def test_negative_control_validator_catches_tampering(committed):
    data = copy.deepcopy(committed["catalog"])
    removed = data["families"].pop(3)
    data["families"][0]["files"][0]["url"] = data["families"][0]["files"][0]["url"].replace(PINNED_COMMIT, "main")
    data["families"][1]["licence"] = "CC-BY-SA-4.0"
    data["families"][2]["flags"] = []
    found = {f.finding for f in validate_catalog(data)}
    assert {"catalog_family_missing", "catalog_file_url_not_pinned", "catalog_licence_not_allowed"} <= found
    assert removed["family"] == "Cairo Play"
    assert "catalog_colour_flag_wrong" in found or "catalog_variable_flag_wrong" in found
