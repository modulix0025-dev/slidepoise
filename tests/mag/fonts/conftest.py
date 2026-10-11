"""Fixtures for the Phase 4 font suites. No network, no google/fonts checkout: only fixture fonts."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
FIX = HERE / "fixtures"
SHARED = HERE.parent / "fixtures" / "fonts"
ROOT = HERE.parents[2]

FONTS = {
    "tajawal": SHARED / "tajawal" / "Tajawal-Regular.ttf",
    "tajawal_bold": SHARED / "tajawal" / "Tajawal-Bold.ttf",
    "amiri": SHARED / "amiri" / "Amiri-Regular.ttf",
    "reemkufi": FIX / "reemkufi" / "ReemKufi[wght].ttf",
    "reemkufifun": FIX / "reemkufifun" / "ReemKufiFun[wght].ttf",
    "blaka": FIX / "blaka" / "Blaka-Regular.ttf",
    "thabit": FIX / "thabit" / "Thabit.ttf",
    "chewy": FIX / "chewy" / "Chewy-Regular.ttf",
}


@pytest.fixture(scope="session")
def fonts() -> dict[str, Path]:
    return dict(FONTS)


@pytest.fixture(scope="session")
def committed():
    """The committed catalog DB files."""
    base = ROOT / "catalog" / "fonts"
    load = lambda name: json.loads((base / name).read_text(encoding="utf-8"))  # noqa: E731
    return {name.split(".")[0]: load(name) for name in (
        "catalog.json", "font_license_ledger.json", "qa_status.json", "type_themes.json", "office_builds.json",
        "egyptian_names.json", "harakat_corpus.json")}


@pytest.fixture(scope="session")
def catalog():
    from mxstudio.fonts.catalog import load_catalog
    return load_catalog()


@pytest.fixture(scope="session")
def all_fixture_fontconfig(tmp_path_factory):
    """fontconfig with the shared and the Phase 4 fixture fonts, for LibreOffice exports."""
    base = tmp_path_factory.mktemp("fc_fonts")
    conf = base / "fonts.conf"
    conf.write_text('<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd"><fontconfig>'
                    '<include ignore_missing="yes">/etc/fonts/fonts.conf</include>'
                    f"<dir>{SHARED}</dir><dir>{FIX}</dir><cachedir>{base / 'cache'}</cachedir></fontconfig>",
                    encoding="utf-8")
    return conf


@pytest.fixture(scope="session")
def soffice_exe():
    exe = shutil.which("soffice") or shutil.which("libreoffice")
    if not exe:
        pytest.skip("LibreOffice is required for export proofs (installed in mag-ci)")
    return exe
