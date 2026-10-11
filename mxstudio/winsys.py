"""Facts about this Windows PC the Studio needs to stay connected: where it is installed, whether that folder
syncs (OneDrive / Dropbox / Google Drive / Files On-Demand), the real desktop, and running processes.

Rules:
* everything Windows-only goes through :class:`System`, so tests inject a fake and the same logic runs on Linux;
* the registry home of the Studio is ``HKCU\\Software\\ModuleX\\MagazineStudio`` (InstallDir, Version), written
  by the installer and refreshed by the app on every start (self-healing after a manual move);
* a sync folder is refused/warned about because «on-demand» files make the exe start late or not at all
  (Claude Desktop then times out) and the sync client locks files while it uploads them.
"""
from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

REG_KEY = r"Software\ModuleX\MagazineStudio"
APP_DIR_NAME = "ModuleX Magazine Studio"
# GetFileAttributesW bits that mean "the bytes live in the cloud until something reads them"
FILE_ATTRIBUTE_OFFLINE = 0x00001000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x00040000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x00400000
CLOUD_ATTRIBUTES = FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_OPEN | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS
SYNC_ENV = ("OneDrive", "OneDriveConsumer", "OneDriveCommercial")
SYNC_NAMES = ("onedrive", "dropbox", "google drive", "googledrive", "my drive", "icloud drive", "icloudrive",
              "box sync", "pcloud", "mega")


@dataclass
class ProcessInfo:
    pid: int
    name: str
    path: str
    started: float  # epoch seconds


class System:
    """Real implementation (Windows: winreg + kernel32/shell32 through ctypes; elsewhere: honest no-ops)."""

    platform = sys.platform

    # -- registry -------------------------------------------------------------------------------------
    def reg_get(self, name: str, key: str = REG_KEY) -> str | None:
        if sys.platform != "win32":
            return None
        import winreg  # noqa: PLC0415
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
                return str(winreg.QueryValueEx(handle, name)[0])
        except OSError:
            return None

    def reg_set(self, name: str, value: str, key: str = REG_KEY) -> bool:
        if sys.platform != "win32":
            return False
        import winreg  # noqa: PLC0415
        try:
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as handle:
                winreg.SetValueEx(handle, name, 0, winreg.REG_SZ, value)
            return True
        except OSError:
            return False

    # -- files ------------------------------------------------------------------------------------------
    def file_attributes(self, path: Path) -> int:
        if sys.platform != "win32":
            return 0
        import ctypes  # noqa: PLC0415
        value = ctypes.windll.kernel32.GetFileAttributesW(str(path))
        return 0 if value in (-1, 0xFFFFFFFF) else int(value)

    def env(self, name: str) -> str | None:
        return os.environ.get(name)

    def known_desktop(self) -> Path:
        """The desktop the operator SEES (SHGetKnownFolderPath(FOLDERID_Desktop)): OneDrive\\Desktop when OneDrive
        backs it up, else %USERPROFILE%\\Desktop."""
        if sys.platform == "win32":
            try:
                import ctypes  # noqa: PLC0415
                from ctypes import wintypes  # noqa: PLC0415
                import uuid  # noqa: PLC0415

                class GUID(ctypes.Structure):
                    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                                ("Data4", wintypes.BYTE * 8)]

                raw = uuid.UUID("{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}").bytes_le  # FOLDERID_Desktop
                guid = GUID.from_buffer_copy(raw)
                out = ctypes.c_wchar_p()
                if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(out)) == 0:
                    try:
                        return Path(out.value)
                    finally:
                        ctypes.windll.ole32.CoTaskMemFree(out)
            except Exception:  # noqa: BLE001 - fall back to the profile folder
                pass
        return Path.home() / "Desktop"

    # -- processes --------------------------------------------------------------------------------------
    def processes(self, image: str) -> list[ProcessInfo]:
        """Running processes with this image name (case-insensitive), with their start time."""
        if sys.platform == "win32":  # pragma: no cover - exercised by the Windows proof
            return _win_processes(image)
        return _posix_processes(image)


