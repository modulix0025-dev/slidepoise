"""One ingest path for HTTP receivers and signed packs: parse → schema → cross-checks → candidate store.

Cross-checks beyond the schema (named refusals):
* M1: every embedded file must be a declared variant file with the declared sha256;
* M2: ``slot_map`` keys must be declared variants; sha256 keys likewise;
* M6: every embedded font file must be declared with the matching sha256.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
from pathlib import Path
from typing import Any

from . import SCHEMA_FILES
from .store import CandidateStore, safe_name
from .validate import validate

MAX_BODY = 64 * 1024 * 1024
SCHEMAS_DIR = Path(__file__).resolve().parent / "schemas"


def load_schema(kind: str, schemas_dir: Path = SCHEMAS_DIR) -> dict:
    return json.loads((Path(schemas_dir) / SCHEMA_FILES[kind]).read_text(encoding="utf-8"))


def _declared_m1(doc: dict) -> dict[str, str]:
    out = {}
    for size in (doc.get("variants") or {}).values():
        for gender in size.values():
            for variant in gender.values():
                out[variant["file"]] = variant["sha256"]
    return out


def ingest(kind: str, raw: bytes, *, store: CandidateStore, schemas_dir: Path = SCHEMAS_DIR,
           extra_files: dict[str, bytes] | None = None, source: str = "http") -> tuple[int, dict[str, Any]]:
    if kind not in SCHEMA_FILES:
        return 404, {"ok": False, "reason": f"unknown contract kind {kind}"}
    if len(raw) > MAX_BODY:
        return 413, {"ok": False, "reason": "document too large"}
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        return 400, {"ok": False, "reason": f"not UTF-8 JSON: {exc.__class__.__name__}"}
    errors = validate(doc, load_schema(kind, schemas_dir))
    if errors:
        return 422, {"ok": False, "reason": "schema", "errors": errors[:50]}
    files: dict[str, bytes] = {}
    for name, b64 in (doc.get("files") or {}).items():
        try:
            files[name] = base64.b64decode(b64, validate=False)
        except (binascii.Error, ValueError):
            return 422, {"ok": False, "reason": f"file {name!r} is not base64"}
    for name, data in (extra_files or {}).items():
        files[name] = data
    for name in files:
        if not safe_name(name):
            return 422, {"ok": False, "reason": f"unsafe file name {name!r}"}
    problems: list[str] = []
    if kind == "m1":
        declared = _declared_m1(doc)
        for name, data in files.items():
            if name not in declared:
                problems.append(f"{name}: not a declared variant file")
            elif hashlib.sha256(data).hexdigest() != declared[name]:
                problems.append(f"{name}: sha256 differs from the declared variant sha256")
    elif kind == "m2":
        variants = set(doc["variants"])
        problems += [f"slot_map.{k}: not a declared variant" for k in doc["slot_map"] if k not in variants]
        problems += [f"variant_sha256.{k}: not a declared variant" for k in doc.get("variant_sha256", {})
                     if k not in variants]
    elif kind == "m6":
        declared = {f["file"]: f["sha256"] for f in doc["fonts"]}
        for name, data in files.items():
            if declared.get(name) != hashlib.sha256(data).hexdigest():
                problems.append(f"{name}: not declared or sha256 mismatch")
    if problems:
        return 422, {"ok": False, "reason": "cross-check", "errors": problems}
    try:
        stored = store.put(kind, raw, files, source=source)
    except ValueError as exc:
        return 422, {"ok": False, "reason": str(exc)}
    return (200 if stored["duplicate"] else 202), {"ok": True, **stored,
                                                   "next": "operator confirmation in the Studio / receiving system"}
