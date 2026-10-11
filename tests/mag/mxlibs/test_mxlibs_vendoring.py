"""Every mxlib is self-contained and vendorable verbatim: allowed imports only, fresh MANIFEST.json, verify works."""

from __future__ import annotations

import ast
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
MXLIBS = ROOT / "mxlibs"
sys.path.insert(0, str(MXLIBS))
import build_manifests

LIBS = ["mx_textfit", "mx_preflight2", "mx_impose"]
THIRD_PARTY = {"pikepdf", "pypdfium2", "numpy", "PIL", "uharfbuzz", "fontTools"}
ALLOWED = set(sys.stdlib_module_names) | THIRD_PARTY


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
    return found


@pytest.mark.parametrize("lib", LIBS)
def test_lib_imports_only_stdlib_and_allowed_packages(lib):
    for path in (MXLIBS / lib).rglob("*.py"):
        bad = _imports(path) - ALLOWED
        assert not bad, f"{path.relative_to(ROOT)} imports {sorted(bad)}"


def test_negative_control_import_scan_catches_a_project_import(tmp_path):
    rogue = tmp_path / "rogue.py"
    rogue.write_text("from slidepoise.arabic import fit_text\nimport mxstudio\n", encoding="utf-8")
    assert _imports(rogue) - ALLOWED == {"slidepoise", "mxstudio"}


def test_manifests_are_current():
    assert build_manifests.check_all(names=LIBS) == [], "run: python mxlibs/build_manifests.py " + " ".join(LIBS)
    for lib in LIBS:
        result = build_manifests.verify_manifest(MXLIBS / lib)
        assert result["ok"], result
        assert result["version"] == "1.0.0"


def test_verify_detects_tampering(tmp_path):
    copy = tmp_path / "mx_textfit"
    shutil.copytree(MXLIBS / "mx_textfit", copy, ignore=shutil.ignore_patterns("__pycache__"))
    assert build_manifests.verify_manifest(copy)["ok"]
    target = copy / "fit.py"
    target.write_bytes(target.read_bytes().replace(b"\n", b"\r\n"))  # a CRLF checkout is a different file
    assert build_manifests.verify_manifest(copy)["mismatched"] == ["fit.py"]
    (copy / "extra.py").write_text("x = 1\n", encoding="utf-8")
    (copy / "measure.py").unlink()
    result = build_manifests.verify_manifest(copy)
    assert not result["ok"] and result["extra"] == ["extra.py"] and result["missing"] == ["measure.py"]


@pytest.mark.parametrize("lib", LIBS)
def test_vendored_copy_imports_under_another_parent(tmp_path, lib):
    """Copied verbatim into a foreign tree (e.g. OM app/vendor/), the package imports by itself."""
    vendor = tmp_path / "om_vendor"
    shutil.copytree(MXLIBS / lib, vendor / lib, ignore=shutil.ignore_patterns("__pycache__"))
    code = (
        f"import sys; sys.path.insert(0, {str(vendor)!r}); import {lib}; "
        f"assert {lib}.__file__.startswith({str(vendor)!r}); print({lib}.__version__)"
    )
    proc = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "1.0.0"


def test_check_cli_reports_stale(tmp_path):
    root = tmp_path / "mxlibs"
    shutil.copytree(MXLIBS, root, ignore=shutil.ignore_patterns("__pycache__"))
    build_manifests.write_all(root, LIBS)
    assert build_manifests.check_all(root, LIBS) == []
    (root / "mx_impose" / "saddle.py").write_text("# changed\n", encoding="utf-8")
    assert build_manifests.check_all(root, LIBS) == ["mx_impose"]
    with pytest.raises(ValueError):
        build_manifests.check_all(root, ["mx_nonexistent"])
