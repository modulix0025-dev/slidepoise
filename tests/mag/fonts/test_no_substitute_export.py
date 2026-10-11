"""No substitute font in any theme's PDF (phase 16, item 9).

The vault installs Office-safe static builds instead of variable files (a variable font shows only its default
instance — «Marhey Light» — so the deck's «Marhey» was substituted), and the export check reads the fonts that are
really in the PDF: a deck typeface replaced by Microsoft JhengHei / Calibri / DejaVu is a named finding.

Rendered proof (Linux CI): one deck with a line in every font of every one of the 33 themes, exported by LibreOffice
with ONLY the install-shaped vault visible → the PDF lists each theme family and nothing else. The same check runs on
every factory build (finding ``font_substituted``); with PowerPoint it is an on-device proof (Proof Runner).
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from mxstudio.validators.pdf_fonts import substitutions

ROOT = Path(__file__).resolve().parents[3]
TEST_FONTS = Path(os.environ.get("MXS_TEST_FONTS") or ROOT / "workspace" / "test-fonts")
CAT = ROOT / "catalog" / "fonts"


def _themes():
    return json.loads((CAT / "type_themes.json").read_text(encoding="utf-8"))["themes"]


def _theme_families() -> list[str]:
    return sorted({v for t in _themes() for k, v in t.items() if k.startswith(("ar_", "en_")) and isinstance(v, str)})


def test_substitutes_are_named_and_renamed_builds_match():
    clean = substitutions({"Tajawal", "Nunito"}, {"Tajawal-Bold", "Tajawal-Regular", "Nunito-Regular"})
    assert clean["ok"]
    swapped = substitutions({"Tajawal", "Nunito"}, {"MicrosoftJhengHei", "Calibri", "Nunito-Regular"})
    assert not swapped["ok"] and swapped["missing"] == ["Tajawal"] and swapped["unexpected"] == ["Calibri",
                                                                                               "MicrosoftJhengHei"]
    renamed = substitutions({"Fredoka"}, {"MXKidsFredoka-Regular"}, {"Fredoka": "MX Kids Fredoka"})
    assert renamed["ok"]
    assert not substitutions({"Baloo 2"}, {"DejaVuSans"})["ok"]


def test_vault_installs_office_builds_instead_of_the_variable_files(tmp_path):
    """build_tree's office step: statics built from the pinned VF, sha-checked; the VF is never installed."""
    from mxstudio.update import assets
    plans = [p for p in json.loads((CAT / "office_builds.json").read_text("utf-8"))["families"]
             if p.get("source") == "office_build" and p["family"] == "Marhey"]
    catalog = {f["id"]: f for f in json.loads((CAT / "catalog.json").read_text("utf-8"))["families"]}
    plan = plans[0]
    source = TEST_FONTS / plan["from_file"]
    if not source.is_file():
        pytest.skip("run `python tools/fetch_test_fonts.py --all`")
    vault = tmp_path / "fonts"
    rel = f"{catalog[plan['id']]['repo_dir']}/{plan['from_file']}"
    (vault / rel).parent.mkdir(parents=True)
    shutil.copyfile(source, vault / rel)
    files = [{"path": rel, "sha256": "x", "licence": "OFL-1.1", "family": "Marhey"}]
    added = assets.office_builds(vault, files)
    assert [Path(a["path"]).name for a in added] == [f["file"] for f in plan["files"]]
    assert files[0]["superseded_by"] == f"office/{plan['id']}"
    (vault / "MANIFEST.json").write_text(json.dumps({"files": files + added}), encoding="utf-8")
    installable = [p.name for p in assets.font_files([vault])]
    assert plan["from_file"] not in installable and "Marhey-Regular.ttf" in installable
    from mxstudio.fonts.install import MemoryBackend
    backend = MemoryBackend(tmp_path / "win")
    backend.registry["user"]["Marhey Light (TrueType)"] = str(tmp_path / "old" / plan["from_file"])  # older install
    result = assets.install_vault_fonts(assets.font_files([vault]), backend=backend,
                                        superseded_names=assets.superseded_files([vault]))
    assert result["ok"] and result["retired_variable"] == ["Marhey Light (TrueType)"]
    assert not any("Light" in name for name in backend.registry["user"])


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from install_vault import files_present, install_shaped_vault  # noqa: E402


def _all_present() -> bool:
    return files_present(_theme_families())


