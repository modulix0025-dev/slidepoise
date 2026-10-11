"""Output for the background CLI commands (update / doctor / firstrun).

Rule: ``mxstudio-cli.exe`` is a windowed (console=False) PyInstaller build, so ``sys.stdout``
may be ``None``. Results are always also writable to ``--out FILE`` (UTF-8 JSON), which is
how the installer smoke test and the server read them.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def emit(obj: Any, *, out: str | None = None, as_json: bool = True, text: str | None = None) -> None:
    payload = json.dumps(obj, ensure_ascii=False, indent=1)
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(payload + "\n", encoding="utf-8")
    stream = sys.stdout
    if stream is None:
        return
    try:
        stream.write((payload if as_json or text is None else text) + "\n")
        stream.flush()
    except (OSError, ValueError, UnicodeEncodeError):
        pass
