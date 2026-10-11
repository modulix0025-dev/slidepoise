"""FastAPI router for the M1/M2/M6/M7 receivers (mounted only when MODULEX_MAG_RECEIVERS=1).

Every route — reads included — passes the :class:`SignedRequestGate` first; the signed PATH is
``request.url.path`` (path only, no query), exactly as the contract requires.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from . import CONTRACT_VERSION, ROUTES, SCHEMA_FILES
from .ingest import SCHEMAS_DIR, ingest
from .signing_gate import SignedRequestGate
from .store import CandidateStore

PREFIX = "/internal/mag/v1"


def build_router(*, kinds: tuple[str, ...], gate: SignedRequestGate, store: CandidateStore,
                 schemas_dir: Path = SCHEMAS_DIR, activator: Callable[[dict, Path], dict] | None = None,
                 system: str = "") -> APIRouter:
    router = APIRouter()

    async def _gate(request: Request) -> tuple[bytes, JSONResponse | None]:
        body = await request.body()
        res = gate.check(request.method, request.url.path, body, request.headers)
        if not res.ok:
            return body, JSONResponse({"ok": False, "reason": res.reason}, status_code=res.status)
        return body, None

    @router.get(f"{PREFIX}/health")
    async def health(request: Request):
        _, refused = await _gate(request)
        if refused:
            return refused
        return {"ok": True, "contract": CONTRACT_VERSION, "system": system, "kinds": list(kinds)}

    @router.get(f"{PREFIX}/contract")
    async def contract(request: Request):
        _, refused = await _gate(request)
        if refused:
            return refused
        schemas = {k: hashlib.sha256((Path(schemas_dir) / SCHEMA_FILES[k]).read_bytes()).hexdigest()
                   for k in kinds}
        return {"version": CONTRACT_VERSION, "schemas_sha256": schemas, "kinds": list(kinds),
                "key_ids": [gate.signing.DEFAULT_KEY_ID]}

    def _make_post(kind: str):
        async def receive(request: Request):
            body, refused = await _gate(request)
            if refused:
                return refused
            status, payload = ingest(kind, body, store=store, schemas_dir=schemas_dir, source="http")
            return JSONResponse(payload, status_code=status)
        return receive

    for kind in kinds:
        router.add_api_route(f"{PREFIX}/{ROUTES[kind]}", _make_post(kind), methods=["POST"],
                             name=f"mag_receive_{kind}")

    @router.get(f"{PREFIX}/candidates/{{kind}}")
    async def candidates(kind: str, request: Request):
        _, refused = await _gate(request)
        if refused:
            return refused
        if kind not in kinds:
            return JSONResponse({"ok": False, "reason": "unknown kind"}, status_code=404)
        return {"ok": True, "candidates": store.list(kind)}

    if "m1" in kinds:
        @router.post(f"{PREFIX}/m1/candidates/{{cid}}/activate")
        async def activate(cid: str, request: Request):
            body, refused = await _gate(request)
            if refused:
                return refused
            if activator is None:
                return JSONResponse({"ok": False, "reason": "activation is not available on this system"},
                                    status_code=501)
            try:
                code = json.loads(body or b"{}").get("operator_confirmation", "")
                _, raw, cdir = store.get("m1", cid)
            except (ValueError, OSError, KeyError):
                return JSONResponse({"ok": False, "reason": "unknown candidate"}, status_code=404)
            if not store.check_confirmation("m1", cid, code):
                return JSONResponse({"ok": False, "reason": "operator confirmation code required"}, status_code=403)
            result: dict[str, Any] = activator(json.loads(raw), cdir)
            store.mark("m1", cid, "activated" if result.get("ok") else "activation_blocked",
                       result=result.get("status"))
            return JSONResponse(result, status_code=200 if result.get("ok") else 409)

    return router