@pytest.mark.skipif(not (shutil.which("soffice") and shutil.which("node") and (ROOT / "node_modules" / "pptxgenjs").is_dir()),
                    reason="LibreOffice + Node + pptxgenjs are needed for the rendered proof")
def test_every_theme_font_reaches_the_pdf_without_a_substitute(tmp_path):
    if not _all_present():
        pytest.skip("run `python tools/fetch_test_fonts.py --all` (pinned google/fonts files)")
    from mxstudio.factory.validate import _pptx_to_pdf
    from mxstudio.fonts.office_build import deck_family
    from mxstudio.validators.pdf_fonts import check_pdf, pdf_font_names
    from mxstudio.validators.synthetic_story import render
    from slidepoise.print_geometry import PageSpec

    vault = install_shaped_vault(tmp_path / "installed")
    conf = tmp_path / "fonts.conf"  # ONLY the installed vault (+ the system's own fallbacks, which must not appear)
    conf.write_text('<?xml version="1.0"?><fontconfig><include ignore_missing="yes">/etc/fonts/fonts.conf</include>'
                    f"<dir>{vault}</dir><cachedir>{tmp_path / 'fc'}</cachedir></fontconfig>", encoding="utf-8")
    os.environ["FONTCONFIG_FILE"] = str(conf)
    os.environ["MODULEX_SOFFICE"] = shutil.which("soffice")
    page = PageSpec.preset("A4", bleed_mm=3, safe_mm=5, dpi=300)
    w, h = page.canvas_px
    slides = []
    for number, theme in enumerate(_themes(), 1):
        roles = [k for k in ("ar_title", "ar_body", "ar_name", "ar_dedication", "ar_body_vowelized", "en_title",
                             "en_body") if theme.get(k)]
        objects = []
        for row, role in enumerate(roles):
            arabic = role.startswith("ar_")
            objects.append({"id": f"p{number}_{role}", "kind": "textbox", "z": 1,
                            "bbox_px": [150, 150 + row * 480, w - 300, 420],
                            "runs": [{"text": f"{theme['name_ar']} جيداء" if arabic else f"{theme['name_en']} Gaidaa"}],
                            "style": {"font_family": deck_family(theme[role]), "font_size_pt": 26, "color": "#111111",
                                      "direction": "rtl" if arabic else "ltr", "lang": "ar-EG" if arabic else "en-US",
                                      "alignment": "center", "vertical_alignment": "middle"}})
        slides.append({"id": f"p{number}", "dimensions_px": [w, h], "background": "#FFFFFF", "objects": objects})
    deck = tmp_path / "themes.pptx"
    render({"title": "themes", "language": "ar-EG", "slides": slides}, deck, python=sys.executable)
    pdf = tmp_path / "themes.pdf"
    _pptx_to_pdf().convert(deck, pdf, expect_pages=len(slides), engines=["soffice"])
    result = check_pdf(pdf, {deck_family(f) for f in _theme_families()})
    assert result["ok"], {k: result[k] for k in ("missing", "unexpected")}
    assert len(pdf_font_names(pdf)) >= len(_theme_families())

    # negative control: the raw variable Marhey alone (what the old vault installed) is NOT the deck's «Marhey»
    raw = tmp_path / "raw"
    raw.mkdir()
    shutil.copyfile(TEST_FONTS / "Marhey[wght].ttf", raw / "Marhey[wght].ttf")
    conf.write_text('<?xml version="1.0"?><fontconfig><include ignore_missing="yes">/etc/fonts/fonts.conf</include>'
                    f"<dir>{raw}</dir><cachedir>{tmp_path / 'fc2'}</cachedir></fontconfig>", encoding="utf-8")
    one = {"title": "m", "language": "ar-EG", "slides": [{"id": "p1", "dimensions_px": [w, h], "background": "#FFFFFF",
           "objects": [{"id": "t", "kind": "textbox", "z": 1, "bbox_px": [150, 150, w - 300, 420],
                        "runs": [{"text": "جيداء"}], "style": {"font_family": "Lemonada", "font_size_pt": 26,
                                                              "direction": "rtl", "lang": "ar-EG", "color": "#111111"}}]}]}
    render(one, tmp_path / "one.pptx", python=sys.executable)
    _pptx_to_pdf().convert(tmp_path / "one.pptx", tmp_path / "one.pdf", expect_pages=1, engines=["soffice"])
    assert not check_pdf(tmp_path / "one.pdf", {"Lemonada"})["ok"]  # Lemonada is not installed there: substituted
