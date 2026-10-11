"""Start the server on 127.0.0.1 with a random free port and a lockfile; one instance per user."""
from __future__ import annotations

import json
import os
import socket
import threading
import time
from pathlib import Path

import httpx

from mxstudio.config import app_home


def lock_path(home: Path | None = None) -> Path:
    return (home or app_home()) / "server.lock"


def read_lock(home: Path | None = None) -> dict | None:
    path = lock_path(home)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def running_instance(home: Path | None = None) -> dict | None:
    """The live server described by the lockfile, or None (stale locks are ignored)."""
    lock = read_lock(home)
    if not lock:
        return None
    try:
        response = httpx.get(f"http://127.0.0.1:{lock['port']}/api/health", timeout=2)
        if response.status_code == 200 and response.json().get("ok"):
            return lock
    except (httpx.HTTPError, ValueError, KeyError):
        pass
    return None


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def serve(home: Path | None = None, port: int | None = None, block: bool = True):
    """Run the server. Returns (server, thread) when block=False (tests, the window launcher)."""
    import uvicorn  # noqa: PLC0415

    from mxstudio.app.server import create_app  # noqa: PLC0415
    from mxstudio.app.state import AppState  # noqa: PLC0415

    home = Path(home or app_home())
    existing = running_instance(home)
    if existing:
        raise RuntimeError(f"the Studio is already running on port {existing['port']}")
    state = AppState.create(home)
    app = create_app(state)
    port = port or free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    lock = {"port": port, "pid": os.getpid(), "shutdown_token": state.shutdown_token, "started": time.time()}
    path = lock_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(lock), encoding="utf-8")
    if os.name != "nt":
        os.chmod(path, 0o600)

    def remove_lock():
        try:
            current = read_lock(home)
            if current and current.get("pid") == os.getpid() and current.get("port") == port:
                path.unlink()
        except OSError:
            pass

    def watch():
        while not server.should_exit:
            if getattr(app.state, "should_exit", False):
                server.should_exit = True
            time.sleep(0.2)

    def run_and_clean():
        try:
            server.run()
        finally:
            state.close()
            remove_lock()

    threading.Thread(target=watch, daemon=True).start()
    if block:
        run_and_clean()
        return None
    thread = threading.Thread(target=run_and_clean, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    return server, thread, port


def shutdown(home: Path | None = None) -> bool:
    lock = running_instance(home)
    if not lock:
        return False
    try:
        httpx.post(f"http://127.0.0.1:{lock['port']}/api/shutdown",
                   headers={"X-MXS-Shutdown": lock["shutdown_token"]}, timeout=5)
    except httpx.HTTPError:
        return False
    return True
