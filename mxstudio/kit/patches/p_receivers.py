"""P-RECEIVERS — mount signed M1/M6/M7 receivers in OM and the M2 receiver in the Console.

Anchors: each system's FastAPI app module, package import root, OM ``add_story`` signature, and the
         sha256 of each system's own ``modulex_signing.py`` (the receivers import that copy).
Hooks:   module end of each app module, behind MODULEX_MAG_RECEIVERS (default OFF).
Payload: ``mxstudio/receivers`` copied verbatim to ``app/mag_receivers`` (OM) and
         ``execution_console/mag_receivers`` (Console) + a generated ``mag_config.json``.
"""
from __future__ import annotations

from pathlib import Path

from .base import Hook, Patch, Payload

RECEIVERS = Path(__file__).resolve().parents[2] / "receivers"
SOURCES = (RECEIVERS,)  # the whole relocatable package: *.py + schemas/


def _signing_rel(ctx: dict, anchor_id: str, default: str) -> str:
    anchor = ctx["anchors"].get(anchor_id, {})
    return anchor.get("file") or default


def om_config(ctx: dict) -> dict:
    return {"system": "OM", "kinds": ["m1", "m6", "m7"], "system_root_up": 2,
            "signing_module": _signing_rel(ctx, "OM.signing.sha", "modulex_core/modulex_signing.py"),
            "store_dir": "mag_candidates", "story_engine_module": "app.services.story_engine",
            "templates_dir": "story_templates"}


def console_config(ctx: dict) -> dict:
    return {"system": "Console", "kinds": ["m2"], "system_root_up": 2,
            "signing_module": _signing_rel(ctx, "Console.signing.sha", "modulex_signing.py"),
            "store_dir": "mag_candidates"}


def _hook(system: str, package: str) -> Hook:
    body = ('if __import__("os").environ.get("MODULEX_MAG_RECEIVERS", "0").strip() == "1":\n'
            f'    from {package}.mount import mount as _mx_mount_receivers\n'
            '    _mx_mount_receivers({app_var})\n')
    return Hook(system, "@app_object", "module_end", body)


PATCH = Patch(
    id="P-RECEIVERS",
    flag="MODULEX_MAG_RECEIVERS",
    title_ar="مستقبلات العقود الموقّعة (M1/M2/M6/M7)",
    title_en="Signed contract receivers (M1/M2/M6/M7)",
    summary_en="Signed (verify + check_replay) candidate receivers; activation only via OM add_story()/update_story() "
               "after the operator's confirmation code; M2 approval stays human on the Console.",
    anchors=("OM.app_object", "OM.app_package", "OM.story_engine.add_story", "OM.signing.sha",
             "Console.app_object", "Console.package", "Console.signing.sha"),
    hooks=(_hook("OM", "app.mag_receivers"), _hook("Console", "execution_console.mag_receivers")),
    payloads=(Payload("OM", "app/mag_receivers", SOURCES, config=om_config),
              Payload("Console", "execution_console/mag_receivers", SOURCES, config=console_config)),
    notes=(("If the Console runs as a frozen PyInstaller build, source hooks take effect only after the operator's "
            "own rebuild — the probe reports frozen_app_hint; use signed packs meanwhile."),),
)
