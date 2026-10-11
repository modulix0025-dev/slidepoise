"""`python -m mxstudio <command>` — every command is non-interactive and prints JSON where useful.

serve | open | shutdown | status | worker | doctor | kit | update | firstrun | factory | fonts | evals
"""
from __future__ import annotations

import importlib
import json
import sys


def _delegate(module: str, argv: list[str]) -> int:
    try:
        target = importlib.import_module(module)
    except ModuleNotFoundError as exc:
        print(json.dumps({"ok": False, "error": f"{module} is not installed ({exc.name})"}))
        return 2
    return int(target.main(argv) or 0)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    command = argv.pop(0) if argv else "open"
    if command == "serve":
        from mxstudio.app.runner import serve  # noqa: PLC0415
        serve()
        return 0
    if command == "open":
        from mxstudio.shell.launcher import open_window  # noqa: PLC0415
        open_window()
        return 0
    if command in {"shutdown", "--shutdown"}:
        from mxstudio.app.runner import shutdown  # noqa: PLC0415
        print(json.dumps({"ok": shutdown()}))
        return 0
    if command == "status":
        from mxstudio.app.runner import running_instance  # noqa: PLC0415
        lock = running_instance()
        print(json.dumps({"running": bool(lock), "port": lock and lock.get("port")}))
        return 0
    if command == "worker":
        from mxstudio.jobs import main as worker_main  # noqa: PLC0415
        return int(worker_main(argv) or 0)
    modules = {"doctor": "mxstudio.doctor", "kit": "mxstudio.kit.cli", "update": "mxstudio.update",
               "firstrun": "mxstudio.firstrun", "factory": "mxstudio.factory.cli", "fonts": "mxstudio.fonts.cli",
               "evals": "mxstudio.agent.evals.cli"}
    if command in modules:
        return _delegate(modules[command], argv)
    print(json.dumps({"ok": False, "error": f"unknown command {command!r}", "commands": ["serve", "open", "shutdown",
                                                                                         "status", "worker",
                                                                                         *modules]}))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
