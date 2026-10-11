"""Shared fixtures for the ModuleX Magazine Studio suites."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for extra in (ROOT, ROOT / "slidepoise" / "runtime" / "src"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

FIXTURE_FONTS = Path(__file__).resolve().parent / "fixtures" / "fonts"


@pytest.fixture(scope="session")
def fixture_registry():
    from slidepoise.arabic.fonts import FontRegistry
    return FontRegistry(directories=[FIXTURE_FONTS])


@pytest.fixture(scope="session")
def fixture_fontconfig(tmp_path_factory):
    """A fontconfig that adds the fixture fonts, so LibreOffice embeds them instead of substituting."""
    base = tmp_path_factory.mktemp("fontconfig")
    conf = base / "fonts.conf"
    conf.write_text(
        '<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd"><fontconfig>'
        '<include ignore_missing="yes">/etc/fonts/fonts.conf</include>'
        f"<dir>{FIXTURE_FONTS}</dir><cachedir>{base / 'cache'}</cachedir></fontconfig>",
        encoding="utf-8")
    return conf


@pytest.fixture(scope="session")
def render_deck(tmp_path_factory):
    """Render a synthetic story spec with the forked renderer; cached per (variant, size)."""
    if not shutil.which("node"):
        pytest.skip("node is required to render PowerPoint decks")
    if not (ROOT / "node_modules" / "pptxgenjs").is_dir():
        pytest.skip("npm ci has not installed pptxgenjs")
    from mxstudio.validators.synthetic_story import build_spec, render

    out_dir = tmp_path_factory.mktemp("decks")
    cache: dict = {}

    def _render(variant: str = "ar_boy", size: str = "A5", spec: dict | None = None, name: str | None = None):
        key = name or f"{variant}_{size}"
        if key not in cache:
            spec = spec or build_spec(variant, size)
            cache[key] = (render(spec, out_dir / f"{key}.pptx", python=sys.executable), spec)
        return cache[key]

    return _render


@pytest.fixture(scope="session")
def soffice():
    exe = shutil.which("soffice") or shutil.which("libreoffice")
    if not exe:
        pytest.skip("LibreOffice is required for export proofs (installed in mag-ci)")
    return exe
