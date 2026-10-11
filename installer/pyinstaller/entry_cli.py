"""Entry of ``mxstudio-cli.exe`` — windowed (console=False) build for background commands.

``mxstudio-cli.exe <subcommand> …`` is dispatched by ``mxstudio.__main__.main(argv)``
(serve / open / shutdown / doctor / kit / update / firstrun). Until that module exists, the
release-owned subcommands are dispatched here so the installed-app smoke test can run.
"""
from __future__ import annotations

import sys

OWN = {"doctor": "mxstudio.doctor", "update": "mxstudio.update", "firstrun": "mxstudio.firstrun"}


def dispatch(argv: list[str]) -> int:
    try:
        from mxstudio.__main__ import main as app_main  # type: ignore[import-not-found]
    except ImportError:
        app_main = None
    if app_main is not None:
        return int(app_main(argv) or 0)
    if argv and argv[0] in OWN:
        import importlib
        return int(importlib.import_module(OWN[argv[0]]).main(argv[1:]) or 0)
    if argv and argv[0] == "shutdown":
        return 0  # nothing to stop until the server exists
    return 2


if __name__ == "__main__":
    sys.exit(dispatch(sys.argv[1:]))
