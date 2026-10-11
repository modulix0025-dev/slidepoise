"""Operator decision 2026-10-11: no commercially-licensed component may ship.

Scans every file the Studio ships or builds from (dependency manifests, installer
scripts, Studio code, catalogs) for the banned components in
catalog/licence_policy.json. Documentation is excluded: it must be able to *name*
what was replaced.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POLICY = json.loads((ROOT / "catalog" / "licence_policy.json").read_text(encoding="utf-8"))
SHIPPED = ["pyproject.toml", "setup.py", "package.json", "package-lock.json", "installer", "mxstudio", "mxlibs",
           "catalog", "contracts", "vendor", ".github/workflows"]
EXCLUDED_FILES = {ROOT / "catalog" / "licence_policy.json"}
TEXT_SUFFIXES = {".py", ".toml", ".json", ".nsi", ".nsh", ".iss", ".yml", ".yaml", ".js", ".mjs", ".cfg", ".txt",
                 ".spec", ".ps1", ".bat", ".cmd", ".tsv", ".csv"}


def _shipped_files():
    for entry in SHIPPED:
        path = ROOT / entry
        if path.is_file():
            yield path
        elif path.is_dir():
            yield from (p for p in path.rglob("*") if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES
                        and "__pycache__" not in p.parts)


def find_banned(text: str) -> list[str]:
    low = text.lower()
    return [c["id"] for c in POLICY["banned_components"] if any(pat in low for pat in c["patterns"])]


def test_no_banned_component_in_shipped_files():
    hits = {}
    for path in _shipped_files():
        if path in EXCLUDED_FILES:
            continue
        found = find_banned(path.read_text(encoding="utf-8", errors="replace"))
        if found:
            hits[str(path.relative_to(ROOT))] = found
    assert hits == {}, f"commercially-licensed components found: {hits}"


def test_every_banned_component_names_a_free_replacement():
    for comp in POLICY["banned_components"]:
        assert comp["replacement"].strip() and comp["reason"].strip() and comp["patterns"]


def test_allow_and_refuse_lists_are_disjoint():
    allow = set(POLICY["print_asset_allowlist"])
    assert not allow & set(POLICY["print_asset_refused"])
    assert not allow & set(POLICY["print_asset_pending_operator"])
    assert set(POLICY["print_asset_requires_credits"]) <= allow


def test_negative_control_detects_each_banned_component():
    samples = {
        "ghostscript": 'subprocess.run(["gswin64c", "-sDEVICE=pdfwrite"])',
        "mupdf": "import fitz  # PyMuPDF",
        "inno-setup": "[Setup]\nAppId={{X}}",
        "wix-6plus": '<PackageReference Include="WixToolset.Sdk" />',
        "flux-dev": '{"ckpt_name": "flux1-kontext-dev-fp8.safetensors"}',
        "paid-search": "https://api.search.brave.com/res/v1/web/search",
        "remixicon-4.9+": "npm install remixicon@4.9.1",
    }
    assert set(samples) == {c["id"] for c in POLICY["banned_components"]}
    for comp_id, sample in samples.items():
        assert comp_id in find_banned(sample), comp_id
    assert find_banned("pikepdf + pypdfium2 + NSIS + Qwen-Image-Edit-2511") == []
