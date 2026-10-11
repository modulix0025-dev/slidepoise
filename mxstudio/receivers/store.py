"""Candidate store: received documents are kept as candidates on disk, never activated here.

Layout: ``<base>/<kind>/<candidate_id>/{candidate.json, meta.json, files/<name>}`` where
``candidate_id = <kind>-<sha256(raw document bytes)[:16]>``. Re-sending the same bytes is
idempotent ("duplicate"). File names are validated (no separators, no traversal).
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

_SAFE_NAME = re.compile(r"^[A-Za-z0-9_.\- ]{1,120}$")


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def safe_name(name: str) -> bool:
    return bool(_SAFE_NAME.match(name)) and name not in (".", "..") and not name.startswith(".")


def confirm_code(raw: bytes) -> str:
    """The operator's confirmation code for a candidate (shown in the Studio, typed/clicked by a human)."""
    return hashlib.sha256(b"mag-confirm\0" + raw).hexdigest()[:10]


class CandidateStore:
    def __init__(self, base: Path):
        self.base = Path(base)

    def _dir(self, kind: str, cid: str) -> Path:
        if not re.match(r"^m\d-[0-9a-f]{16}$", cid):
            raise ValueError("bad candidate id")
        return self.base / kind / cid

    def put(self, kind: str, raw: bytes, files: dict[str, bytes] | None = None, *, source: str) -> dict[str, Any]:
        digest = hashlib.sha256(raw).hexdigest()
        cid = f"{kind}-{digest[:16]}"
        target = self._dir(kind, cid)
        if (target / "meta.json").is_file():
            meta = json.loads((target / "meta.json").read_text(encoding="utf-8"))
            return {"candidate_id": cid, "sha256": digest, "status": meta.get("status", "candidate"),
                    "duplicate": True}
        for name in files or {}:
            if not safe_name(name):
                raise ValueError(f"unsafe file name {name!r}")
        tmp = target.with_name(cid + ".partial")
        (tmp / "files").mkdir(parents=True, exist_ok=True)
        (tmp / "candidate.json").write_bytes(raw)
        file_rows = {}
        for name, data in (files or {}).items():
            (tmp / "files" / name).write_bytes(data)
            file_rows[name] = hashlib.sha256(data).hexdigest()
        meta = {"candidate_id": cid, "kind": kind, "sha256": digest, "received_at": _now(), "source": source,
                "status": "candidate", "files": file_rows, "confirm_code_sha256":
                    hashlib.sha256(confirm_code(raw).encode()).hexdigest()}
        (tmp / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(tmp, target)
        return {"candidate_id": cid, "sha256": digest, "status": "candidate", "duplicate": False}

    def list(self, kind: str) -> list[dict[str, Any]]:
        base = self.base / kind
        if not base.is_dir():
            return []
        out = []
        for d in sorted(base.iterdir()):
            meta = d / "meta.json"
            if meta.is_file():
                m = json.loads(meta.read_text(encoding="utf-8"))
                m.pop("confirm_code_sha256", None)
                out.append(m)
        return out

    def get(self, kind: str, cid: str) -> tuple[dict, bytes, Path]:
        d = self._dir(kind, cid)
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        return meta, (d / "candidate.json").read_bytes(), d

    def check_confirmation(self, kind: str, cid: str, code: str) -> bool:
        meta, raw, _ = self.get(kind, cid)
        return hashlib.sha256((code or "").encode()).hexdigest() == meta["confirm_code_sha256"] \
            and confirm_code(raw) == code

    def mark(self, kind: str, cid: str, status: str, **extra: Any) -> dict:
        d = self._dir(kind, cid)
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        meta["status"] = status
        meta.setdefault("history", []).append({"at": _now(), "status": status, **extra})
        tmp = d / "meta.json.tmp"
        tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, d / "meta.json")
        return meta
