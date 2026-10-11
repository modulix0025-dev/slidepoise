"""The Studio window: pywebview pointed at the local server — and NOTHING exposed to JavaScript.

pywebview's JavaScript bridge (its js_api argument) froze the operator's OM window through recursive .NET
serialisation, so this window never passes one. The UI talks HTTP to the
loopback server like any web page.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from mxstudio.app.runner import running_instance, serve
from mxstudio.config import APP_NAME
from mxstudio.proc import spawn_hidden


def window_options(url: str) -> dict:
    """The exact keyword arguments for webview.create_window (pinned by a test: no js_api)."""
    return {"title": APP_NAME, "url": url, "width": 1360, "height": 860, "min_size": (1024, 680),
            "text_select": True}


def ensure_server(home: Path | None = None, background_process: bool = True) -> dict:
    lock = running_instance(home)
    if lock:
        return lock
    if background_process:
        exe = Path(sys.executable)
        pythonw = exe.with_name("pythonw.exe")
        runner = [str(pythonw if pythonw.exists() else exe), "-m", "mxstudio", "serve"]
        if getattr(sys, "frozen", False):
            runner = [str(exe.with_name("mxstudio-cli.exe")), "serve"]
        spawn_hidden(runner)
        for _ in range(100):
            time.sleep(0.1)
            lock = running_instance(home)
            if lock:
                return lock
        raise RuntimeError("the Studio server did not start")
    _server, _thread, port = serve(home, block=False)
    return {"port": port}


def open_window(home: Path | None = None) -> None:  # pragma: no cover - needs a desktop
    import webview  # noqa: PLC0415 - pywebview is Windows-only in the bundle

    lock = ensure_server(home)
    webview.create_window(**window_options(f"http://127.0.0.1:{lock['port']}/"))
    webview.start()
