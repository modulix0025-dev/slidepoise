"""Load the two vendored operator contracts (byte-identical copies) after checking their sha256.

Rule: the Studio never re-implements `modulex_signing` or `pptx_to_pdf`; it imports the
vendored copy, and refuses to import it if its bytes differ from ``vendor/modulex/SHA256SUMS``.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from functools import cache
from pathlib import Path
from types import ModuleType

from ._util import sha256_file

PINNED = {
    "modulex_signing.py": "a2f1db607288413e6e631dca8f63e523e6916612d6ec97af55906dfe509d347e",
    "pptx_to_pdf.py": "2920eb32048e286604a60fe98229763f3932898b3c8150f08f3cd2b1539d7eee",
}


class VendorIntegrityError(RuntimeError):
    pass


def vendor_dir() -> Path:
    env = os.environ.get("MXS_VENDOR_DIR")
    if env:
        return Path(env)
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base / "vendor" / "modulex"


def load_module_from(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@cache
def _load(filename: str) -> ModuleType:
    path = vendor_dir() / filename
    digest = sha256_file(path)
    if digest != PINNED[filename]:
        raise VendorIntegrityError(f"vendored {filename} sha256 {digest} != pinned {PINNED[filename]}")
    return load_module_from(path, "mx_vendor_" + filename[:-3])


def signing() -> ModuleType:
    return _load("modulex_signing.py")


def pptx_to_pdf() -> ModuleType:
    return _load("pptx_to_pdf.py")
