"""One Studio window per Windows user: a second start brings the existing window to the front and exits.

* Windows: a named mutex ``Local\\ModuleX.MagazineStudio.Window`` held for the life of the window process (the OS
  releases it when the process dies, so a crash never blocks the next start);
* elsewhere (tests, dev): an exclusive ``flock`` on ``<app home>/window.lock`` with the same semantics;
* ``server.lock`` whose pid is dead is stale and removed (a crash or a power cut must not leave the Studio «running»).
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

MUTEX_NAME = "Local\\ModuleX.MagazineStudio.Window"
ERROR_ALREADY_EXISTS = 183
_held: list = []  # keeps the mutex handle / lock file alive for the life of the process


def acquire(home: Path | None = None):
    """Return a guard when this is the first window, None when one already runs."""
    if sys.platform == "win32":  # pragma: no cover - proven by the Windows proof script
        import ctypes  # noqa: PLC0415
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
        if not handle:
            return object()  # cannot tell: never block the operator
        if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(ctypes.c_void_p(handle))
            return None
        _held.append(handle)
        return handle
    import fcntl  # noqa: PLC0415
    from mxstudio.config import app_home  # noqa: PLC0415
    path = Path(home or app_home()) / "window.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+")  # noqa: SIM115 - held open on purpose
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()))
    handle.flush()
    _held.append(handle)
    return handle


def release_all() -> None:
    while _held:
        item = _held.pop()
        if hasattr(item, "close"):
            item.close()
        elif sys.platform == "win32":  # pragma: no cover
            import ctypes  # noqa: PLC0415
            ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(item))


def bring_to_front(title: str) -> bool:
    """Restore and focus the existing Studio window (found by its exact title)."""
    if sys.platform != "win32":
        return False
    import ctypes  # noqa: PLC0415  pragma: no cover
    user32 = ctypes.windll.user32
    user32.FindWindowW.restype = ctypes.c_void_p
    for _ in range(50):  # the first window may still be opening
        hwnd = user32.FindWindowW(None, title)
        if hwnd:
            user32.ShowWindow(ctypes.c_void_p(hwnd), 9)  # SW_RESTORE
            user32.SetForegroundWindow(ctypes.c_void_p(hwnd))
            return True
        time.sleep(0.1)
    return False


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":  # pragma: no cover
        import ctypes  # noqa: PLC0415
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.restype = ctypes.c_void_p
        handle = kernel32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        try:
            kernel32.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code))
        finally:
            kernel32.CloseHandle(ctypes.c_void_p(handle))
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def clear_stale_server_lock(home: Path | None = None) -> bool:
    """Remove server.lock when the process it names is gone. Returns True when something was removed."""
    from mxstudio.app.runner import lock_path  # noqa: PLC0415
    path = lock_path(home)
    try:
        lock = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        if path.is_file():  # unreadable/half-written lock
            try:
                path.unlink()
                return True
            except OSError:
                return False
        return False
    if pid_alive(int(lock.get("pid") or 0)):
        return False
    try:
        path.unlink()
    except OSError:
        return False
    return True


def probe_main(argv: list[str]) -> int:  # pragma: no cover - driven by tests in a child process
    """`python -m mxstudio.shell.single <home> <seconds>`: acquire, report, hold — the multi-start test."""
    home, hold = Path(argv[0]), float(argv[1])
    guard = acquire(home)
    print("first" if guard is not None else "second", flush=True)
    if guard is not None:
        time.sleep(hold)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(probe_main(sys.argv[1:]))
