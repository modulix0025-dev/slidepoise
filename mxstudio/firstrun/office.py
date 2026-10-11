"""Office engine: use PowerPoint when it is installed, otherwise LibreOffice without admin rights.

Order (brief §6.10):
1. PowerPoint detected → nothing to install (the Studio adds no PowerPoint requirement).
2. LibreOffice already present (our extraction, a machine install, or PATH) → use it.
3. Otherwise get the official MSI (Full flavour: bundled copy; online flavour: resumable
   download pinned by sha256 in ``installer/downloads.json``) and run an **administrative
   extraction** — ``msiexec /a <msi> /qn TARGETDIR=<dir>`` — which writes files only and needs
   no elevation. CI job ``libreoffice-standard-user`` and the Sandbox runbook prove it as a
   standard user; until that proof is recorded it is *pending on-device proof*.
4. If the extraction fails, ask (Arabic UAC explanation) and only with consent run the
   per-machine install elevated.

Documented exception to "paths travel in env": ``msiexec`` cannot read environment variables,
so the MSI/target paths are argv items. They go through ``CreateProcessW`` (UTF-16) via
``mxstudio.proc`` — never through cmd.exe — so the codepage incident class does not apply.
The elevated route uses ``ShellExecuteExW("runas")`` because elevation cannot be requested
through ``subprocess``; it is the only process start outside ``mxstudio.proc``.
"""
from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mxstudio.update import payloads
from mxstudio.update.errors import UpdateError

POWERPOINT_KEYS = (
    ("HKCR", r"PowerPoint.Application\CurVer", ""),
    ("HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\POWERPNT.EXE", ""),
    ("HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\POWERPNT.EXE", ""),
)
LIBREOFFICE_KEYS = (
    ("HKLM", r"SOFTWARE\LibreOffice\UNO\InstallPath", ""),
    ("HKCU", r"SOFTWARE\LibreOffice\UNO\InstallPath", ""),
)

UAC_EXPLANATION_AR = (
    "استخراج LibreOffice من غير صلاحيات مدير ما نجحش على الجهاز ده.\n"
    "لو وافقت، ويندوز هيطلب منك صلاحية مدير (UAC) مرة واحدة علشان يثبّت LibreOffice الرسمي لكل المستخدمين.\n"
    "الاستوديو نفسه هيفضل شغّال من غير صلاحيات مدير، ومش هنغيّر أي حاجة تانية في الجهاز.\n"
    "لو مش عايز: استخدم المثبّت الكامل (Full) أو اطلب من مسؤول الجهاز يثبّت LibreOffice."
)
UAC_EXPLANATION_EN = (
    "Extracting LibreOffice without admin rights failed on this PC.\n"
    "If you agree, Windows will ask once for administrator approval (UAC) to install the official LibreOffice "
    "for all users. The Studio itself keeps running without admin rights and nothing else is changed.\n"
    "If not: use the Full installer or ask the PC's administrator to install LibreOffice."
)


def detect_powerpoint(ctx) -> dict[str, Any] | None:
    if not ctx.is_windows:
        return None
    for hive, key, value in POWERPOINT_KEYS:
        found = ctx.reg_read(hive, key, value)
        if found:
            return {"engine": "powerpoint", "evidence": f"{hive}\\{key}", "value": found}
    return None


def libreoffice_target(ctx) -> Path:
    """Program-side folder for our extraction (inside the per-user program dir when installed)."""
    if getattr(ctx, "frozen", getattr(sys, "frozen", False)):
        return Path(ctx.app_dir) / "libreoffice"
    return Path(ctx.home) / "libreoffice"


def _soffice_name(ctx) -> str:
    return "soffice.exe" if ctx.is_windows else "soffice"


def find_in_tree(root: Path, exe: str) -> Path | None:
    if not root.is_dir():
        return None
    for pattern in (f"program/{exe}", f"*/program/{exe}", f"*/*/program/{exe}", f"*/*/*/program/{exe}"):
        for hit in sorted(root.glob(pattern)):
            if hit.is_file():
                return hit
    return None


def find_soffice(ctx) -> Path | None:
    exe = _soffice_name(ctx)
    hit = find_in_tree(libreoffice_target(ctx), exe)
    if hit:
        return hit
    if ctx.is_windows:
        for hive, key, value in LIBREOFFICE_KEYS:
            found = ctx.reg_read(hive, key, value)
            if found:
                candidate = Path(found) / exe
                if candidate.is_file():
                    return candidate
        for base in (Path("C:/Program Files/LibreOffice"), Path("C:/Program Files (x86)/LibreOffice")):
            if (base / "program" / exe).is_file():
                return base / "program" / exe
    for name in ("soffice", "libreoffice"):
        found = ctx.which(name)
        if found:
            return Path(found)
    return None


def detect_engine(ctx) -> dict[str, Any] | None:
    pp = detect_powerpoint(ctx)
    if pp:
        return pp
    soffice = find_soffice(ctx)
    return {"engine": "libreoffice", "soffice": str(soffice)} if soffice else None


