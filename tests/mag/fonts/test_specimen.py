"""Specimen book: PPTX built from the catalog DB, exported by the vendored converter, embedding + text proven."""
from __future__ import annotations

from pptx import Presentation

from mxstudio.fonts.specimen import (SpecimenFamily, SpecimenTheme, build_specimen, embedding_proof,
                                     export_specimen, specimen_inputs)

THEME = SpecimenTheme(id="t", name_ar="مرح كلاسيكي", name_en="Classic fun",
                      fonts={"ar_title": "Tajawal", "ar_body": "Amiri", "ar_body_vowelized": "Tajawal",
                             "ar_name": "Tajawal", "ar_dedication": "Tajawal", "en_title": "Chewy",
                             "en_body": "Chewy"})


def test_inputs_come_from_the_catalog_db(committed, catalog):
    families, themes = specimen_inputs(catalog, committed["qa_status"], committed["office_builds"],
                                       committed["type_themes"])
    assert len(families) == committed["qa_status"]["counts"]["certified_print"]
    assert len(themes) == len(committed["type_themes"]["themes"])
    readex = next(f for f in families if f.family == "Readex Pro")
    assert readex.install_name == "MX Kids F033 Readex Pro"
    assert all(f.status == "certified_print" for f in families)


def test_three_page_specimen_from_fixture_fonts(tmp_path, soffice_exe, all_fixture_fontconfig, monkeypatch):
    monkeypatch.setenv("FONTCONFIG_FILE", str(all_fixture_fontconfig))
    monkeypatch.setenv("MODULEX_SOFFICE", soffice_exe)
    families = [SpecimenFamily("Tajawal", "Tajawal", "AR"), SpecimenFamily("Chewy", "Chewy", "EN")]
    pptx, pages = build_specimen(tmp_path / "specimen.pptx", families, [THEME])
    assert len(Presentation(pptx).slides) == 3 and len(pages) == 3
    result = export_specimen(pptx, tmp_path / "specimen.pdf", pages, ["Tajawal", "Chewy", "Amiri"],
                             engines=["soffice"], timeout=300)
    assert result["export"]["pages"] == 3 and result["export"]["has_text"]
    assert result["embedding"]["missing"] == []
    assert result["multiset_ok_pages"] == 3
    assert result["pages"][1]["ok"]  # the Latin page passes the strict proof too
    # negative control: a font that is not in the PDF is reported missing, by name
    assert embedding_proof(tmp_path / "specimen.pdf", ["Lalezar"])["missing"] == ["Lalezar"]
