"""Self-healing of the Claude Desktop connection, every time the Studio window opens (and after install).

Steps (each one measured and recorded in ``<app home>/mcp_state.json``; nothing is claimed that was not checked):
1. HKCU\\Software\\ModuleX\\MagazineStudio InstallDir/Version = where this program really runs (installed build);
2. the fixed launcher is present in ``<app home>\\bin`` (copied from the program when missing or different);
3. every Claude Desktop config has our entry pointing at that launcher — fixed when missing, broken or different;
   a config that is not valid JSON is left untouched and its reason shown in «الفحص الشامل»;
4. the tools cache is refreshed from the running Studio (so Claude Desktop's next handshake is instant);
5. the handshake is run exactly as Claude Desktop runs it (self-test), result shown in «حالة البرنامج»;
6. the inbox has a shortcut on the operator's real desktop.
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from mxstudio.mcp import clients
from mxstudio.winsys import SYSTEM, System

log = logging.getLogger("mxstudio.mcp.heal")
SHORTCUT_NAME_AR = "الوارد - استوديو المجلات"
SHORTCUT_PS = ("$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:MXS_LNK); "
               "$s.TargetPath = $env:MXS_TARGET; $s.Description = 'ModuleX Magazine Studio inbox'; $s.Save()")


def desktop_shortcut(inbox: Path, system: System | None = None, run=None) -> dict:
    """A shortcut to the inbox on the desktop the operator really sees (OneDrive\\Desktop or Desktop)."""
    system = system or SYSTEM
    desktop = system.known_desktop()
    if system.platform != "win32":
        return {"ok": False, "skipped": "not windows", "desktop": str(desktop)}
    link = desktop / f"{SHORTCUT_NAME_AR}.lnk"
    if link.is_file():
        return {"ok": True, "action": "present", "path": str(link)}
    if run is None:
        from mxstudio.proc import run_hidden as run  # noqa: PLC0415
    result = run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", SHORTCUT_PS],
                 env={"MXS_LNK": str(link), "MXS_TARGET": str(inbox)}, timeout=60)
    return {"ok": result.returncode == 0 and link.is_file(), "action": "created", "path": str(link)}


def heal_all(state=None, app=None, *, home: Path | None = None, workspace: Path | None = None,
             system: System | None = None, candidates: list[Path] | None = None, run_self_test: bool = True,
             shortcut: bool = True) -> dict:
    from mxstudio.config import APP_VERSION, app_home  # noqa: PLC0415
    from mxstudio.runtime_paths import app_dir, frozen  # noqa: PLC0415
    from mxstudio.winsys import record_install  # noqa: PLC0415

    system = system or SYSTEM
    home = Path(home or (state.home if state is not None else app_home()))
    report: dict = {"at": time.time()}
    if frozen() and system.platform == "win32":
        report["registry"] = record_install(app_dir(), APP_VERSION, system)
    report["launcher"] = clients.ensure_launcher(home)
    entry = clients.expected_entry(home)
    try:
        report["configs"] = clients.heal(entry, candidates, home)
    except clients.ConfigProblem as exc:
        report["configs"] = {"error": {"ar": exc.ar, "en": exc.en}}
    if state is not None:
        try:
            from mxstudio.mcp.server import StudioMCP, write_cache  # noqa: PLC0415
            write_cache(StudioMCP(state, app).list_tools(), home)
            report["tools_cache"] = "written"
        except Exception as exc:  # noqa: BLE001 - recorded
            report["tools_cache"] = f"failed: {type(exc).__name__}"
    if shortcut and workspace is not None:
        from mxstudio.agent.inbox import inbox_dir  # noqa: PLC0415
        try:
            report["inbox_shortcut"] = desktop_shortcut(inbox_dir(workspace), system)
        except Exception as exc:  # noqa: BLE001 - recorded
            report["inbox_shortcut"] = {"ok": False, "error": type(exc).__name__}
    if run_self_test:
        report["self_test"] = clients.self_test(entry, timeout=120)
    clients.write_state(home, last_heal=report)
    return report


def start_background(state, app) -> threading.Thread:
    """Run the heal in a daemon thread when the Studio server starts (never delays the window)."""
    def work():
        try:
            heal_all(state, app, workspace=state.workspace.root)
        except Exception:  # noqa: BLE001 - recorded in the log; the Doctor shows the facts
            log.exception("mcp self-heal failed")
    thread = threading.Thread(target=work, name="mcp-heal", daemon=True)
    thread.start()
    return thread


def health(home: Path | None = None, system: System | None = None) -> dict:
    """Everything «حالة البرنامج» and «توصيل Claude Desktop» show about the connection."""
    state = clients.read_state(home)
    entry = clients.expected_entry(home)
    try:
        configs = clients.status(entry)
    except clients.ConfigProblem as exc:
        configs = {"connected": False, "problem": {"ar": exc.ar, "en": exc.en}, "configs": []}
    return {"entry": entry, "connected": configs.get("connected"), "configs": configs.get("configs", []),
            "launcher_present": Path(entry["command"]).is_file() if Path(entry["command"]).is_absolute() else True,
            "restart": clients.restart_pending(home, system), "claude_log": clients.claude_log_state(),
            "last_heal": state.get("last_heal"), "config_changed_at": state.get("config_changed_at")}
