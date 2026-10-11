"""Shared builder for the three OM editor extensions (P-SAFEZONE, P-PREVIEW, P-PROOF).

Each one is its own patch with its own flag, payload package and marker block in OM's app
module (the module that creates ``FastAPI()``, found by the ``OM.app_object`` anchor). The
hook mounts the extension's router only when its flag is 1, so flags off ⇒ nothing mounted.
"""
from __future__ import annotations

from .base import PAYLOADS, Hook, Payload


def editor_config(ctx: dict) -> dict:
    return {"deck_module": "app.editor.deck", "print_service_module": "app.printing.print_service",
            "system_root_up": 2, "cache_dir": "mag_cache/preview"}


def hook(flag: str, package: str) -> Hook:
    body = (f'if __import__("os").environ.get("{flag}", "0").strip() == "1":\n'
            f'    from app.{package}.mount import mount as _mx_mount_{package}\n'
            f'    _mx_mount_{package}({{app_var}})\n')
    return Hook("OM", "@app_object", "module_end", body)


def payload(name: str) -> Payload:
    return Payload("OM", f"app/mag_{name}", (PAYLOADS / name, PAYLOADS / "_common" / "editor_common.py"),
                   config=editor_config)


ANCHORS = ("OM.app_object", "OM.app_package", "OM.editor.deck.signatures")
