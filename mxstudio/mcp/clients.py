"""Keep Claude Desktop connected to the local MCP server: every config it reads, one fixed launcher, self-healing.

Rules:
* the entry is ALWAYS the fixed launcher in the app home (``<app home>\\bin\\mxstudio-mcp.exe``, no args), never the
  program's own exe: uninstalling, reinstalling, moving or upgrading the program then never changes the config;
* every Claude Desktop config on this PC is kept in step (the classic ``%APPDATA%\\Claude`` one and each Microsoft
  Store package's redirected copy);
* the existing config is never lost: it must be valid JSON (else we refuse, say why in Arabic, and leave it as it is),
  a timestamped backup is written first, other servers and settings are kept, the write is atomic;
* only a human click, the installer, or the app's own start-up self-heal writes the config — no agent tool can;
* Claude Desktop reads the file at start-up: after any change we remember the time, and a Claude.exe that started
  before it is reported as «needs a restart» (and can be restarted on the operator's confirmation).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

from mxstudio.winsys import SYSTEM, System

ENTRY = "modulex-studio"
CONFIG_NAME = "claude_desktop_config.json"
LAUNCHER_NAME = "mxstudio-mcp.exe"
STATE_NAME = "mcp_state.json"
CLAUDE_IMAGE = "Claude.exe"
HANDSHAKE_BUDGET_S = 2.0


class ConfigProblem(ValueError):
    def __init__(self, ar: str, en: str):
        super().__init__(en)
        self.ar, self.en = ar, en


# ------------------------------------------------------------------ where Claude Desktop keeps things
def _store_roots() -> list[Path]:
    local = os.environ.get("LOCALAPPDATA")
    if not local or not (Path(local) / "Packages").is_dir():
        return []
    return sorted(p / "LocalCache" / "Roaming" / "Claude" for p in (Path(local) / "Packages").glob("Claude_*")
                  if p.is_dir())


def claude_roots() -> list[Path]:
    """Every folder a Claude Desktop build keeps its config and logs in (classic first, then Store packages)."""
    home = Path.home()
    if sys.platform == "win32":
        out = []
        if os.environ.get("APPDATA"):
            out.append(Path(os.environ["APPDATA"]) / "Claude")
        return out + _store_roots()
    if sys.platform == "darwin":
        return [home / "Library" / "Application Support" / "Claude"]
    return [Path(os.environ.get("XDG_CONFIG_HOME", home / ".config")) / "Claude"]


def config_candidates() -> list[Path]:
    return [root / CONFIG_NAME for root in claude_roots()]


def config_path(candidates: list[Path] | None = None) -> Path:
    """The primary config: an existing file first, else the folder Claude Desktop created, else the first candidate."""
    candidates = candidates if candidates is not None else config_candidates()
    for path in candidates:
        if path.is_file():
            return path
    for path in candidates:
        if path.parent.is_dir():
            return path
    if not candidates:
        raise ConfigProblem("مش عارف مكان إعدادات Claude Desktop على النظام ده.", "unknown config location")
    return candidates[0]


def live_configs(candidates: list[Path] | None = None) -> list[Path]:
    """Every config a Claude Desktop on this PC will read: existing files, or folders Claude Desktop made.
    When none exists yet, the primary location (so «connect» still prepares it before the first start)."""
    candidates = candidates if candidates is not None else config_candidates()
    found = [p for p in candidates if p.is_file() or p.parent.is_dir()]
    return found or ([config_path(candidates)] if candidates else [])


def _read(path: Path) -> dict:
    if not path.is_file():
        return {}
    raw = path.read_text(encoding="utf-8-sig").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigProblem(f"ملف إعدادات Claude Desktop فيه خطأ (سطر {exc.lineno}) — صلّحه الأول أو امسحه؛ "
                            "مش هلمسه علشان مايضيعش حاجة.",
                            f"Claude Desktop config is not valid JSON (line {exc.lineno}); not touching it") from exc
    if not isinstance(data, dict) or not isinstance(data.get("mcpServers", {}), dict):
        raise ConfigProblem("شكل ملف إعدادات Claude Desktop مش متوقع — مش هلمسه.", "unexpected config shape")
    return data


def _write(path: Path, data: dict) -> str | None:
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if path.is_file():
        backup = path.with_name(f"{path.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}")
        n = 1
        while backup.exists():  # two writes in the same second never overwrite a backup
            backup = path.with_name(f"{path.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}-{n}")
            n += 1
        backup.write_bytes(path.read_bytes())
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return str(backup) if backup else None


# ------------------------------------------------------------------ the fixed launcher
def launcher_path(home: Path | None = None) -> Path:
    from mxstudio.config import app_home  # noqa: PLC0415
    return Path(home or app_home()) / "bin" / LAUNCHER_NAME


def bundled_launcher(app_dir: Path | None = None) -> Path:
    from mxstudio.runtime_paths import app_dir as program_dir  # noqa: PLC0415
    return Path(app_dir or program_dir()) / "mcp" / LAUNCHER_NAME


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ensure_launcher(home: Path | None = None, app_dir: Path | None = None) -> dict:
    """Put the program's launcher in the app home (copy when missing or different). A copy that is in use by a
    running Claude Desktop is left alone (same launcher logic; replaced on the next start)."""
    source, target = bundled_launcher(app_dir), launcher_path(home)
    if not source.is_file():
        return {"ok": target.is_file(), "action": "no_bundled_launcher", "path": str(target)}
    if target.is_file() and _sha(target) == _sha(source):
        return {"ok": True, "action": "current", "path": str(target)}
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".new")
    try:
        shutil.copyfile(source, tmp)
        os.replace(tmp, target)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        return {"ok": target.is_file(), "action": "busy", "path": str(target), "error": type(exc).__name__}
    return {"ok": True, "action": "copied", "path": str(target)}


def expected_entry(home: Path | None = None, app_dir: Path | None = None, frozen: bool | None = None,
                   platform: str | None = None) -> dict:
    """What Claude Desktop must run. Installed on Windows: the fixed launcher. A source checkout: this Python."""
    from mxstudio.runtime_paths import frozen as is_frozen  # noqa: PLC0415
    frozen = is_frozen() if frozen is None else frozen
    platform = platform or sys.platform
    if frozen and platform == "win32":
        return {"command": str(launcher_path(home)), "args": []}
    if frozen:
        from mxstudio.runtime_paths import app_dir as program_dir  # noqa: PLC0415
        return {"command": str(Path(app_dir or program_dir()) / "mxstudio-cli"), "args": ["mcp"]}
    return {"command": sys.executable, "args": ["-m", "mxstudio", "mcp"]}


def entry_problem(current, entry: dict) -> str | None:
    """Why our current entry is not good, or None."""
    if not current:
        return "missing"
    if not isinstance(current, dict) or not isinstance(current.get("command"), str):
        return "malformed"
    if current.get("command") != entry["command"] or list(current.get("args") or []) != list(entry.get("args") or []):
        return "different"
    command = Path(current["command"])
    if command.is_absolute() and not command.is_file():
        return "command_missing"
    return None


# ------------------------------------------------------------------ status / install / remove
def _one_status(path: Path, entry: dict) -> dict:
    try:
        data = _read(path)
        current = data.get("mcpServers", {}).get(ENTRY)
        problem = None
    except ConfigProblem as exc:
        data, current, problem = {}, None, {"ar": exc.ar, "en": exc.en}
    reason = entry_problem(current, entry) if problem is None else "invalid_json"
    return {"path": str(path), "config_exists": path.is_file(), "claude_desktop_found": path.parent.is_dir(),
            "connected": problem is None and reason is None, "reason": reason, "current_entry": current,
            "problem": problem, "store": "Packages" in path.parts,
            "other_servers": sorted(k for k in data.get("mcpServers", {}) if k != ENTRY)}


def status(entry: dict, candidates: list[Path] | None = None) -> dict:
    configs = [_one_status(p, entry) for p in live_configs(candidates)]
    primary = configs[0] if configs else _one_status(config_path(candidates), entry)
    return {**primary, "expected_entry": entry, "configs": configs,
            "connected": bool(configs) and all(c["connected"] for c in configs)}


def install(entry: dict, candidates: list[Path] | None = None, home: Path | None = None) -> dict:
    """Add/refresh our entry in every Claude Desktop config. Any invalid config stops the whole install (nothing is
    written) so the operator fixes it first."""
    targets = live_configs(candidates)
    datas = [(path, _read(path)) for path in targets]  # raises ConfigProblem before anything is written
    written = []
    for path, data in datas:
        if data.get("mcpServers", {}).get(ENTRY) == entry and path.is_file():
            written.append({"path": str(path), "backup": None, "changed": False})
            continue
        data.setdefault("mcpServers", {})[ENTRY] = entry
        written.append({"path": str(path), "backup": _write(path, data), "changed": True})
    if any(w["changed"] for w in written):
        remember_change(home, [w["path"] for w in written if w["changed"]], "install")
    first = written[0] if written else {"path": "", "backup": None}
    return {"path": first["path"], "backup": first["backup"], "configs": written, "entry": entry,
            "ar": "اتضاف. اقفل Claude Desktop خالص (من الأيقونة جنب الساعة ← Quit) وافتحه تاني — أو دوس «أعد تشغيل Claude Desktop».",
            "en": "Added. Quit Claude Desktop completely (tray icon → Quit) and open it again, or press «Restart Claude Desktop»."}


def remove(candidates: list[Path] | None = None, home: Path | None = None) -> dict:
    """Remove ONLY our entry from every config (backup first); other servers are kept. Invalid configs are skipped."""
    results = []
    for path in live_configs(candidates):
        try:
            data = _read(path)
        except ConfigProblem as exc:
            results.append({"path": str(path), "removed": False, "backup": None, "problem": {"ar": exc.ar, "en": exc.en}})
            continue
        if ENTRY not in data.get("mcpServers", {}):
            results.append({"path": str(path), "removed": False, "backup": None})
            continue
        del data["mcpServers"][ENTRY]
        results.append({"path": str(path), "removed": True, "backup": _write(path, data)})
    if any(r["removed"] for r in results):
        remember_change(home, [r["path"] for r in results if r["removed"]], "remove")
    first = results[0] if results else {"path": "", "removed": False, "backup": None}
    return {**first, "removed": any(r["removed"] for r in results), "configs": results}


def heal(entry: dict, candidates: list[Path] | None = None, home: Path | None = None) -> dict:
    """Start-up self-heal: fix our entry where it is missing, points at a file that is gone, or differs. A config that
    is not valid JSON is never touched — its reason is reported for «الفحص الشامل»."""
    report = []
    for path in live_configs(candidates):
        try:
            data = _read(path)
        except ConfigProblem as exc:
            report.append({"path": str(path), "action": "untouched_invalid", "ar": exc.ar, "en": exc.en})
            continue
        reason = entry_problem(data.get("mcpServers", {}).get(ENTRY), entry)
        if reason is None:
            report.append({"path": str(path), "action": "ok"})
            continue
        data.setdefault("mcpServers", {})[ENTRY] = entry
        backup = _write(path, data)
        report.append({"path": str(path), "action": "fixed", "reason": reason, "backup": backup,
                       "kept_servers": sorted(k for k in data["mcpServers"] if k != ENTRY)})
    fixed = [r["path"] for r in report if r["action"] == "fixed"]
    if fixed:
        remember_change(home, fixed, "heal")
    return {"configs": report, "fixed": len(fixed),
            "invalid": [r for r in report if r["action"] == "untouched_invalid"]}


# ------------------------------------------------------------------ change time → «restart Claude Desktop»
def _state_path(home: Path | None) -> Path:
    from mxstudio.config import app_home  # noqa: PLC0415
    return Path(home or app_home()) / STATE_NAME


def read_state(home: Path | None = None) -> dict:
    try:
        return json.loads(_state_path(home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_state(home: Path | None, **patch) -> dict:
    path = _state_path(home)
    data = read_state(home) | patch
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)
    return data


def remember_change(home: Path | None, paths: list[str], why: str, when: float | None = None) -> None:
    write_state(home, config_changed_at=when or time.time(), config_changed_paths=paths, config_changed_by=why)


def claude_processes(system: System | None = None) -> list:
    return (system or SYSTEM).processes(CLAUDE_IMAGE)


def restart_pending(home: Path | None = None, system: System | None = None) -> dict:
    """Is a Claude Desktop running that started BEFORE our last config change (so it has not read it)?"""
    changed = float(read_state(home).get("config_changed_at") or 0)
    running = claude_processes(system)
    stale = [p for p in running if p.started and p.started < changed]
    return {"pending": bool(stale), "running": bool(running), "config_changed_at": changed or None,
            "claude_started_at": min((p.started for p in running if p.started), default=None),
            "ar": "Claude Desktop لازم يتقفل ويتفتح علشان يشوف الاستوديو." if stale else "",
            "en": "Claude Desktop must be quit and reopened to see the Studio." if stale else ""}


# ------------------------------------------------------------------ Claude Desktop's own log
_LOG_CONNECTED = re.compile(r"connected successfully|Message from server", re.I)
_LOG_STARTING = re.compile(r"Initializing server|Launching MCP Server|Server started", re.I)
_LOG_ERROR = re.compile(r"\[error\]|Server disconnected|transport closed unexpectedly|spawn .* ENOENT|exited with code",
                        re.I)


def log_paths(roots: list[Path] | None = None) -> list[Path]:
    return [root / "logs" / f"mcp-server-{ENTRY}.log" for root in (roots if roots is not None else claude_roots())]


def claude_log_state(paths: list[Path] | None = None, tail_bytes: int = 64 * 1024) -> dict:
    """The last state Claude Desktop logged for our server: connected / error / starting / unknown, with the line."""
    best = None
    for path in paths if paths is not None else log_paths():
        if not path.is_file():
            continue
        with open(path, "rb") as handle:
            handle.seek(max(0, path.stat().st_size - tail_bytes))
            lines = handle.read().decode("utf-8", "replace").splitlines()
        state, line_seen = "unknown", ""
        for line in lines:
            if _LOG_ERROR.search(line):
                state, line_seen = "error", line
            elif _LOG_CONNECTED.search(line):
                state, line_seen = "connected", line
            elif _LOG_STARTING.search(line):
                state, line_seen = "starting", line
        found = {"state": state, "line": line_seen.strip()[:400], "path": str(path), "mtime": path.stat().st_mtime}
        if best is None or found["mtime"] > best["mtime"]:
            best = found
    return best or {"state": "no_log", "line": "", "path": None, "mtime": None}


# ------------------------------------------------------------------ restart Claude Desktop (operator-confirmed)
START_APPS_PS = ("$a = Get-StartApps | Where-Object { $_.Name -eq 'Claude' -or $_.AppID -like 'Claude_*' } | "
                 "Select-Object -First 1; if ($a) { [Console]::Out.Write($a.AppID) }")


def restart_claude(system: System | None = None, run=None, sleep=time.sleep, timeout_s: float = 15.0) -> dict:
    """Quit every Claude.exe (closing its window only hides it in the tray, so the processes are ended) and start it
    again: the Store build through shell:AppsFolder\\<AppID>, the classic build through its exe. The UI asks for the
    operator's confirmation first: any conversation in progress in Claude Desktop is interrupted."""
    system = system or SYSTEM
    if run is None:
        from mxstudio.proc import run_hidden as run  # noqa: PLC0415
    running = claude_processes(system)
    exe = next((p.path for p in running if p.path), "")
    if running:
        run(["taskkill", "/T", "/F", "/IM", CLAUDE_IMAGE], timeout=30)
        deadline = time.monotonic() + timeout_s
        while claude_processes(system) and time.monotonic() < deadline:
            sleep(0.5)
        if claude_processes(system):
            return {"ok": False, "ar": "Claude Desktop مارضيش يتقفل — اقفله من الأيقونة جنب الساعة ← Quit.",
                    "en": "Claude Desktop did not quit; quit it from the tray icon."}
    store = "WindowsApps" in exe or not exe
    started = False
    if store:
        found = run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", START_APPS_PS], timeout=60)
        app_id = (found.stdout or b"").decode("utf-8", "replace").strip()
        if app_id:
            run(["explorer.exe", f"shell:AppsFolder\\{app_id}"], timeout=30)
            started = True
    if not started:
        local = os.environ.get("LOCALAPPDATA", "")
        for candidate in (exe, str(Path(local) / "AnthropicClaude" / "claude.exe")):
            if candidate and Path(candidate).is_file():
                from mxstudio.proc import spawn_hidden  # noqa: PLC0415
                spawn_hidden([candidate])
                started = True
                break
    return {"ok": started, "was_running": bool(running),
            "ar": "Claude Desktop اتفتح تاني — استنى ثواني لحد ما الأدوات تظهر." if started
            else "قفلت Claude Desktop بس مش لاقي أفتحه — افتحه بإيدك من قايمة ابدأ.",
            "en": "Claude Desktop restarted." if started else "Claude Desktop was quit; open it from the Start menu."}