def _posix_processes(image: str) -> list[ProcessInfo]:
    out = []
    proc = Path("/proc")
    if not proc.is_dir():
        return out
    boot = time.time() - float(Path("/proc/uptime").read_text().split()[0])
    ticks = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            name = (entry / "comm").read_text().strip()
            if name.casefold() != image.casefold():
                continue
            fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
            started = boot + int(fields[19]) / ticks
            out.append(ProcessInfo(int(entry.name), name, os.readlink(entry / "exe"), started))
        except OSError:
            continue
    return out


def _win_processes(image: str) -> list[ProcessInfo]:  # pragma: no cover - Windows only
    import ctypes  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415

    kernel32 = ctypes.windll.kernel32
    TH32CS_SNAPPROCESS, PROCESS_QUERY_LIMITED_INFORMATION = 0x2, 0x1000

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_void_p), ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_wchar * 260)]

    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.OpenProcess.restype = wintypes.HANDLE
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
    out: list[ProcessInfo] = []
    try:
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.casefold() == image.casefold():
                pid = int(entry.th32ProcessID)
                handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
                path, started = "", 0.0
                if handle:
                    try:
                        buf = ctypes.create_unicode_buffer(1024)
                        size = wintypes.DWORD(1024)
                        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                            path = buf.value
                        times = [wintypes.FILETIME() for _ in range(4)]
                        if kernel32.GetProcessTimes(handle, *[ctypes.byref(t) for t in times]):
                            ft = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
                            started = ft / 1e7 - 11644473600.0
                    finally:
                        kernel32.CloseHandle(handle)
                out.append(ProcessInfo(pid, entry.szExeFile, path, started))
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)
    return out


SYSTEM = System()


# ------------------------------------------------------------------ install location
def default_install_dir(system: System | None = None) -> Path:
    system = system or SYSTEM
    local = system.env("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(local) / "Programs" / APP_DIR_NAME


def _parts(path: str) -> list[str]:
    return [p.casefold() for p in PureWindowsPath(path).parts] if "\\" in path or ":" in path[:3] \
        else [p.casefold() for p in Path(path).parts]


def _under(path: str, root: str) -> bool:
    a, b = _parts(path), _parts(root)
    return len(a) >= len(b) and a[:len(b)] == b


def sync_folder_reason(path: str | Path, system: System | None = None) -> dict | None:
    """Why this folder is a bad place for the program, or None. Checks the sync clients' own environment
    variables, well-known folder names, and the cloud «Files On-Demand» attributes of the folder and its parents."""
    system = system or SYSTEM
    text = str(path)
    for name in SYNC_ENV:
        root = system.env(name)
        if root and _under(text, root):
            return {"kind": "onedrive", "root": root, "via": f"%{name}%"}
    for part in _parts(text):
        for marker in SYNC_NAMES:
            if part == marker or part.startswith(marker + " -") or part.startswith(marker + "-"):
                return {"kind": marker.replace(" ", "_"), "root": None, "via": "folder name"}
    probe = PureWindowsPath(text) if ("\\" in text or text[1:2] == ":") else Path(text)
    for candidate in (probe, *probe.parents):
        attributes = system.file_attributes(candidate)
        if attributes & CLOUD_ATTRIBUTES:
            return {"kind": "cloud_files", "root": str(candidate), "via": f"attributes 0x{attributes:08x}"}
    return None


def record_install(app_dir: Path, version: str, system: System | None = None) -> dict:
    """Self-heal of HKCU\\Software\\ModuleX\\MagazineStudio: InstallDir/Version = where this program really runs."""
    system = system or SYSTEM
    before = {"InstallDir": system.reg_get("InstallDir"), "Version": system.reg_get("Version")}
    changed = []
    for name, value in (("InstallDir", str(app_dir)), ("Version", version)):
        if before[name] != value and system.reg_set(name, value):
            changed.append(name)
    return {"before": before, "changed": changed}


def installed_cli(system: System | None = None) -> Path | None:
    """mxstudio-cli.exe of the installed program (registry first, then the default folder)."""
    system = system or SYSTEM
    for folder in (system.reg_get("InstallDir"), str(default_install_dir(system))):
        if folder and (Path(folder) / "mxstudio-cli.exe").is_file():
            return Path(folder) / "mxstudio-cli.exe"
    return None
