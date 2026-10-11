"""Write (or check) MANIFEST.json for every vendorable library under mxlibs/.

Rule enforced: a library is vendored into the operator's OrderManagement
system byte-for-byte. Each MANIFEST.json lists every file of the library with
its sha256, so the Kit can verify a vendored copy with ``verify_manifest``
(stdlib only) before enabling it. The manifest is deterministic (no
timestamps), so ``--check`` fails whenever a file changed without a rebuild.

Usage:
    python mxlibs/build_manifests.py [lib ...]           # rewrite MANIFEST.json (all mx_* libs, or the named ones)
    python mxlibs/build_manifests.py --check [lib ...]   # exit 1 if any manifest is missing or stale
    python mxlibs/build_manifests.py --verify <vendored_lib_dir>

Each library's owner rebuilds its own manifest (name it explicitly when other
owners' libraries are in progress) and adds its entry to ``DEPENDENCIES``.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFEST = "MANIFEST.json"
SKIP_DIRS = {"__pycache__", ".pytest_cache"}
SKIP_SUFFIXES = {".pyc", ".pyo"}

#: Declared runtime dependencies per library (import names). "optional" ones degrade gracefully.
DEPENDENCIES = {
    "mx_textfit": {"requires": ["Pillow"], "optional": ["uharfbuzz", "fontTools"]},
    "mx_preflight2": {"requires": ["pikepdf", "pypdfium2", "numpy", "Pillow"], "optional": []},
    "mx_impose": {"requires": ["pikepdf", "pypdfium2", "numpy", "Pillow"], "optional": []},
    "mx_qagate": {"requires": [], "optional": ["pypdfium2", "numpy", "mx_textfit"]},
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def lib_files(lib_dir: Path) -> list[Path]:
    files = []
    for path in sorted(lib_dir.rglob("*")):
        if not path.is_file() or path.name == MANIFEST or path.suffix in SKIP_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(lib_dir).parts):
            continue
        files.append(path)
    return files


def _version(lib_dir: Path) -> str:
    match = re.search(
        r'^__version__\s*=\s*"([^"]+)"', (lib_dir / "__init__.py").read_text(encoding="utf-8"), re.MULTILINE
    )
    return match.group(1) if match else "0"


def build_manifest(lib_dir: Path) -> dict:
    lib_dir = Path(lib_dir)
    files = {path.relative_to(lib_dir).as_posix(): _sha256(path) for path in lib_files(lib_dir)}
    deps = DEPENDENCIES.get(lib_dir.name, {"requires": [], "optional": []})
    return {
        "lib": lib_dir.name,
        "version": _version(lib_dir),
        "python": ">=3.10",
        **deps,
        "vendoring": "copy bytes verbatim (no line-ending conversion); verify with verify_manifest()",
        "files": files,
    }


def _dump(manifest: dict) -> str:
    return json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def libraries(root: Path = HERE, names: list[str] | None = None) -> list[Path]:
    found = sorted(
        p for p in root.iterdir() if p.is_dir() and p.name.startswith("mx_") and (p / "__init__.py").is_file()
    )
    if names:
        unknown = set(names) - {p.name for p in found}
        if unknown:
            raise ValueError(f"unknown libraries: {sorted(unknown)}")
        found = [p for p in found if p.name in names]
    return found


def write_all(root: Path = HERE, names: list[str] | None = None) -> list[Path]:
    written = []
    for lib in libraries(root, names):
        target = lib / MANIFEST
        target.write_text(_dump(build_manifest(lib)), encoding="utf-8", newline="\n")
        written.append(target)
    return written


def check_all(root: Path = HERE, names: list[str] | None = None) -> list[str]:
    """Names of libraries whose MANIFEST.json is missing or stale."""
    stale = []
    for lib in libraries(root, names):
        target = lib / MANIFEST
        if not target.is_file() or target.read_text(encoding="utf-8") != _dump(build_manifest(lib)):
            stale.append(lib.name)
    return stale


def verify_manifest(lib_dir) -> dict:
    """Verify a (vendored) library directory against its MANIFEST.json. Stdlib only, never raises on mismatch."""
    lib_dir = Path(lib_dir)
    try:
        manifest = json.loads((lib_dir / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"ok": False, "error": f"manifest unreadable: {exc}", "mismatched": [], "missing": [], "extra": []}
    expected = manifest.get("files", {})
    mismatched, missing = [], []
    for rel, digest in sorted(expected.items()):
        path = lib_dir / rel
        if not path.is_file():
            missing.append(rel)
        elif _sha256(path) != digest:
            mismatched.append(rel)
    present = {p.relative_to(lib_dir).as_posix() for p in lib_files(lib_dir)}
    extra = sorted(present - set(expected))
    return {
        "ok": not (mismatched or missing or extra),
        "lib": manifest.get("lib"),
        "version": manifest.get("version"),
        "mismatched": mismatched,
        "missing": missing,
        "extra": extra,
    }


def main(argv: list[str]) -> int:
    if argv[:1] == ["--check"]:
        stale = check_all(names=argv[1:] or None)
        print(json.dumps({"ok": not stale, "stale": stale}))
        return 1 if stale else 0
    if argv[:1] == ["--verify"] and len(argv) == 2:
        result = verify_manifest(argv[1])
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["ok"] else 1
    for path in write_all(names=argv or None):
        print(path.relative_to(HERE.parent).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
