"""Everything the Doctor touches, behind one injectable object.

Rule: checks and fixers never import subprocess, sockets, winreg or the network directly;
they go through a :class:`DoctorContext`, whose defaults use ``mxstudio.proc`` for every
child process. Tests replace any member with a fake.
"""
from __future__ import annotations

import shutil
import socket
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mxstudio import proc


def program_dir() -> Path:
    """Installed program folder (frozen) or the repository root (source checkout)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def self_command(*args: str) -> list[str]:
    """How to re-run this app's CLI as a child (frozen: sibling mxstudio-cli.exe)."""
    if getattr(sys, "frozen", False):
        cli = Path(sys.executable).resolve().parent / ("mxstudio-cli.exe" if sys.platform == "win32" else "mxstudio-cli")
        return [str(cli), "doctor", *args]
    return [sys.executable, "-m", "mxstudio.doctor", *args]


def _connect(host: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _http_get(url: str, timeout: float) -> int:
    import urllib.error
    import urllib.request
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="GET"), timeout=timeout) as response:
            return int(response.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)
    except (OSError, ValueError):
        return 0


def _reg_read(hive: str, key: str, value: str = "") -> str | None:
    if sys.platform != "win32":
        return None
    import winreg  # type: ignore[import-not-found]
    roots = {"HKCU": winreg.HKEY_CURRENT_USER, "HKLM": winreg.HKEY_LOCAL_MACHINE, "HKCR": winreg.HKEY_CLASSES_ROOT}
    try:
        with winreg.OpenKey(roots[hive], key) as handle:
            data, _ = winreg.QueryValueEx(handle, value)
            return str(data)
    except OSError:
        return None


def _disk_free(path: Path) -> int:
    probe = Path(path)
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return shutil.disk_usage(probe).free


@dataclass
class DoctorContext:
    settings: dict[str, Any]
    workspace: Path
    home: Path
    app_dir: Path = field(default_factory=program_dir)
    platform: str = sys.platform
    frozen: bool = field(default_factory=lambda: bool(getattr(sys, "frozen", False)))
    run: Callable[..., Any] = proc.run_hidden
    connect: Callable[[str, int, float], bool] = _connect
    http_get: Callable[[str, float], int] = _http_get
    reg_read: Callable[..., str | None] = _reg_read
    disk_free: Callable[[Path], int] = _disk_free
    which: Callable[[str], str | None] = shutil.which
    self_command: Callable[..., list[str]] = self_command
    transport: Any = None  # mxstudio.update.download transport for fixers (None → urllib)
    timeout: float = 3.0

    @classmethod
    def default(cls) -> DoctorContext:
        from mxstudio.config import Settings, app_home
        settings = Settings()
        return cls(settings=settings.load(), workspace=settings.workspace(), home=app_home())

    @property
    def is_windows(self) -> bool:
        return self.platform == "win32"
