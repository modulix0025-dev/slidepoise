"""Content-addressed workspace with versioned, immutable approved artefacts.

Blobs live at ``blobs/<sha[:2]>/<sha>``; records (stories, art, templates,
packs…) are JSON documents in SQLite with a version history. Approving a
version freezes it: later writes create a new version, never change the
approved one. Restore = copy an old version forward as the newest one.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
  kind TEXT NOT NULL, key TEXT NOT NULL, version INTEGER NOT NULL,
  body TEXT NOT NULL, blobs TEXT NOT NULL, approved INTEGER NOT NULL DEFAULT 0,
  approved_by TEXT, created_at REAL NOT NULL, note TEXT,
  PRIMARY KEY (kind, key, version));
"""


class ImmutableError(RuntimeError):
    pass


class Workspace:
    def __init__(self, root: Path):
        self.root = Path(root)
        (self.root / "blobs").mkdir(parents=True, exist_ok=True)
        self._db_path = self.root / "workspace.sqlite3"
        self._lock = threading.Lock()
        with self._connect() as db:
            db.executescript(SCHEMA)

    def _connect(self):
        from mxstudio.sqlite_util import connect  # noqa: PLC0415
        return connect(self._db_path, rows=True)

    # -- blobs -------------------------------------------------------------
    def put_bytes(self, data: bytes) -> str:
        sha = hashlib.sha256(data).hexdigest()
        path = self.blob_path(sha)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
        return sha

    def put_file(self, source: Path) -> str:
        digest = hashlib.sha256()
        with open(source, "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        sha = digest.hexdigest()
        path = self.blob_path(sha)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, path.with_suffix(".tmp"))
            path.with_suffix(".tmp").replace(path)
        return sha

    def blob_path(self, sha: str) -> Path:
        if len(sha) != 64 or not all(c in "0123456789abcdef" for c in sha):
            raise ValueError("not a sha256")
        return self.root / "blobs" / sha[:2] / sha

    def verify_blob(self, sha: str) -> bool:
        path = self.blob_path(sha)
        return path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == sha

    # -- records -----------------------------------------------------------
    def save(self, kind: str, key: str, body: dict[str, Any], blobs: dict[str, str] | None = None,
             note: str = "") -> int:
        for sha in (blobs or {}).values():
            if not self.blob_path(sha).is_file():
                raise FileNotFoundError(f"blob {sha} is not in the workspace")
        with self._lock, self._connect() as db:
            row = db.execute("SELECT MAX(version) AS v FROM records WHERE kind=? AND key=?", (kind, key)).fetchone()
            version = (row["v"] or 0) + 1
            db.execute("INSERT INTO records VALUES (?,?,?,?,?,0,NULL,?,?)",
                       (kind, key, version, json.dumps(body, ensure_ascii=False, sort_keys=True),
                        json.dumps(blobs or {}, sort_keys=True), time.time(), note))
        return version

    def get(self, kind: str, key: str, version: int | None = None) -> dict | None:
        with self._connect() as db:
            if version is None:
                row = db.execute("SELECT * FROM records WHERE kind=? AND key=? ORDER BY version DESC LIMIT 1",
                                 (kind, key)).fetchone()
            else:
                row = db.execute("SELECT * FROM records WHERE kind=? AND key=? AND version=?",
                                 (kind, key, version)).fetchone()
        return self._row(row) if row else None

    def history(self, kind: str, key: str) -> list[dict]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM records WHERE kind=? AND key=? ORDER BY version", (kind, key)).fetchall()
        return [self._row(row) for row in rows]

    def latest(self, kind: str) -> dict | None:
        """The most recently saved record of a kind (any key), or None."""
        with self._connect() as db:
            row = db.execute("SELECT * FROM records WHERE kind=? ORDER BY created_at DESC, version DESC LIMIT 1",
                             (kind,)).fetchone()
        return self._row(row) if row else None

    def keys(self, kind: str) -> list[str]:
        with self._connect() as db:
            return [r["key"] for r in db.execute("SELECT DISTINCT key FROM records WHERE kind=? ORDER BY key", (kind,))]

    def approve(self, kind: str, key: str, version: int, approved_by: str) -> dict:
        if not approved_by:
            raise ValueError("an approval names the human who approved")
        with self._lock, self._connect() as db:
            updated = db.execute("UPDATE records SET approved=1, approved_by=? WHERE kind=? AND key=? AND version=? "
                                 "AND approved=0", (approved_by, kind, key, version)).rowcount
            if not updated:
                raise ImmutableError(f"{kind}/{key} v{version} does not exist or is already approved")
        return self.get(kind, key, version)

    def latest_approved(self, kind: str, key: str) -> dict | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM records WHERE kind=? AND key=? AND approved=1 ORDER BY version DESC LIMIT 1",
                             (kind, key)).fetchone()
        return self._row(row) if row else None

    def restore(self, kind: str, key: str, version: int) -> int:
        old = self.get(kind, key, version)
        if old is None:
            raise KeyError(f"{kind}/{key} v{version}")
        return self.save(kind, key, old["body"], old["blobs"], note=f"restored from v{version}")

    def diff(self, kind: str, key: str, a: int, b: int) -> dict:
        left, right = self.get(kind, key, a), self.get(kind, key, b)
        if left is None or right is None:
            raise KeyError("version not found")
        keys = sorted(set(left["body"]) | set(right["body"]))
        changed = {k: {"from": left["body"].get(k), "to": right["body"].get(k)} for k in keys
                   if left["body"].get(k) != right["body"].get(k)}
        blobs = {k: {"from": left["blobs"].get(k), "to": right["blobs"].get(k)}
                 for k in sorted(set(left["blobs"]) | set(right["blobs"])) if left["blobs"].get(k) != right["blobs"].get(k)}
        return {"body": changed, "blobs": blobs}

    @staticmethod
    def _row(row: sqlite3.Row) -> dict:
        return {"kind": row["kind"], "key": row["key"], "version": row["version"], "body": json.loads(row["body"]),
                "blobs": json.loads(row["blobs"]), "approved": bool(row["approved"]), "approved_by": row["approved_by"],
                "created_at": row["created_at"], "note": row["note"]}
