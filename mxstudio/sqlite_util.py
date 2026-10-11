"""One SQLite connection per `with` block: WAL, commit or rollback, then CLOSE.

`with sqlite3.connect(...) as db` only commits; the connection stays open until garbage
collection, and on Windows an open handle keeps the file locked (a temp workspace or an
uninstall cannot delete it). Every store opens its connections through `connect`.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def connect(path: str | Path, *, rows: bool = False, autocommit: bool = False) -> Iterator[sqlite3.Connection]:
    db = sqlite3.connect(path, timeout=30, **({"isolation_level": None} if autocommit else {}))
    try:
        db.execute("PRAGMA journal_mode=WAL")
        if rows:
            db.row_factory = sqlite3.Row
        with db:
            yield db
    finally:
        db.close()
