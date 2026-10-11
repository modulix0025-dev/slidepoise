"""`latest.json` — the signed update manifest (schema ``mxs-update/1``).

Rules enforced here:
* the signature covers the canonical UTF-8 JSON of every field except ``signature``
  (sorted keys, no whitespace, Arabic kept as UTF-8), so re-serialising never breaks it;
* asset URLs are ``https`` on an allow-listed host (GitHub Releases by default);
* asset names follow ``ModuleX-MagazineStudio-Setup-<ver>[-Full].exe`` and never contain a path;
* sha256 is 64 lowercase hex and size a positive integer — the downloader checks both.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from . import versioning
from .errors import ManifestError

SCHEMA_ID = "mxs-update/1"
APP_ID = "ModuleX Magazine Studio"
DEFAULT_ALLOWED_HOSTS = ("github.com",)
ASSET_NAME = re.compile(r"^ModuleX-MagazineStudio-Setup-[0-9A-Za-z.\-]+\.exe$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
FLAVOURS = ("online", "full")

# Documentation/contract copy of the schema (the validator below is dependency-free so the
# frozen app does not need jsonschema).
JSON_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://modulex.local/schemas/mxs-update-1.json",
    "type": "object",
    "required": ["schema", "app", "version", "released_at", "assets"],
    "properties": {
        "schema": {"const": SCHEMA_ID},
        "app": {"const": APP_ID},
        "version": {"type": "string", "pattern": r"^\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?$"},
        "released_at": {"type": "string"},
        "channel": {"type": "string"},
        "tag": {"type": "string"},
        "notes_ar": {"type": "string"},
        "notes_en": {"type": "string"},
        "assets": {
            "type": "object",
            "required": ["online"],
            "properties": {f: {"$ref": "#/$defs/asset"} for f in FLAVOURS},
            "additionalProperties": False,
        },
        "signature": {
            "type": "object",
            "required": ["alg", "key_id", "value"],
            "properties": {"alg": {"const": "Ed25519"}, "key_id": {"type": "string"},
                           "value": {"type": "string"}},
        },
    },
    "$defs": {
        "asset": {
            "type": "object",
            "required": ["name", "url", "sha256", "size"],
            "properties": {
                "name": {"type": "string", "pattern": ASSET_NAME.pattern},
                "url": {"type": "string", "pattern": "^https://"},
                "sha256": {"type": "string", "pattern": SHA256.pattern},
                "size": {"type": "integer", "minimum": 1},
            },
        }
    },
}


def canonical_bytes(manifest: dict[str, Any]) -> bytes:
    """The exact bytes that are signed: everything except ``signature``."""
    body = {k: v for k, v in manifest.items() if k != "signature"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _bad(en: str, ar: str) -> ManifestError:
    return ManifestError("manifest_invalid", f"ملف التحديث مش سليم: {ar}", f"Update manifest is invalid: {en}")


def validate(manifest: Any, *, allowed_hosts: tuple[str, ...] | list[str] = DEFAULT_ALLOWED_HOSTS) -> dict[str, Any]:
    """Return the manifest if it follows mxs-update/1 and the URL/name policy, else raise."""
    if not isinstance(manifest, dict):
        raise _bad("not a JSON object", "مش JSON object")
    if manifest.get("schema") != SCHEMA_ID:
        raise _bad(f"schema must be {SCHEMA_ID}", f"الـschema لازم تكون {SCHEMA_ID}")
    if manifest.get("app") != APP_ID:
        raise _bad("wrong app id", "اسم البرنامج غلط")
    version = manifest.get("version")
    if not isinstance(version, str) or not versioning.is_valid(version):
        raise _bad("version is not X.Y.Z", "رقم النسخة مش بالشكل X.Y.Z")
    if not isinstance(manifest.get("released_at"), str):
        raise _bad("released_at missing", "تاريخ الإصدار ناقص")
    assets = manifest.get("assets")
    if not isinstance(assets, dict) or "online" not in assets:
        raise _bad("assets.online missing", "ملف المثبّت (online) ناقص")
    hosts = {h.lower() for h in allowed_hosts}
    for flavour, asset in assets.items():
        if flavour not in FLAVOURS:
            raise _bad(f"unknown flavour {flavour!r}", f"نوع مثبّت مش معروف {flavour!r}")
        if not isinstance(asset, dict):
            raise _bad(f"asset {flavour} is not an object", f"بيانات {flavour} مش object")
        name = asset.get("name")
        if not isinstance(name, str) or not ASSET_NAME.match(name):
            raise _bad(f"asset {flavour} has an unsafe name", f"اسم ملف {flavour} مش مسموح")
        url = asset.get("url")
        parsed = urlparse(url if isinstance(url, str) else "")
        if parsed.scheme != "https" or (parsed.hostname or "").lower() not in hosts:
            raise _bad(f"asset {flavour} URL must be https on {sorted(hosts)}",
                       f"رابط {flavour} لازم يكون https على {sorted(hosts)}")
        if not isinstance(asset.get("sha256"), str) or not SHA256.match(asset["sha256"]):
            raise _bad(f"asset {flavour} sha256 is not 64 lowercase hex", f"بصمة sha256 لملف {flavour} مش سليمة")
        size = asset.get("size")
        if not isinstance(size, int) or isinstance(size, bool) or size < 1:
            raise _bad(f"asset {flavour} size must be a positive integer", f"حجم ملف {flavour} لازم رقم موجب")
    return manifest


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def build(version: str, base_url: str, files: dict[str, Path], *, tag: str | None = None,
          notes_ar: str = "", notes_en: str = "", channel: str = "stable",
          released_at: str | None = None) -> dict[str, Any]:
    """Build an unsigned manifest from local installer files (used by mag-release)."""
    assets = {}
    for flavour, path in files.items():
        path = Path(path)
        assets[flavour] = {"name": path.name, "url": f"{base_url.rstrip('/')}/{path.name}",
                           "sha256": file_sha256(path), "size": path.stat().st_size}
    manifest = {
        "schema": SCHEMA_ID, "app": APP_ID, "version": version, "channel": channel,
        "released_at": released_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "notes_ar": notes_ar, "notes_en": notes_en, "assets": assets,
    }
    if tag:
        manifest["tag"] = tag
    host = urlparse(base_url).hostname or ""
    return validate(manifest, allowed_hosts=(host,) if host else DEFAULT_ALLOWED_HOSTS)
