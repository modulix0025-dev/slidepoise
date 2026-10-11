"""Mount the P-PREVIEW route (called from the hook in OM's app module only when the flag is 1)."""
# no `from __future__ import annotations`: FastAPI must see the real Request class in route signatures

import importlib
import json
from pathlib import Path

from .editor_common import deck_and_pdf, guard
from .preview import cached_preview

HERE = Path(__file__).resolve().parent


def build_router(deck_module, cache_dir: Path):
    from fastapi import APIRouter, Request
    from fastapi.responses import FileResponse, JSONResponse
    from starlette.concurrency import run_in_threadpool

    router = APIRouter()

    @router.get("/api/editor/mag/preview/{order_ref}/{slide_no}")
    async def preview(order_ref: str, slide_no: int, request: Request):
        await guard(request)
        deck, _ = deck_and_pdf(deck_module.locate(order_ref))
        if deck is None or not Path(deck).is_file():
            return JSONResponse({"ok": False, "reason": "deck not found"}, status_code=404)
        try:
            pdf = await run_in_threadpool(cached_preview, Path(deck), slide_no, cache_dir, deck_module.export_pdf)
        except ValueError as exc:
            return JSONResponse({"ok": False, "reason": str(exc)}, status_code=400)
        return FileResponse(str(pdf), media_type="application/pdf")

    return router


def mount(app) -> None:
    cfg = json.loads((HERE / "mag_config.json").read_text(encoding="utf-8"))
    root = HERE
    for _ in range(int(cfg.get("system_root_up", 2))):
        root = root.parent
    app.include_router(build_router(importlib.import_module(cfg["deck_module"]),
                                    root / cfg.get("cache_dir", "mag_cache/preview")))
