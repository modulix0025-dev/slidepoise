"""Signed packs — the fallback transport when a receiver endpoint does not exist.

``mag-pack-<id>.zip`` contains exactly: ``manifest.json``, ``manifest.sig``, ``document.json`` and
``files/<name>`` entries. ``manifest.sig`` is a detached HMAC made with the contract's own
``signature(secret, "POST", "/pack/<id>", timestamp, manifest_bytes)``. Import verifies the
signature (constant-time), every sha256, the exact member set (no traversal, no extras), then
hands the document to the same :func:`ingest` path the HTTP receivers use. Replays of a pack
are idempotent through the candidate store (same bytes → "duplicate").
"""
from __future__ import annotations

import base64
import datetime as _dt
import hashlib
import hmac
import io
import json
import re
import zipfile
from types import ModuleType
from typing import Any

from . import CONTRACT_VERSION, SCHEMA_FILES
from .ingest import SCHEMAS_DIR, ingest
from .store import CandidateStore, safe_name

_PACK_ID = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,63}$")
MAX_PACK = 512 * 1024 * 1024


class PackError(ValueError):
    pass


def _fixed_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    return info


def build_pack(kind: str, document: dict, *, secret: str, signing: ModuleType, pack_id: str,
               files: dict[str, bytes] | None = None, timestamp: int | None = None,
               key_id: str | None = None) -> bytes:
    """Deterministic zip bytes (fixed member order and timestamps)."""
    if kind not in SCHEMA_FILES:
        raise PackError(f"unknown kind {kind}")
    if not _PACK_ID.match(pack_id):
        raise PackError("bad pack id")
    files = dict(files or {})
    for name in files:
        if not safe_name(name):
            raise PackError(f"unsafe file name {name!r}")
    doc_bytes = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    manifest = {
        "pack_id": pack_id, "kind": kind, "contract": f"{CONTRACT_VERSION}/{kind}",
        "created_at": _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat(),
        "document": {"name": "document.json", "sha256": hashlib.sha256(doc_bytes).hexdigest()},
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())},
    }
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8")
    ts = str(int(timestamp if timestamp is not None else _dt.datetime.now(_dt.timezone.utc).timestamp()))
    sig = {"key_id": key_id or signing.DEFAULT_KEY_ID, "timestamp": ts, "alg": "modulex-hmac-sha256",
           "signed": f"POST /pack/{pack_id}",
           "signature": signing.signature(secret, "POST", f"/pack/{pack_id}", ts, manifest_bytes)}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(_fixed_info("manifest.json"), manifest_bytes)
        z.writestr(_fixed_info("manifest.sig"), json.dumps(sig, sort_keys=True).encode("utf-8"))
        z.writestr(_fixed_info("document.json"), doc_bytes)
        for name, data in sorted(files.items()):
            z.writestr(_fixed_info(f"files/{name}"), data)
    return buf.getvalue()


def read_pack(data: bytes, *, secret: str, signing: ModuleType) -> dict[str, Any]:
    """Verify and unpack. Raises :class:`PackError` with a named reason."""
    if len(data) > MAX_PACK:
        raise PackError("pack too large")
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise PackError("not a zip") from exc
    with z:
        names = z.namelist()
        for n in names:
            if n.startswith(("/", "\\")) or ".." in n.split("/") or "\\" in n or ":" in n:
                raise PackError(f"unsafe member {n!r}")
        if len(set(names)) != len(names):
            raise PackError("duplicate members")
        for required in ("manifest.json", "manifest.sig", "document.json"):
            if required not in names:
                raise PackError(f"missing {required}")
        manifest_bytes = z.read("manifest.json")
        try:
            sig = json.loads(z.read("manifest.sig"))
            manifest = json.loads(manifest_bytes)
        except ValueError as exc:
            raise PackError("manifest is not JSON") from exc
        pack_id = manifest.get("pack_id", "")
        if not isinstance(pack_id, str) or not _PACK_ID.match(pack_id):
            raise PackError("bad pack id")
        expected = signing.signature(secret, "POST", f"/pack/{pack_id}", str(sig.get("timestamp", "")),
                                     manifest_bytes)
        if not hmac.compare_digest(expected, str(sig.get("signature", ""))):
            raise PackError("signature mismatch")
        kind = manifest.get("kind")
        if kind not in SCHEMA_FILES:
            raise PackError("unknown kind")
        declared_files = manifest.get("files") or {}
        allowed = {"manifest.json", "manifest.sig", "document.json"} | {f"files/{n}" for n in declared_files}
        extras = sorted(set(names) - allowed)
        if extras:
            raise PackError(f"undeclared members {extras}")
        doc = z.read("document.json")
        if hashlib.sha256(doc).hexdigest() != (manifest.get("document") or {}).get("sha256"):
            raise PackError("document.json sha256 mismatch")
        files = {}
        for name, digest in declared_files.items():
            if not safe_name(name):
                raise PackError(f"unsafe file name {name!r}")
            blob = z.read(f"files/{name}")
            if hashlib.sha256(blob).hexdigest() != digest:
                raise PackError(f"{name}: sha256 mismatch")
            files[name] = blob
    return {"pack_id": pack_id, "kind": kind, "document": doc, "files": files, "manifest": manifest,
            "key_id": sig.get("key_id")}


def import_pack(data: bytes, *, secret: str, signing: ModuleType, store: CandidateStore,
                schemas_dir=SCHEMAS_DIR) -> tuple[int, dict[str, Any]]:
    """Verify a pack and ingest it through the receivers' own code path."""
    try:
        pack = read_pack(data, secret=secret, signing=signing)
    except PackError as exc:
        return 400, {"ok": False, "reason": f"pack refused: {exc}"}
    status, body = ingest(pack["kind"], pack["document"], store=store, schemas_dir=schemas_dir,
                          extra_files=pack["files"], source=f"pack:{pack['pack_id']}")
    body["pack_id"] = pack["pack_id"]
    return status, body


def embed_files(document: dict, files: dict[str, bytes]) -> dict:
    """Helper for HTTP senders: base64-embed files in the document's ``files`` map."""
    out = dict(document)
    out["files"] = {name: base64.b64encode(data).decode("ascii") for name, data in files.items()}
    return out
