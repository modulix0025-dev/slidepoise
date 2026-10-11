"""Helpers shared by the Kit suites (kept out of conftest.py so they can be imported by name)."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


def ok_runner(_system_root):
    return {"ran": True, "returncode": 0, "tail": "fake runner: ok"}


def tree_digest(root: Path) -> dict[str, str]:
    """sha256 of every file under root except Kit backups and Python caches."""
    out = {}
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        if p.is_file() and "/_backup_mag_" not in f"/{rel}" and "__pycache__" not in p.parts:
            out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def run_child(code: str, *, pythonpath: Path, env: dict | None = None, timeout: int = 120) -> dict:
    """Run ``code`` in a fresh interpreter (isolates the replica's ``app`` package); returns its JSON."""
    from mxstudio.proc import run_hidden

    extra = {"PYTHONPATH": str(pythonpath), **(env or {})}
    res = run_hidden([sys.executable, "-c", code], env=extra, timeout=timeout, cwd=pythonpath)
    out = res.stdout.decode("utf-8", "replace").strip()
    assert res.returncode == 0, res.stderr.decode("utf-8", "replace")[-3000:]
    return json.loads(out.splitlines()[-1])
