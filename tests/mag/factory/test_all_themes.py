"""A real story with the name «جيداء» builds green in every type theme (phase 16, acceptance 7).

Each theme: factory build_and_validate (8 variants: ar/en × boy/girl × A4/A5; the girl's sample name is «جيداء»),
LibreOffice export, every validator — text_proof (hamza names, fragmented extraction), long_name, fonts,
font_substituted — with only the install-shaped vault visible (Office builds, RFN-renamed families).
Default: four themes that cover the fonts that failed before; MXS_ALL_THEMES=1 runs all 33 (mag-ci does).
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from install_vault import files_present, install_shaped_vault, theme_families  # noqa: E402

THEMES = [t["id"] for t in json.loads((ROOT / "catalog" / "fonts" / "type_themes.json").read_text("utf-8"))["themes"]]
REPRESENTATIVE = ["adventure", "comics", "detectives", "egyptian_heritage"]
SELECTED = THEMES if os.environ.get("MXS_ALL_THEMES") == "1" else REPRESENTATIVE
ready = pytest.mark.skipif(not (shutil.which("soffice") and shutil.which("node")
                                and (ROOT / "node_modules" / "pptxgenjs").is_dir() and files_present(theme_families())),
                           reason="needs LibreOffice, Node, pptxgenjs and `python tools/fetch_test_fonts.py --all`")


@pytest.fixture(scope="module")
def installed(tmp_path_factory):
    base = tmp_path_factory.mktemp("vault")
    vault = install_shaped_vault(base / "installed")
    conf = base / "fonts.conf"
    conf.write_text('<?xml version="1.0"?><fontconfig><include ignore_missing="yes">/etc/fonts/fonts.conf</include>'
                    f"<dir>{vault}</dir><cachedir>{base / 'fc'}</cachedir></fontconfig>", encoding="utf-8")
    os.environ["FONTCONFIG_FILE"] = str(conf)
    os.environ["MODULEX_SOFFICE"] = shutil.which("soffice") or ""
    from slidepoise.arabic.fonts import FontRegistry
    return FontRegistry(directories=[vault])


@ready
@pytest.mark.parametrize("theme_id", SELECTED)
def test_story_named_gaidaa_is_green_in_the_theme(theme_id, installed, tmp_path):
    from mxstudio.factory.api import resolve_theme
    from mxstudio.factory.demo_story import moon_star_story
    from mxstudio.factory.service import build_and_validate
    story = moon_star_story()
    assert story.base_names["ar_girl"] == "جيداء"
    theme = resolve_theme({"type_theme": theme_id}, registry=installed)
    result = build_and_validate(story, tmp_path, registry=installed, engines=["soffice"], theme=theme)
    bad = {k: [f["code"] for f in v["findings"]] for k, v in result["validation"]["variants"].items() if not v["ok"]}
    assert result["validation"]["ok"], bad
    girl = result["validation"]["variants"]["ar_girl_A4"]["facts"]
    assert girl["text_proof"]["ok"] and girl["pdf_fonts"]["ok"]
