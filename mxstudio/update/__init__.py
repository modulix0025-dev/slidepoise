"""Signed auto-update for ModuleX Magazine Studio (no paid code-signing certificate).

Integrity comes from an Ed25519-signed ``latest.json`` (public key embedded in the app,
private key only in the CI secret ``MXS_UPDATE_SIGNING_KEY``) plus sha256 of every file.
Updates are downloaded in the background (resumable), verified, staged, and installed on
the next launch only with the operator's consent; the previous installer is kept for
one-click rollback. See ``state.py`` for the state machine.

Integration points for the rest of the app:
* ``open`` → ``launch_hook()`` first; if it returns True an installer was started: exit.
* the server → ``UpdateManager().check()`` / ``.download()`` in a background thread,
  ``.consent()`` from the UI, ``.rollback()`` from Settings.
"""
from __future__ import annotations

from .errors import IntegrityError, ManifestError, SignatureError, UpdateError
from .state import UpdateManager


def launch_hook() -> bool:
    """Settle the last apply/rollback and start a consented staged update. True → exit now."""
    try:
        manager = UpdateManager()
        if not manager.trust.auto_update_enabled:
            return False  # no embedded key: nothing staged can be verified, so nothing is ever started
        return manager.launch_hook()
    except UpdateError:
        return False


def main(argv: list[str] | None = None) -> int:
    from .cli import main as _main
    return _main(argv)


__all__ = ["IntegrityError", "ManifestError", "SignatureError", "UpdateError", "UpdateManager", "launch_hook", "main"]
