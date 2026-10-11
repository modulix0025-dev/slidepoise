"""`mxstudio-cli connect <action>` — what the installer and uninstaller run (no window, JSON out).

    connect install   [--out FILE]   launcher into the app home + our entry in every Claude Desktop config (backup)
                                     + tools cache + registry InstallDir; never touches other servers
    connect remove    [--out FILE]   remove ONLY our entry from every config (backup)
    connect heal      [--out FILE]   the start-up self-heal (no shortcut, no window)
    connect status    [--out FILE]   facts: configs, launcher, restart pending, Claude Desktop's last log state
    connect self-test [--out FILE]   handshake exactly as Claude Desktop does it
The exe is windowed (no console), so the installer reads the JSON from --out.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mxstudio connect")
    parser.add_argument("action", choices=["install", "remove", "heal", "status", "self-test"])
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    from mxstudio.mcp import clients, heal  # noqa: PLC0415

    try:
        if args.action == "install":
            result = heal.heal_all(None, None, run_self_test=False, shortcut=False)
            entry = clients.expected_entry()
            result["install"] = clients.install(entry)
            try:
                from mxstudio.mcp.server import warm  # noqa: PLC0415
                result["tools_cache"] = warm()
            except Exception as exc:  # noqa: BLE001 - the first handshake is then slower, not broken
                result["tools_cache"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
            result["self_test"] = clients.self_test(entry, timeout=120)
            result["ok"] = bool(result["self_test"].get("ok"))
        elif args.action == "remove":
            result = {"ok": True, **clients.remove()}
        elif args.action == "heal":
            result = {"ok": True, **heal.heal_all(None, None, shortcut=False)}
        elif args.action == "status":
            result = {"ok": True, **heal.health()}
        else:
            result = clients.self_test(clients.expected_entry(), timeout=120)
    except clients.ConfigProblem as exc:
        result = {"ok": False, "code": "CONFIG_PROBLEM", "ar": exc.ar, "en": exc.en}
    text = json.dumps(result, ensure_ascii=False, indent=1, default=str)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
