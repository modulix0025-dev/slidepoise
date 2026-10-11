"""Connect the local MCP server to Claude Desktop: find its config, add/remove our entry, self-test.

Only a human click in the Studio window calls `install`/`remove` (these routes are not agent tools).
The existing config is never lost: it must be valid JSON (else we refuse and say why), a timestamped
backup is written first, other servers and settings are kept as they are, and the write is atomic.
Claude Desktop reads the file at start-up, so it must be quit (from the tray) and opened again.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ENTRY = "modulex-studio"
CONFIG_NAME = "claude_desktop_config.json"


class ConfigProblem(ValueError):
    def __init__(self, ar: str, en: str):
        super().__init__(en)
        self.ar, self.en = ar, en


def config_candidates() -> list[Path]:
    """Where Claude Desktop keeps its config on this OS (the Microsoft Store build uses a redirected folder)."""
    home = Path.home()
    if sys.platform == "win32":
        out = []
        if os.environ.get("APPDATA"):
            out.append(Path(os.environ["APPDATA"]) / "Claude" / CONFIG_NAME)
        local = os.environ.get("LOCALAPPDATA")
        if local and (Path(local) / "Packages").is_dir():
            out += sorted(p / "LocalCache" / "Roaming" / "Claude" / CONFIG_NAME
                          for p in (Path(local) / "Packages").glob("*Claude*") if p.is_dir())
        return out
    if sys.platform == "darwin":
        return [home / "Library" / "Application Support" / "Claude" / CONFIG_NAME]
    return [Path(os.environ.get("XDG_CONFIG_HOME", home / ".config")) / "Claude" / CONFIG_NAME]


def config_path(candidates: list[Path] | None = None) -> Path:
    """The file Claude Desktop uses: an existing config first, else the folder Claude Desktop created."""
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


def status(entry: dict, candidates: list[Path] | None = None) -> dict:
    path = config_path(candidates)
    try:
        data = _read(path)
        current = data.get("mcpServers", {}).get(ENTRY)
        problem = None
    except ConfigProblem as exc:
        current, problem = None, {"ar": exc.ar, "en": exc.en}
    return {"path": str(path), "config_exists": path.is_file(), "claude_desktop_found": path.parent.is_dir(),
            "connected": current == entry, "current_entry": current, "expected_entry": entry, "problem": problem,
            "other_servers": sorted(k for k in (data.get("mcpServers", {}) if problem is None else {}) if k != ENTRY)}


def _write(path: Path, data: dict) -> str | None:
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if path.is_file():
        backup = path.with_name(f"{path.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}")
        backup.write_bytes(path.read_bytes())
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return str(backup) if backup else None


def install(entry: dict, candidates: list[Path] | None = None) -> dict:
    path = config_path(candidates)
    data = _read(path)
    data.setdefault("mcpServers", {})[ENTRY] = entry
    backup = _write(path, data)
    return {"path": str(path), "backup": backup, "entry": entry,
            "ar": "اتضاف. اقفل Claude Desktop خالص (من الأيقونة جنب الساعة ← Quit) وافتحه تاني.",
            "en": "Added. Quit Claude Desktop completely (tray icon → Quit) and open it again."}


def remove(candidates: list[Path] | None = None) -> dict:
    path = config_path(candidates)
    data = _read(path)
    if ENTRY not in data.get("mcpServers", {}):
        return {"path": str(path), "removed": False, "backup": None}
    del data["mcpServers"][ENTRY]
    return {"path": str(path), "removed": True, "backup": _write(path, data)}


HANDSHAKE = (b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18",'
             b'"capabilities":{},"clientInfo":{"name":"modulex-self-test","version":"1"}}}\n'
             b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
             b'{"jsonrpc":"2.0","id":2,"method":"tools/list"}\n')


def self_test(entry: dict, timeout: float = 90.0) -> dict:
    """Start the server exactly as Claude Desktop will (same command and args) and do the handshake."""
    from mxstudio.proc import run_hidden_scripted  # noqa: PLC0415
    started = time.time()
    try:
        proc = run_hidden_scripted([entry["command"], *entry.get("args", [])], HANDSHAKE, timeout=timeout)
    except (OSError, ValueError) as exc:
        return {"ok": False, "ar": "الأمر مش بيشتغل — اتأكد إن البرنامج متسطّب.", "detail": str(exc)[:300]}
    except Exception as exc:  # noqa: BLE001 - timeout and friends, reported
        return {"ok": False, "ar": "السيرفر ماردّش في الوقت.", "detail": f"{type(exc).__name__}: {exc}"[:300]}
    replies = {}
    for line in proc.stdout.decode("utf-8", "replace").splitlines():
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        replies[message.get("id")] = message
    info = (replies.get(1) or {}).get("result", {}).get("serverInfo", {})
    tools = (replies.get(2) or {}).get("result", {}).get("tools", [])
    ok = bool(info) and bool(tools)
    return {"ok": ok, "server": info, "tools": len(tools), "seconds": round(time.time() - started, 1),
            "ar": f"شغّال ✓ — {len(tools)} أداة جاهزة لـClaude." if ok else "السيرفر ماردّش صح.",
            "detail": "" if ok else proc.stderr.decode("utf-8", "replace")[-600:]}
