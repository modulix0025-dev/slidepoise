"""Mount the P-SAFEZONE routes (called from the hook in OM's app module only when the flag is 1)."""
# no `from __future__ import annotations`: FastAPI must see the real Request class in route signatures

import importlib
import json
import os
from pathlib import Path

from .editor_common import add_script_injection, asset, deck_and_pdf, guard
from .geometry import geometry

HERE = Path(__file__).resolve().parent


def build_router(deck_module):
    from fastapi import APIRouter, Request
    from fastapi.responses import JSONResponse, Response

    router = APIRouter()

    @router.get("/api/editor/mag/safezone.js")
    async def script():
        return Response(asset("safezone.js"), media_type="application/javascript; charset=utf-8")

    @router.get("/api/editor/mag/safezone/{order_ref}")
    async def safezone(order_ref: str, request: Request):
        await guard(request)
        deck, _ = deck_and_pdf(deck_module.locate(order_ref))
        if deck is None or not Path(deck).is_file():
            return JSONResponse({"ok": False, "reason": "deck not found"}, status_code=404)
        safe_mm = float(os.environ.get("MODULEX_MAG_SAFE_MM", "5") or 5)
        return {"ok": True, **geometry(Path(deck), safe_mm=safe_mm)}

    return router


def mount(app) -> None:
    cfg = json.loads((HERE / "mag_config.json").read_text(encoding="utf-8"))
    app.include_router(build_router(importlib.import_module(cfg["deck_module"])))
    add_script_injection(app, "/api/editor/mag/safezone.js")