# ------------------------------------------------------------------ handshake
HANDSHAKE = (b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18",'
             b'"capabilities":{},"clientInfo":{"name":"modulex-self-test","version":"1"}}}\n'
             b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
             b'{"jsonrpc":"2.0","id":2,"method":"tools/list"}\n')


def self_test(entry: dict, timeout: float = 90.0) -> dict:
    """Start the server exactly as Claude Desktop will (same command and args) and do the handshake.
    Every stdout line must be JSON-RPC: anything else would break Claude Desktop's parser."""
    from mxstudio.proc import run_hidden_scripted  # noqa: PLC0415
    started = time.time()
    try:
        proc = run_hidden_scripted([entry["command"], *entry.get("args", [])], HANDSHAKE, timeout=timeout)
    except (OSError, ValueError) as exc:
        return {"ok": False, "ar": "الأمر مش بيشتغل — اتأكد إن البرنامج متسطّب.", "detail": str(exc)[:300]}
    except Exception as exc:  # noqa: BLE001 - timeout and friends, reported
        return {"ok": False, "ar": "السيرفر ماردّش في الوقت.", "detail": f"{type(exc).__name__}: {exc}"[:300]}
    seconds = round(time.time() - started, 2)
    replies, junk = {}, []
    for line in proc.stdout.decode("utf-8", "replace").splitlines():
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            junk.append(line[:200])
            continue
        replies[message.get("id")] = message
    info = (replies.get(1) or {}).get("result", {}).get("serverInfo", {})
    tools = (replies.get(2) or {}).get("result", {}).get("tools", [])
    ok = bool(info) and bool(tools) and not junk
    return {"ok": ok, "server": info, "tools": len(tools), "seconds": seconds, "non_json_stdout_lines": junk[:5],
            "fast": seconds <= HANDSHAKE_BUDGET_S,
            "ar": f"شغّال ✓ — {len(tools)} أداة جاهزة لـClaude ({seconds} ث)." if ok
            else ("السيرفر طبع حاجة مش JSON على stdout." if junk else "السيرفر ماردّش صح."),
            "detail": "" if ok else proc.stderr.decode("utf-8", "replace")[-600:]}
