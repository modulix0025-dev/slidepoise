"""Fixtures for the Integration Kit suites: Arabic-named replica estates, an isolated Kit home,
small stand-in mxlibs (manifested like the real ones) and a child-process runner for
behaviour checks of patched operator modules."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "replicas"))

from build_replica import build

STANDIN_TEXTFIT = '''"""Stand-in mx_textfit (tests only): a crude char-grid measure with the M4 signature."""
def fit(text, box_emu, font, rules=None):
    w, h = box_emu
    size = float(font.get("size_pt") or 18)
    per_line = max(1, int((w / 12700) / (size * 0.5)))
    lines = sum(max(1, -(-len(p) // per_line)) for p in text.split("\\n"))
    fits = lines * size * 1.2 <= h / 12700
    return {"fits": fits, "verdict": "fits" if fits else "does_not_fit", "lines": lines,
            "ar": "النص أطول من المكان" if not fits else "تمام", "en": "overflow" if not fits else "fits"}
'''

STANDIN_PREFLIGHT2 = '''"""Stand-in mx_preflight2 (tests only)."""
def run(pdf_path, profile=None):
    profile = dict(profile or {})
    ok = float(profile.get("bleed_mm", 0)) == 0.0
    return {"ok": ok, "warnings": [], "checks": [
        {"id": "bleed", "ok": ok, "ar": "النزيف", "en": "bleed", "detail": {"profile_size": profile.get("size")}}]}
'''


def _lib(base: Path, name: str, source: str) -> None:
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "__init__.py").write_text(source, encoding="utf-8")
    files = {"__init__.py": hashlib.sha256((d / "__init__.py").read_bytes()).hexdigest()}
    (d / "MANIFEST.json").write_text(json.dumps({"lib": name, "version": "0.0.0-standin", "files": files}),
                                     encoding="utf-8")


@pytest.fixture()
def standin_libs(tmp_path, monkeypatch):
    base = tmp_path / "mxlibs_standin"
    _lib(base, "mx_textfit", STANDIN_TEXTFIT)
    _lib(base, "mx_preflight2", STANDIN_PREFLIGHT2)
    monkeypatch.setenv("MXS_MXLIBS_DIR", str(base))
    return base


@pytest.fixture()
def kit_home(tmp_path, monkeypatch):
    home = tmp_path / "kit_home"
    monkeypatch.setenv("MXS_KIT_HOME", str(home))
    monkeypatch.setenv("MXS_HOME", str(tmp_path / "mxs_home"))
    return home


@pytest.fixture()
def replica(tmp_path, kit_home, standin_libs):
    """Factory: build(mutate=...) under a fresh «المشروع» folder; returns the facts dict."""
    count = {"n": 0}

    def _make(mutate=frozenset(), **kw):
        count["n"] += 1
        root = tmp_path / f"r{count['n']}" / "المشروع"
        return build(root, set(mutate), **kw)

    return _make
