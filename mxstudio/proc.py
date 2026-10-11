"""The only way the Studio starts a child process.

Operator rules (from past incidents on his Windows PC):
* no automation may ever open a visible console window → every child gets
  ``CREATE_NO_WINDOW`` on Windows;
* Arabic paths break when passed through cmd's codepage → paths travel in
  environment variables, and the child gets ``PYTHONUTF8=1``;
* nothing interactive: stdin is closed.

`tests/mag/test_windows_rules.py` fails if any module under mxstudio/ calls
subprocess directly instead of going through this file.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000


def creation_flags() -> int:
    return CREATE_NO_WINDOW if sys.platform == "win32" else 0


def child_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    for key, value in (extra or {}).items():
        env[key] = str(value)
    return env


def run_hidden(cmd: list[str], *, env: dict[str, str] | None = None, timeout: float | None = None,
               cwd: str | Path | None = None, check: bool = False) -> subprocess.CompletedProcess:
    """Run a child with no window, no stdin, UTF-8 everywhere. Paths belong in `env`, not `cmd`."""
    return subprocess.run(cmd, env=child_env(env), timeout=timeout, cwd=str(cwd) if cwd else None,
                          stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          creationflags=creation_flags(), check=check)


def spawn_hidden(cmd: list[str], *, env: dict[str, str] | None = None, cwd: str | Path | None = None,
                 log_path: Path | None = None) -> subprocess.Popen:
    """Start a detached background child (e.g. the worker) with no window."""
    out = open(log_path, "ab") if log_path else subprocess.DEVNULL  # noqa: SIM115 - handed to the child
    return subprocess.Popen(cmd, env=child_env(env), cwd=str(cwd) if cwd else None, stdin=subprocess.DEVNULL,
                            stdout=out, stderr=subprocess.STDOUT, creationflags=creation_flags())
