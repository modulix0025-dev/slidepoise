"""Mount the P-PROOF routes (called from the hook in OM's app module only when the flag is 1)."""
# no `from __future__ import annotations`: FastAPI must see the real Request class in route signatures

import importlib
import json
from pathlib import Path

from .approval import record, status
from .editor_common import add_script_injection, asset, deck_and_pdf, guard

HERE = Path(__file__).resolve().parent


def build_router(deck_module, print_service):
    from fastapi import APIRouter, Request
    from fastapi.responses import JSONResponse, Response

    router = APIRouter()

    @router.get("/api/editor/mag/proof.js")
    async def script():
        return Response(asset("proof.js"), media_type="application/javascript; charset=utf-8")

    def _pdf(order_ref: str):
        _, pdf = deck_and_pdf(deck_module.locate(order_ref))
        return pdf if pdf is not None and Path(pdf).is_file() else None

    @router.get("/api/editor/mag/proof/{order_ref}")
    async def get_status(order_ref: str, request: Request):
        await guard(request)
        pdf = _pdf(order_ref)
        if pdf is None:
            return JSONResponse({"ok": False, "reason": "pdf not found"}, status_code=404)
        return {"ok": True, **status(pdf)}

    @router.post("/api/editor/mag/proof/{order_ref}/approve")
    async def approve(order_ref: str, request: Request):
        await guard(request)
        pdf = _pdf(order_ref)
        if pdf is None:
            return JSONResponse({"ok": False, "reason": "pdf not found"}, status_code=404)
        try:
            body = json.loads((await request.body()) or b"{}")
        except ValueError:
            return JSONResponse({"ok": False, "reason": "bad json"}, status_code=400)
        version = str(body.get("version", "")).strip()
        if not version:
            return JSONResponse({"ok": False, "reason": "version required"}, status_code=422)
        return {"ok": True, "approval": record(pdf, version=version, order_ref=order_ref, print_service=print_service)}

    return router


def mount(app) -> None:
    cfg = json.loads((HERE / "mag_config.json").read_text(encoding="utf-8"))
    print_service = importlib.import_module(cfg["print_service_module"])
    app.include_router(build_router(importlib.import_module(cfg["deck_module"]), print_service))
    add_script_injection(app, "/api/editor/mag/proof.js")