def admin_extract_command(msi: Path, target: Path, log: Path, manifest: dict[str, Any] | None = None) -> list[str]:
    item = payloads.entry(manifest or payloads.load(), "libreoffice_msi")
    return [payloads.expand(part, msi=msi, target=target, log=log) for part in item["install"]["command"]]


def per_machine_command(msi: Path, log: Path, manifest: dict[str, Any] | None = None) -> list[str]:
    item = payloads.entry(manifest or payloads.load(), "libreoffice_msi")
    return [payloads.expand(part, msi=msi, log=log) for part in item["fallback"]["command"]]


def quote_args(args: list[str]) -> str:
    """Windows command-line quoting (same rules as CreateProcess/CommandLineToArgvW)."""
    out = []
    for arg in args:
        if arg and not any(ch in arg for ch in ' \t"'):
            out.append(arg)
            continue
        quoted, slashes = ['"'], 0
        for ch in arg:
            if ch == "\\":
                slashes += 1
                continue
            if ch == '"':
                quoted.append("\\" * (slashes * 2 + 1) + '"')
            else:
                quoted.append("\\" * slashes + ch)
            slashes = 0
        quoted.append("\\" * (slashes * 2) + '"')
        out.append("".join(quoted))
    return " ".join(out)


def _shell_execute_runas(cmd: list[str]) -> int:  # pragma: no cover - Windows only
    """Start ``cmd`` elevated (UAC prompt), hidden, and wait. Returns the exit code."""
    import ctypes
    from ctypes import wintypes

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
                    ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
                    ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
                    ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
                    ("dwHotKey", wintypes.DWORD), ("hIconOrMonitor", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]

    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x00000040  # SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "runas"
    info.lpFile = cmd[0]
    info.lpParameters = quote_args(cmd[1:])
    info.nShow = 0  # SW_HIDE
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
        return -1  # declined or failed
    ctypes.windll.kernel32.WaitForSingleObject(info.hProcess, 0xFFFFFFFF)
    code = wintypes.DWORD()
    ctypes.windll.kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
    ctypes.windll.kernel32.CloseHandle(info.hProcess)
    return int(code.value)


def install_libreoffice(ctx, *, consent_elevation: bool = False, progress: Callable[[dict], None] | None = None,
                        manifest: dict[str, Any] | None = None,
                        elevate: Callable[[list[str]], int] | None = None) -> dict[str, Any]:
    """Make an Office engine available. Returns {ok, ar, en, …}; never elevates without consent."""
    engine = detect_engine(ctx)
    if engine:
        return {"ok": True, "ar": "محرّك أوفيس موجود بالفعل.", "en": "An Office engine is already available.", **engine}
    if not ctx.is_windows:
        return {"ok": False, "ar": "تثبيت LibreOffice التلقائي للويندوز بس؛ على الجهاز ده ثبّته من مدير الحزم.",
                "en": "Automatic LibreOffice install is Windows-only; use the system package manager here."}
    manifest = manifest or payloads.load()
    try:
        msi = payloads.fetch("libreoffice_msi", Path(ctx.home) / "downloads", app_dir=ctx.app_dir, manifest=manifest,
                             transport=ctx.transport, progress=progress,
                             digits=ctx.settings.get("digits", "arabic_indic"))
    except UpdateError as err:
        return {"ok": False, "ar": err.ar, "en": err.en, "code": err.code}
    logs = Path(ctx.home) / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    target = libreoffice_target(ctx)
    target.mkdir(parents=True, exist_ok=True)
    if progress:
        progress({"ar": "بنفك LibreOffice في فولدر البرنامج (من غير صلاحيات مدير)…",
                  "en": "Extracting LibreOffice into the program folder (no admin rights)…"})
    result = ctx.run(admin_extract_command(msi, target, logs / "libreoffice-admin-extract.log", manifest),
                     timeout=1800)
    soffice = find_in_tree(target, _soffice_name(ctx))
    if getattr(result, "returncode", 1) == 0 and soffice:
        return {"ok": True, "engine": "libreoffice", "soffice": str(soffice), "method": "msi_admin_extract",
                "ar": "LibreOffice اتجهّز من غير صلاحيات مدير.", "en": "LibreOffice is ready (no admin rights used)."}
    if not consent_elevation:
        return {"ok": False, "needs_consent": True, "consent_kind": "uac", "method": "msi_admin_extract",
                "returncode": getattr(result, "returncode", None), "ar": UAC_EXPLANATION_AR, "en": UAC_EXPLANATION_EN}
    code = (elevate or _shell_execute_runas)(per_machine_command(msi, logs / "libreoffice-per-machine.log", manifest))
    soffice = find_soffice(ctx)
    if code == 0 and soffice:
        return {"ok": True, "engine": "libreoffice", "soffice": str(soffice), "method": "msi_per_machine",
                "ar": "LibreOffice اتثبّت لكل المستخدمين.", "en": "LibreOffice was installed for all users."}
    return {"ok": False, "method": "msi_per_machine", "returncode": code,
            "ar": "تثبيت LibreOffice ما نجحش. جرّب المثبّت الكامل (Full) أو ثبّته يدوي من libreoffice.org.",
            "en": "LibreOffice install failed. Try the Full installer or install it manually from libreoffice.org."}
