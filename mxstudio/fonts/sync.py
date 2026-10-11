"""M6 font sync: certified fonts → OM / Console export machines, and the machine's acknowledgement.

Payload (Studio → machine)::

    {"set_id": "...", "fonts": [{"file", "sha256", "install_names", "roles"}]}

Ack (machine → Studio)::

    {"set_id": "...", "installed": [{"file", "windows_reported_name", "scope"}], "account": {...}}

Rules:

* only fonts whose family is ``certified_print`` in the QA status may be in a
  payload, and every file's sha256 must match the bytes being sent;
* ``install_names`` are the exact names Windows reports (name ID 1 family and
  ID 4 full name); the ack's ``windows_reported_name`` must equal one of them
  exactly — internal whitespace counts (``Blabeloo  MagdySoliman`` with two
  spaces is not ``Blabeloo MagdySoliman``);
* the scope in the ack must suit the exporting account (service / other user
  ⇒ machine);
* the bytes on the wire are signed with the operator's contract
  (``vendor/modulex/modulex_signing.py``), never a re-implementation.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from functools import lru_cache
from pathlib import Path

import jsonschema

from slidepoise.arabic.fonts import normalize_family

from mxstudio.fonts.install import Account, FontBackend, choose_scope, install_fonts, registry_value_name
from mxstudio.fonts.paths import ROOT

SYNC_PATH = "/v1/fonts/sync"

PAYLOAD_SCHEMA = {
    "type": "object", "required": ["set_id", "fonts"], "additionalProperties": False,
    "properties": {
        "schema": {"const": "mx.fonts.sync/1"},
        "set_id": {"type": "string", "minLength": 1},
        "fonts": {"type": "array", "minItems": 1, "items": {
            "type": "object", "required": ["file", "sha256", "install_names", "roles"], "additionalProperties": False,
            "properties": {
                "file": {"type": "string", "pattern": r"^[^\\/:*?\"<>|]+\.(ttf|otf)$"},
                "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                "install_names": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}},
                "roles": {"type": "array", "items": {"type": "string"}},
                "family": {"type": "string"},
            }}},
    },
}
ACK_SCHEMA = {
    "type": "object", "required": ["installed", "account"], "additionalProperties": False,
    "properties": {
        "set_id": {"type": "string"},
        "installed": {"type": "array", "items": {
            "type": "object", "required": ["file", "windows_reported_name", "scope"], "additionalProperties": False,
            "properties": {"file": {"type": "string"}, "windows_reported_name": {"type": "string"},
                           "scope": {"enum": ["user", "machine"]}}}},
        "account": {"type": "object", "required": ["name", "sid"], "properties": {
            "name": {"type": "string"}, "sid": {"type": "string"}, "session_id": {"type": "integer"},
            "is_service": {"type": "boolean"}}},
        "errors": {"type": "array"},
    },
}


class SyncRefused(ValueError):
    """A payload/ack that must not be applied/accepted; `.findings` names every reason."""

    def __init__(self, findings: list[dict]):
        self.findings = findings
        super().__init__("; ".join(f"{f['finding']}: {f.get('file') or f.get('detail', '')}" for f in findings))


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def install_names_for(path: Path) -> list[str]:
    """Exact names Windows will report for this file (legacy family ID1 and full name ID4)."""
    from fontTools.ttLib import TTFont
    font = TTFont(str(path), lazy=True)
    try:
        names = [str(font["name"].getDebugName(1) or ""), registry_value_name(Path(path))[1]]
    finally:
        font.close()
    return list(dict.fromkeys(n for n in names if n))


def build_payload(set_id: str, fonts: list[dict], qa: dict) -> dict:
    """`fonts`: [{"path", "family" (catalog family), "roles"}]. Refuses anything not certified for print."""
    status = {f["family"]: f["status"] for f in qa.get("families", [])}
    findings = []
    entries = []
    for item in fonts:
        family = item["family"]
        if status.get(family) != "certified_print":
            findings.append({"finding": "sync_font_not_certified", "file": Path(item["path"]).name,
                             "detail": f"{family}: {status.get(family, 'not in QA')}"})
            continue
        path = Path(item["path"])
        entries.append({"file": path.name, "sha256": _sha256(path), "install_names": install_names_for(path),
                        "roles": list(item.get("roles", [])), "family": family})
    if findings:
        raise SyncRefused(findings)
    payload = {"schema": "mx.fonts.sync/1", "set_id": set_id, "fonts": entries}
    jsonschema.validate(payload, PAYLOAD_SCHEMA)
    return payload


def verify_payload(payload: dict, files_dir: Path, certified: set[str] | None = None) -> list[dict]:
    """Receiver-side checks before installing: schema, bytes present and equal, families certified."""
    try:
        jsonschema.validate(payload, PAYLOAD_SCHEMA)
    except jsonschema.ValidationError as exc:
        return [{"finding": "sync_payload_schema", "detail": exc.message}]
    findings = []
    for entry in payload["fonts"]:
        path = Path(files_dir) / entry["file"]
        if not path.is_file():
            findings.append({"finding": "sync_file_missing", "file": entry["file"]})
        elif _sha256(path) != entry["sha256"]:
            findings.append({"finding": "sync_sha256_mismatch", "file": entry["file"]})
        if certified is not None and entry.get("family") not in certified:
            findings.append({"finding": "sync_font_not_certified", "file": entry["file"], "detail": entry.get("family")})
    return findings


def apply_payload(payload: dict, files_dir: Path, backend: FontBackend, exporter: Account) -> dict:
    """Machine side: verify, install in the scope the exporting account needs, return the ack."""
    findings = verify_payload(payload, files_dir)
    if findings:
        raise SyncRefused(findings)
    scope = choose_scope(backend.current_account(), exporter)["scope"]
    results = install_fonts([Path(files_dir) / e["file"] for e in payload["fonts"]], scope, backend)
    return {"set_id": payload["set_id"], "installed": [r.as_ack() for r in results],
            "account": {"name": exporter.name, "sid": exporter.sid, "session_id": exporter.session_id,
                        "is_service": exporter.is_service}}


def verify_ack(payload: dict, ack: dict, installer: Account | None = None) -> list[dict]:
    """Studio side: every file installed under one of its exact install names, in a scope the exporter sees."""
    try:
        jsonschema.validate(ack, ACK_SCHEMA)
    except jsonschema.ValidationError as exc:
        return [{"finding": "sync_ack_schema", "detail": exc.message}]
    findings = []
    if ack.get("set_id") not in (None, payload["set_id"]):
        findings.append({"finding": "sync_ack_wrong_set", "detail": f"{ack.get('set_id')} != {payload['set_id']}"})
    acked = {item["file"]: item for item in ack["installed"]}
    account = ack["account"]
    exporter = Account(name=account["name"], sid=account["sid"], session_id=int(account.get("session_id", 1)),
                       is_service=bool(account.get("is_service", False)))
    needed = choose_scope(installer or exporter, exporter)["scope"]
    for entry in payload["fonts"]:
        item = acked.pop(entry["file"], None)
        if item is None:
            findings.append({"finding": "sync_file_not_installed", "file": entry["file"]})
            continue
        names = {normalize_family(n) for n in entry["install_names"]}
        if normalize_family(item["windows_reported_name"]) not in names:
            findings.append({"finding": "sync_reported_name_mismatch", "file": entry["file"],
                             "detail": f"«{item['windows_reported_name']}» not in {entry['install_names']}"})
        if needed == "machine" and item["scope"] != "machine":
            findings.append({"finding": "sync_scope_invisible_to_exporter", "file": entry["file"],
                             "detail": f"exporter {exporter.name} cannot see per-user fonts"})
    for extra in acked:
        findings.append({"finding": "sync_ack_unexpected_file", "file": extra})
    return findings


@lru_cache(maxsize=1)
def _signing():
    path = ROOT / "vendor" / "modulex" / "modulex_signing.py"
    spec = importlib.util.spec_from_file_location("mx_vendor_modulex_signing", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def encode(payload: dict) -> bytes:
    """Serialize once; these are the bytes that are signed and sent."""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_payload(raw: bytes, secret: str, *, timestamp: int | None = None) -> dict[str, str]:
    return _signing().sign(secret, "POST", SYNC_PATH, raw, timestamp=timestamp)


def verify_signed(raw: bytes, headers: dict[str, str], secret: str, *, now: float | None = None) -> tuple[bool, str]:
    signing = _signing()
    return signing.verify(secret=secret, method="POST", path=SYNC_PATH, body=raw,
                          timestamp=headers.get(signing.HEADER_TS), signature=headers.get(signing.HEADER_SIG),
                          now=now)
