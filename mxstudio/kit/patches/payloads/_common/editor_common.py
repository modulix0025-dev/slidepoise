"""Helpers shared by the OM editor extensions (copied into each payload; no cross-payload imports).

Rules:
* default-deny: without ``MODULEX_MAG_EDITOR_AUTH=<module>:<callable>`` (the editor's own access
  check, chosen on device from the probe's route map) the extension answers loopback clients only;
* UI additions reach the editor page through a response middleware that inserts one
  ``<script>`` tag — no HTML/JS file of the operator (and nothing under any ``static`` folder) is edited;
* OM's ``locate(order)`` result is read defensively: the first ``.pptx`` and ``.pdf`` paths found.
"""
from __future__ import annotations

import importlib
import inspect
import os
from pathlib import Path
from typing import Any

LOOPBACK = {"127.0.0.1", "::1", "localhost", "testclient"}


def flag(name: str) -> bool:
    return os.environ.get(name, "0").strip() == "1"


async def guard(request) -> None:
    from fastapi import HTTPException

    spec = os.environ.get("MODULEX_MAG_EDITOR_AUTH", "").strip()
    if spec:
        module, _, attr = spec.partition(":")
        check = getattr(importlib.import_module(module), attr)
        verdict = check(request)
        if inspect.isawaitable(verdict):
            verdict = await verdict
        if verdict is False:
            raise HTTPException(status_code=403, detail="غير مسموح · not allowed")
        return
    host = request.client.host if request.client else ""
    if host not in LOOPBACK:
        raise HTTPException(status_code=403, detail="الإضافة دي لسه متقفلة على الجهاز المحلي · loopback only "
                                                    "until MODULEX_MAG_EDITOR_AUTH is configured")


def _paths(obj: Any, acc: list[Path], depth: int = 0) -> None:
    if depth > 4 or obj is None:
        return
    if isinstance(obj, (str, Path)):
        p = Path(obj)
        if p.suffix.lower() in (".pptx", ".pdf"):
            acc.append(p)
        return
    if isinstance(obj, dict):
        for v in obj.values():
            _paths(v, acc, depth + 1)
        return
    if isinstance(obj, (list, tuple, set)):
        for v in obj:
            _paths(v, acc, depth + 1)
        return
    for attr in ("deck", "deck_path", "pptx", "pdf", "pdf_path", "path"):
        if hasattr(obj, attr):
            _paths(getattr(obj, attr), acc, depth + 1)


def deck_and_pdf(located: Any) -> tuple[Path | None, Path | None]:
    acc: list[Path] = []
    _paths(located, acc)
    deck = next((p for p in acc if p.suffix.lower() == ".pptx"), None)
    pdf = next((p for p in acc if p.suffix.lower() == ".pdf"), None)
    return deck, pdf


def add_script_injection(app, script_url: str, page_prefix: str | None = None) -> None:
    """Insert ``<script src=script_url defer>`` before ``</body>`` of editor HTML pages."""
    from starlette.responses import Response

    prefix = page_prefix or os.environ.get("MODULEX_MAG_EDITOR_PAGE_PREFIX", "/editor")
    tag = f'<script src="{script_url}" defer></script>'.encode()

    @app.middleware("http")
    async def _mag_inject(request, call_next):
        response = await call_next(request)
        if not request.url.path.startswith(prefix) or "text/html" not in response.headers.get("content-type", ""):
            return response
        body = b"".join([chunk async for chunk in response.body_iterator])
        if tag not in body and b"</body>" in body:
            body = body.replace(b"</body>", tag + b"</body>", 1)
        new = Response(content=body, status_code=response.status_code)
        new.raw_headers = [(k, v) for k, v in response.raw_headers if k.lower() != b"content-length"] + \
            [(b"content-length", str(len(body)).encode("ascii"))]
        return new


def asset(name: str) -> bytes:
    return (Path(__file__).resolve().parent / name).read_bytes()
