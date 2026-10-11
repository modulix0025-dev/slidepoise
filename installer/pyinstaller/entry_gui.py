"""Entry of ``ModuleX Magazine Studio.exe`` (windowed, console=False).

No arguments → ``open`` (the desktop window; ``open`` runs ``mxstudio.update.launch_hook()``
first). ``--shutdown`` (older installers) → ``shutdown``. Anything else is passed through.
"""
from __future__ import annotations

import sys

from entry_cli import dispatch  # same folder; bundled by the spec


def main(argv: list[str]) -> int:
    if not argv:
        argv = ["open"]
    elif argv == ["--shutdown"]:
        argv = ["shutdown"]
    return dispatch(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
