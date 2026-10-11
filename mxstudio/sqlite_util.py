"""One SQLite connection per `with` block: WAL, commit or rollback, then CLOSE.

`with sqlite3.connect(...) as db` only commits; the connection stays open until garbage
collection, and on Windows an open handle keeps the file locked (a temp workspace or an
uninstall cannot delete it). Every store opens its connections through `connect`.
"""
from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


BUSY_TIMEOUT_MS = 30_000  # the Studio window and every MCP server (Claude Desktop may start several) share files


def _wal(db: sqlite3.Connection, attempts: int = 20) -> None:
    """Switching to WAL needs a moment of exclusive access; another process may hold it — retry, never fail."""
    for attempt in range(attempts):
        try:
            db.execute("PRAGMA journal_mode=WAL")
            return
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc) and "busy" not in str(exc):
                raise
            time.sleep(0.05 * (attempt + 1))
    db.execute("PRAGMA journal_mode=WAL")


@contextmanager
def connect(path: str | Path, *, rows: bool = False, autocommit: bool = False) -> Iterator[sqlite3.Connection]:
    db = sqlite3.connect(path, timeout=BUSY_TIMEOUT_MS / 1000, **({"isolation_level": None} if autocommit else {}))
    try:
        db.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        _wal(db)
        if rows:
            db.row_factory = sqlite3.Row
        with db:
            yield db
    finally:
        db.close()
