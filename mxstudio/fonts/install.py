"""Install fonts on the operator's Windows machines, per-user or machine-wide.

Rules (from how Windows and Office actually behave):

* **Per-user** install = copy to ``%LOCALAPPDATA%\\Microsoft\\Windows\\Fonts``,
  a value under ``HKCU\\Software\\Microsoft\\Windows NT\\CurrentVersion\\Fonts``
  whose data is the *full path*, ``AddFontResourceExW`` and a
  ``WM_FONTCHANGE`` broadcast. No elevation needed.
* A process running as **another user or as a service** (session 0,
  LocalSystem) does not see per-user fonts. The account that runs exports is
  therefore detected and, when it differs from the installing user or is a
  service, the install switches to **machine-wide** (``%WINDIR%\\Fonts`` +
  HKLM, file name only) — which needs UAC; the reason is explained in Arabic.
* A **running PowerPoint does not see newly installed fonts**: install, then
  wait for an idle moment (no export running) and ask for PowerPoint to be
  restarted. A live export is never killed.
* Everything Windows-only is behind :class:`WindowsBackend`; importing this
  module on Linux works, and tests use :class:`MemoryBackend`.

On-device proof pending: the real registry/AddFontResourceExW path and the
"service cannot see per-user fonts" behaviour are verified only on the
operator's PC (Proof Runner › Fonts › «تثبيت وتأكيد»).
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Protocol

from fontTools.ttLib import TTFont

FONTS_KEY = r"Software\Microsoft\Windows NT\CurrentVersion\Fonts"
SCOPES = ("user", "machine")
SYSTEM_SIDS = {"S-1-5-18", "S-1-5-19", "S-1-5-20"}  # LocalSystem, LocalService, NetworkService
WM_FONTCHANGE = 0x001D
HWND_BROADCAST = 0xFFFF
SMTO_ABORTIFHUNG = 0x0002

UAC_EXPLANATION_AR = (
    "الخطوط لازم تتثبّت لكل المستخدمين على الجهاز ده، لأن التصدير بيشتغل من حساب تاني ({account}) "
    "أو كخدمة ويندوز، والحساب ده مش بيشوف الخطوط المتثبّتة لمستخدم واحد بس. "
    "ويندوز هيطلب موافقة المدير (UAC) مرة واحدة — دوس «نعم» عشان الخطوط تتنسخ في C:\\Windows\\Fonts.")
UAC_EXPLANATION_EN = (
    "Fonts must be installed for all users on this machine because exports run as another account ({account}) "
    "or as a Windows service, which cannot see per-user fonts. Windows will ask for administrator approval (UAC) once.")
RESTART_PPT_AR = ("الخطوط اتثبّتت، بس PowerPoint المفتوح مش هيشوفها غير لما يتقفل ويتفتح تاني. "
                  "مفيش تصدير شغال دلوقتي — اقفل PowerPoint وافتحه لما تكون جاهز (إحنا مش هنقفله لوحدنا).")
RESTART_PPT_EN = ("Fonts installed, but the running PowerPoint will not see them until it is restarted. No export is "
                  "running now — restart PowerPoint when convenient (it is never closed automatically).")


class NeedsElevation(PermissionError):
    """Machine-wide install requested by a non-elevated process."""

    finding = "install_needs_elevation"

    def __init__(self, account: str):
        self.message_ar = UAC_EXPLANATION_AR.format(account=account)
        self.message_en = UAC_EXPLANATION_EN.format(account=account)
        super().__init__(self.message_en)


@dataclass(frozen=True)
class Account:
    name: str
    sid: str
    session_id: int = 1
    is_service: bool = False

    @property
    def runs_as_service(self) -> bool:
        return self.is_service or self.session_id == 0 or self.sid in SYSTEM_SIDS


@dataclass
class InstallResult:
    file: str
    windows_reported_name: str
    scope: str
    path: str
    sha256: str
    registry_value: str
    add_font_resource: int = 0

    def as_ack(self) -> dict:
        return {"file": self.file, "windows_reported_name": self.windows_reported_name, "scope": self.scope}


def choose_scope(installer: Account, exporter: Account) -> dict:
    """Per-user only when the exporting process is the same interactive user; otherwise machine-wide."""
    if exporter.runs_as_service:
        return {"scope": "machine", "reason": "exporter_is_service",
                "ar": UAC_EXPLANATION_AR.format(account=exporter.name),
                "en": UAC_EXPLANATION_EN.format(account=exporter.name)}
    if exporter.sid != installer.sid:
        return {"scope": "machine", "reason": "exporter_is_other_user",
                "ar": UAC_EXPLANATION_AR.format(account=exporter.name),
                "en": UAC_EXPLANATION_EN.format(account=exporter.name)}
    return {"scope": "user", "reason": "exporter_is_this_user", "ar": "التثبيت للمستخدم الحالي بس — مش محتاج صلاحيات مدير.",
            "en": "per-user install; no elevation needed"}


def registry_value_name(font_path: Path) -> tuple[str, str]:
    """('<Full name> (TrueType|OpenType)', full name) — what Windows lists for the file."""
    font = TTFont(str(font_path), lazy=True)
    try:
        full = str(font["name"].getDebugName(4) or font["name"].getDebugName(1) or Path(font_path).stem)
        kind = "OpenType" if ("CFF " in font or "CFF2" in font) else "TrueType"
    finally:
        font.close()
    return f"{full} ({kind})", full


def reported_name(value_name: str) -> str:
    """Strip the ' (TrueType)' / ' (OpenType)' suffix Windows adds to registry value names."""
    for suffix in (" (TrueType)", " (OpenType)"):
        if value_name.endswith(suffix):
            return value_name[: -len(suffix)]
    return value_name


class FontBackend(Protocol):
    def fonts_dir(self, scope: str) -> Path: ...
    def is_admin(self) -> bool: ...
    def current_account(self) -> Account: ...
    def registry_set(self, scope: str, name: str, value: str) -> None: ...
    def registry_values(self, scope: str) -> dict[str, str]: ...
    def add_font_resource(self, path: Path) -> int: ...
    def broadcast_font_change(self) -> None: ...
    def process_running(self, image: str) -> bool: ...


@dataclass
class MemoryBackend:
    """In-memory Windows stand-in for tests and dry runs (files really are copied into `root`)."""

    root: Path
    admin: bool = False
    account: Account = field(default_factory=lambda: Account("operator", "S-1-5-21-1-1001"))
    running: set[str] = field(default_factory=set)
    registry: dict[str, dict[str, str]] = field(default_factory=lambda: {"user": {}, "machine": {}})
    resources: list[str] = field(default_factory=list)
    broadcasts: int = 0

    def fonts_dir(self, scope: str) -> Path:
        return Path(self.root) / ("LocalAppData/Microsoft/Windows/Fonts" if scope == "user" else "Windows/Fonts")

    def is_admin(self) -> bool:
        return self.admin

    def current_account(self) -> Account:
        return self.account

    def registry_set(self, scope: str, name: str, value: str) -> None:
        self.registry[scope][name] = value

    def registry_values(self, scope: str) -> dict[str, str]:
        return dict(self.registry[scope])

    def add_font_resource(self, path: Path) -> int:
        self.resources.append(str(path))
        return 1

    def registry_delete(self, scope: str, name: str) -> None:
        self.registry[scope].pop(name, None)

    def remove_font_resource(self, path: Path) -> int:
        self.removed = [*getattr(self, "removed", []), str(path)]
        return 1

    def broadcast_font_change(self) -> None:
        self.broadcasts += 1

    def process_running(self, image: str) -> bool:
        return image.casefold() in {p.casefold() for p in self.running}


class WindowsBackend:  # pragma: no cover - exercised only on Windows (pending on-device proof)
    """Real Windows implementation: winreg + gdi32/user32/shell32/advapi32 through ctypes."""

    def __init__(self):
        if sys.platform != "win32":
            raise OSError("WindowsBackend is only available on Windows")
        import ctypes  # noqa: PLC0415
        import winreg  # noqa: PLC0415
        self.ctypes, self.winreg = ctypes, winreg

    def fonts_dir(self, scope: str) -> Path:
        if scope == "user":
            return Path(os.environ["LOCALAPPDATA"]) / "Microsoft" / "Windows" / "Fonts"
        return Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"

    def is_admin(self) -> bool:
        return bool(self.ctypes.windll.shell32.IsUserAnAdmin())

    def current_account(self) -> Account:
        ctypes = self.ctypes
        from ctypes import wintypes  # noqa: PLC0415
        advapi32, kernel32 = ctypes.windll.advapi32, ctypes.windll.kernel32
        token = wintypes.HANDLE()
        advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token))  # TOKEN_QUERY
        size = wintypes.DWORD()
        advapi32.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))  # TokenUser
        buffer = ctypes.create_string_buffer(size.value)
        advapi32.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size))
        sid_ptr = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
        string_sid = wintypes.LPWSTR()
        advapi32.ConvertSidToStringSidW(ctypes.c_void_p(sid_ptr), ctypes.byref(string_sid))
        sid = string_sid.value or ""
        kernel32.LocalFree(string_sid)
        kernel32.CloseHandle(token)
        session = wintypes.DWORD()
        kernel32.ProcessIdToSessionId(kernel32.GetCurrentProcessId(), ctypes.byref(session))
        name = os.environ.get("USERNAME", "")
        return Account(name=name, sid=sid, session_id=int(session.value), is_service=int(session.value) == 0)

    def _hive(self, scope: str):
        return self.winreg.HKEY_CURRENT_USER if scope == "user" else self.winreg.HKEY_LOCAL_MACHINE

    def registry_set(self, scope: str, name: str, value: str) -> None:
        with self.winreg.CreateKeyEx(self._hive(scope), FONTS_KEY, 0, self.winreg.KEY_SET_VALUE) as key:
            self.winreg.SetValueEx(key, name, 0, self.winreg.REG_SZ, value)

    def registry_values(self, scope: str) -> dict[str, str]:
        out: dict[str, str] = {}
        try:
            with self.winreg.OpenKey(self._hive(scope), FONTS_KEY) as key:
                index = 0
                while True:
                    try:
                        name, value, _kind = self.winreg.EnumValue(key, index)
                    except OSError:
                        break
                    out[name] = str(value)
                    index += 1
        except OSError:
            pass
        return out

    def add_font_resource(self, path: Path) -> int:
        return int(self.ctypes.windll.gdi32.AddFontResourceExW(str(path), 0, None))

    def registry_delete(self, scope: str, name: str) -> None:
        with self.winreg.OpenKey(self._hive(scope), FONTS_KEY, 0, self.winreg.KEY_SET_VALUE) as key:
            self.winreg.DeleteValue(key, name)

    def remove_font_resource(self, path: Path) -> int:
        return int(self.ctypes.windll.gdi32.RemoveFontResourceExW(str(path), 0, None))

    def broadcast_font_change(self) -> None:
        from ctypes import wintypes  # noqa: PLC0415
        result = wintypes.DWORD()
        self.ctypes.windll.user32.SendMessageTimeoutW(HWND_BROADCAST, WM_FONTCHANGE, 0, 0, SMTO_ABORTIFHUNG, 2000,
                                                      self.ctypes.byref(result))

    def process_running(self, image: str) -> bool:
        from mxstudio.proc import run_hidden  # noqa: PLC0415 - the only way the Studio starts a child
        proc = run_hidden(["tasklist", "/FI", f"IMAGENAME eq {image}", "/NH", "/FO", "CSV"], timeout=30)
        return image.casefold() in proc.stdout.decode("utf-8", "replace").casefold()


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def install_fonts(files: list[Path], scope: str, backend: FontBackend) -> list[InstallResult]:
    """Copy + register + load each font. Machine scope without elevation raises :class:`NeedsElevation`."""
    if scope not in SCOPES:
        raise ValueError(f"unknown scope {scope!r}")
    if scope == "machine" and not backend.is_admin():
        raise NeedsElevation(backend.current_account().name)
    target_dir = backend.fonts_dir(scope)
    target_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for source in files:
        source = Path(source)
        value_name, full = registry_value_name(source)
        target = target_dir / source.name
        if not target.exists() or _sha256(target) != _sha256(source):
            shutil.copyfile(source, target)
        backend.registry_set(scope, value_name, str(target) if scope == "user" else target.name)
        loaded = backend.add_font_resource(target)
        results.append(InstallResult(file=source.name, windows_reported_name=reported_name(value_name), scope=scope,
                                     path=str(target), sha256=_sha256(target), registry_value=value_name,
                                     add_font_resource=loaded))
    backend.broadcast_font_change()
    return results


def install_fonts_each(files: list[Path], scope: str, backend: FontBackend) -> dict:
    """Like :func:`install_fonts`, one file at a time: a file that fails (locked, broken, unreadable) is named and the
    REST STILL INSTALL; a target that already holds the same bytes (sha256) is never copied again — copying over a
    font that something has open was what stopped the whole install before. One WM_FONTCHANGE at the end."""
    if scope not in SCOPES:
        raise ValueError(f"unknown scope {scope!r}")
    if scope == "machine" and not backend.is_admin():
        raise NeedsElevation(backend.current_account().name)
    target_dir = backend.fonts_dir(scope)
    target_dir.mkdir(parents=True, exist_ok=True)
    results, failed, identical = [], [], 0
    for source in files:
        source = Path(source)
        try:
            value_name, _full = registry_value_name(source)
            target = target_dir / source.name
            if target.exists() and _sha256(target) == _sha256(source):
                identical += 1
            else:
                shutil.copyfile(source, target)
            backend.registry_set(scope, value_name, str(target) if scope == "user" else target.name)
            loaded = backend.add_font_resource(target)
            results.append(InstallResult(file=source.name, windows_reported_name=reported_name(value_name),
                                         scope=scope, path=str(target), sha256=_sha256(target),
                                         registry_value=value_name, add_font_resource=loaded))
        except Exception as exc:  # noqa: BLE001 - named, and the next file goes on
            failed.append({"file": source.name, "error": f"{type(exc).__name__}: {str(exc)[:160]}"})
    if results:
        backend.broadcast_font_change()
    return {"results": results, "failed": failed, "identical_skipped": identical}


def verify_installed(results: list[InstallResult], backend: FontBackend) -> list[dict]:
    """Named findings for anything that is not registered or whose bytes changed on disk."""
    problems = []
    for item in results:
        values = backend.registry_values(item.scope)
        if item.registry_value not in values:
            problems.append({"finding": "font_not_registered", "file": item.file, "scope": item.scope})
        if not Path(item.path).is_file() or _sha256(Path(item.path)) != item.sha256:
            problems.append({"finding": "font_file_changed_or_missing", "file": item.file, "scope": item.scope})
    return problems


def wait_for_idle(is_busy: Callable[[], bool], *, poll_s: float = 5.0, timeout_s: float = 1800.0,
                  sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic) -> bool:
    """Poll until nothing is exporting. Returns False on timeout. Never interrupts anything."""
    deadline = clock() + timeout_s
    while is_busy():
        if clock() >= deadline:
            return False
        sleep(poll_s)
    return True


def after_install(backend: FontBackend, export_busy: Callable[[], bool], **wait) -> dict:
    """What to tell the operator once fonts are installed. Never kills PowerPoint or an export."""
    if not backend.process_running("POWERPNT.EXE"):
        return {"state": "ready", "ar": "الخطوط جاهزة للتصدير.", "en": "fonts ready for export"}
    if not wait_for_idle(export_busy, **wait):
        return {"state": "waiting_for_idle", "ar": "فيه تصدير شغال — مستنيين يخلص قبل ما نطلب إعادة فتح PowerPoint.",
                "en": "an export is running; waiting for it to finish before asking for a PowerPoint restart"}
    return {"state": "restart_powerpoint_when_idle", "ar": RESTART_PPT_AR, "en": RESTART_PPT_EN}


def plan_install(installer: Account, exporter: Account, backend: FontBackend) -> dict:
    """Scope decision + whether UAC will be needed, for the UI to show before anything is copied."""
    decision = choose_scope(installer, exporter)
    return decision | {"needs_uac": decision["scope"] == "machine" and not backend.is_admin(),
                       "installer": asdict(installer), "exporter": asdict(exporter)}
