"""Restart-safe job queue on SQLite WAL with leases and idempotency keys.

A job is leased by one worker for `lease_seconds`; the worker heartbeats while
it runs. If the process dies, the lease expires and the job becomes runnable
again (attempts counted, `max_attempts` respected). Enqueueing the same
idempotency key twice returns the first job instead of creating a duplicate.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL, idempotency_key TEXT UNIQUE,
  state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL,
  lease_owner TEXT, lease_until REAL, result TEXT, error TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS jobs_state ON jobs(state, created_at);
"""
STATES = ("queued", "running", "done", "failed", "cancelled")


class JobQueue:
    def __init__(self, path: Path, clock: Callable[[], float] = time.time):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self._lock = threading.Lock()
        with self._db() as db:
            db.executescript(SCHEMA)

    def _db(self):
        from mxstudio.sqlite_util import connect  # noqa: PLC0415
        return connect(self.path, rows=True, autocommit=True)

    def enqueue(self, kind: str, payload: dict[str, Any], idempotency_key: str | None = None,
                max_attempts: int = 3) -> dict:
        now = self.clock()
        with self._lock, self._db() as db:
            if idempotency_key:
                existing = db.execute("SELECT * FROM jobs WHERE idempotency_key=?", (idempotency_key,)).fetchone()
                if existing:
                    return self._row(existing)
            job_id = uuid.uuid4().hex
            db.execute("INSERT INTO jobs (id, kind, payload, idempotency_key, state, max_attempts, created_at, "
                       "updated_at) VALUES (?,?,?,?, 'queued', ?, ?, ?)",
                       (job_id, kind, json.dumps(payload, ensure_ascii=False), idempotency_key, max_attempts, now, now))
            return self._row(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

    def lease(self, owner: str, kinds: list[str] | None = None, lease_seconds: float = 60) -> dict | None:
        now = self.clock()
        with self._lock, self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            # expired leases go back to the queue (or fail when out of attempts)
            db.execute("UPDATE jobs SET state='failed', error='lease expired after final attempt', updated_at=? "
                       "WHERE state='running' AND lease_until < ? AND attempts >= max_attempts", (now, now))
            db.execute("UPDATE jobs SET state='queued', lease_owner=NULL, lease_until=NULL, updated_at=? "
                       "WHERE state='running' AND lease_until < ?", (now, now))
            query = "SELECT * FROM jobs WHERE state='queued'"
            args: list[Any] = []
            if kinds:
                query += f" AND kind IN ({','.join('?' * len(kinds))})"
                args.extend(kinds)
            row = db.execute(query + " ORDER BY created_at LIMIT 1", args).fetchone()
            if row is None:
                db.execute("COMMIT")
                return None
            db.execute("UPDATE jobs SET state='running', lease_owner=?, lease_until=?, attempts=attempts+1, "
                       "updated_at=? WHERE id=?", (owner, now + lease_seconds, now, row["id"]))
            db.execute("COMMIT")
            return self._row(db.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone())

    def heartbeat(self, job_id: str, owner: str, lease_seconds: float = 60) -> bool:
        now = self.clock()
        with self._lock, self._db() as db:
            return db.execute("UPDATE jobs SET lease_until=?, updated_at=? WHERE id=? AND lease_owner=? AND "
                              "state='running'", (now + lease_seconds, now, job_id, owner)).rowcount == 1

    def complete(self, job_id: str, owner: str, result: dict[str, Any]) -> bool:
        return self._finish(job_id, owner, "done", result=json.dumps(result, ensure_ascii=False))

    def fail(self, job_id: str, owner: str, error: str, retry: bool = True) -> bool:
        job = self.get(job_id)
        if job and retry and job["attempts"] < job["max_attempts"]:
            now = self.clock()
            with self._lock, self._db() as db:
                return db.execute("UPDATE jobs SET state='queued', lease_owner=NULL, lease_until=NULL, error=?, "
                                  "updated_at=? WHERE id=? AND lease_owner=?", (error, now, job_id, owner)).rowcount == 1
        return self._finish(job_id, owner, "failed", error=error)

    def cancel(self, job_id: str) -> bool:
        now = self.clock()
        with self._lock, self._db() as db:
            return db.execute("UPDATE jobs SET state='cancelled', updated_at=? WHERE id=? AND state IN "
                              "('queued','running')", (now, job_id)).rowcount == 1

    def _finish(self, job_id: str, owner: str, state: str, result: str | None = None, error: str | None = None) -> bool:
        now = self.clock()
        with self._lock, self._db() as db:
            return db.execute("UPDATE jobs SET state=?, result=?, error=?, lease_owner=NULL, lease_until=NULL, "
                              "updated_at=? WHERE id=? AND lease_owner=? AND state='running'",
                              (state, result, error, now, job_id, owner)).rowcount == 1

    def get(self, job_id: str) -> dict | None:
        with self._db() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return self._row(row) if row else None

    def list(self, state: str | None = None, limit: int = 100) -> list[dict]:
        with self._db() as db:
            if state:
                rows = db.execute("SELECT * FROM jobs WHERE state=? ORDER BY created_at DESC LIMIT ?", (state, limit))
            else:
                rows = db.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,))
            return [self._row(r) for r in rows.fetchall()]

    @staticmethod
    def _row(row: sqlite3.Row) -> dict:
        out = dict(row)
        out["payload"] = json.loads(out["payload"])
        out["result"] = json.loads(out["result"]) if out["result"] else None
        return out


class Worker:
    """Runs handlers for leased jobs. One handler per job kind; handlers are pure-ish callables."""

    def __init__(self, queue: JobQueue, handlers: dict[str, Callable[[dict], dict]], owner: str | None = None):
        self.queue, self.handlers = queue, handlers
        self.owner = owner or f"worker-{uuid.uuid4().hex[:8]}"

    def run_once(self) -> dict | None:
        job = self.queue.lease(self.owner, list(self.handlers))
        if job is None:
            return None
        try:
            result = self.handlers[job["kind"]](job["payload"])
        except Exception as exc:  # noqa: BLE001 - recorded on the job, never swallowed silently
            self.queue.fail(job["id"], self.owner, f"{type(exc).__name__}: {exc}")
        else:
            self.queue.complete(job["id"], self.owner, result)
        return self.queue.get(job["id"])
