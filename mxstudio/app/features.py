"""Optional feature areas (factory, fonts, shapes, colour, kit, QA, doctor…) plug in here.

Each area exposes `register(app, state)` in `mxstudio/<area>/api.py`. A missing or
broken area is reported in /api/features instead of taking the whole Studio down.
"""
from __future__ import annotations

import importlib
import logging

log = logging.getLogger("mxstudio.features")
AREAS = ("factory", "fonts", "shapes", "colour", "kit", "qa", "doctor", "update", "firstrun", "marketing", "agent")


def mount_features(app, state) -> None:
    status: dict[str, str] = {}
    for area in AREAS:
        try:
            module = importlib.import_module(f"mxstudio.{area}.api")
        except ModuleNotFoundError as exc:
            status[area] = f"absent ({exc.name})"
            continue
        try:
            module.register(app, state)
            status[area] = "ok"
        except Exception as exc:  # noqa: BLE001 - one area must not break the others
            log.exception("feature %s failed to mount", area)
            status[area] = f"error: {type(exc).__name__}: {exc}"

    @app.get("/api/features")
    def features():
        return {"features": status}
