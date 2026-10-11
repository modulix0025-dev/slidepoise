"""Local HTTP server for the Studio UI and the agent.

* Loopback only: any request whose peer is not 127.0.0.1 / ::1 is refused (403),
  whatever address the socket was bound to.
* The UI gets a session cookie and a CSRF token; every mutating request must
  carry the token in ``X-MXS-CSRF``.
* Confirmation tokens for irreversible tools are minted only through the human
  session (`/api/confirm`); the agent endpoint can spend a token, never mint one.
* Secrets are write-only: responses show a fingerprint, never the value.
"""
from __future__ import annotations

import hmac
import json
import secrets
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from mxstudio.app.state import AppState
from mxstudio.config import APP_NAME, APP_VERSION

LOOPBACK = {"127.0.0.1", "::1", "localhost"}
UI_DIR = Path(__file__).resolve().parents[1] / "ui"
SESSION_COOKIE = "mxs_session"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
CONTRACTS = Path(__file__).resolve().parents[2] / "contracts" / "mag" / "v1"


def create_app(state: AppState) -> FastAPI:
    app = FastAPI(title=APP_NAME, version=APP_VERSION, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.mxs = state

    @app.middleware("http")
    async def guard(request: Request, call_next):
        peer = request.client.host if request.client else ""
        if peer not in LOOPBACK:
            return JSONResponse({"ok": False, "code": "LOOPBACK_ONLY", "ar": "السيرفر ده للجهاز ده بس."}, status_code=403)
        if request.method not in SAFE_METHODS and request.url.path.startswith("/api/") \
                and request.url.path not in {"/api/shutdown"}:
            session = request.cookies.get(SESSION_COOKIE, "")
            expected = state.sessions.get(session)
            supplied = request.headers.get("X-MXS-CSRF", "")
            if not expected or not hmac.compare_digest(expected, supplied):
                return JSONResponse({"ok": False, "code": "CSRF", "ar": "الطلب ده مش جاي من شاشة الاستوديو."},
                                    status_code=403)
        return await call_next(request)

    def human(request: Request) -> str:
        session = request.cookies.get(SESSION_COOKIE, "")
        if session not in state.sessions:
            raise HTTPException(403, "no UI session")
        return f"ui:{session[:8]}"

    app.state.human = human  # feature areas (e.g. pending approvals) need the same human identity

    # -- UI ---------------------------------------------------------------
    @app.get("/", response_class=HTMLResponse)
    def index():
        session = secrets.token_urlsafe(18)
        state.sessions[session] = secrets.token_urlsafe(24)
        response = FileResponse(UI_DIR / "index.html", media_type="text/html; charset=utf-8")
        response.set_cookie(SESSION_COOKIE, session, httponly=True, samesite="strict")
        return response

    @app.get("/ui/{name:path}")
    def ui_asset(name: str):
        path = (UI_DIR / name).resolve()
        if UI_DIR.resolve() not in path.parents or not path.is_file():
            raise HTTPException(404)
        return FileResponse(path)

    @app.get("/api/session")
    def session_info(request: Request):
        session = request.cookies.get(SESSION_COOKIE, "")
        if session not in state.sessions:
            raise HTTPException(403, "open the Studio window first")
        return {"csrf": state.sessions[session], "app": APP_NAME, "version": APP_VERSION}

    # -- health & contract (M0) --------------------------------------------
    @app.get("/api/health")
    def health():
        return {"ok": True, "app": APP_NAME, "version": APP_VERSION}

    @app.get("/internal/mag/v1/health")
    def m0_health():
        return {"ok": True, "contract": "mag/v1", "version": APP_VERSION}

    @app.get("/internal/mag/v1/contract")
    def m0_contract():
        schemas = sorted(p.name for p in CONTRACTS.glob("*.schema.json")) if CONTRACTS.is_dir() else []
        return {"contract": "mag/v1", "version": APP_VERSION, "signing": "modulex_signing (vendored, sha-pinned)",
                "schemas": {name.split(".")[0]: f"/internal/mag/v1/schemas/{name}" for name in schemas}}

    @app.get("/internal/mag/v1/schemas/{name}")
    def m0_schema(name: str):
        path = (CONTRACTS / name).resolve()
        if CONTRACTS.resolve() not in path.parents or not path.is_file():
            raise HTTPException(404)
        return json.loads(path.read_text(encoding="utf-8"))

    # -- settings, secrets, providers, budget --------------------------------
    @app.get("/api/settings")
    def get_settings():
        return state.settings.load()

    @app.post("/api/settings")
    async def set_settings(request: Request):
        patch = await request.json()
        if not isinstance(patch, dict):
            raise HTTPException(400, "settings patch must be an object")
        if any(key in json.dumps(patch).lower() for key in ("api_key", "secret")):
            raise HTTPException(400, "keys go to /api/secrets, never into settings")
        return state.settings.update(patch)

    @app.get("/api/secrets")
    def list_secrets():
        return {"secrets": state.secrets.list(), "backend": state.secrets.backend}

    @app.post("/api/secrets/{name}")
    async def set_secret(name: str, request: Request):
        body = await request.json()
        saved = state.secrets.set(name, str(body.get("value", "")))
        if name == "provider.text_vision" and state.settings.load()["providers"]["text_vision"].get("enabled"):
            from mxstudio.agent import model_check  # noqa: PLC0415 - «اختبر الموديل» runs by itself
            saved = dict(saved) | {"model_check_started": model_check.start_check(state)}
        return saved

    @app.delete("/api/secrets/{name}")
    def delete_secret(name: str):
        return {"deleted": state.secrets.delete(name)}

    @app.post("/api/providers/{which}/test")
    def test_provider(which: str):
        from mxstudio.providers import ProviderError, build_image_provider, build_text_provider  # noqa: PLC0415
        config = state.settings.load()["providers"].get(which)
        if config is None:
            raise HTTPException(404, "unknown provider slot")
        try:
            provider = (build_text_provider(config, state.secrets.get(f"provider.{which}"))
                        if which == "text_vision" else build_image_provider(config, manual_dir=state.home / "manual"))
            return provider.test_connection()
        except ProviderError as exc:
            return {"ok": False, "ar": "المزوّد مش متظبط أو مش مسموح.", "detail": str(exc)}

    @app.get("/api/budget")
    def budget():
        return state.budget.dashboard()

    # -- jobs ---------------------------------------------------------------
    @app.get("/api/jobs")
    def jobs(job_state: str | None = None):
        return {"jobs": state.queue.list(job_state)}

    # -- agent tools ---------------------------------------------------------
    @app.get("/api/tools")
    def tools():
        return {"tools": state.tools.specs()}

    @app.post("/api/confirm")
    async def confirm(request: Request):
        body = await request.json()
        token = state.tools.tokens.mint(str(body.get("tool")), body.get("args") or {}, human(request))
        return {"token": token, "expires_in": 600}

    @app.post("/api/tools/{name}")
    async def call_tool(name: str, request: Request):
        body: dict[str, Any] = await request.json()
        actor = str(body.get("actor") or "agent")
        if not actor.startswith(("agent", "ui:")):
            actor = "agent"
        return state.tools.call(name, body.get("args") or {}, actor=actor,
                                confirmation_token=body.get("confirmation_token"))

    @app.get("/api/audit")
    def audit(limit: int = 200):
        return {"entries": state.tools.audit.entries(limit)}

    # -- lifecycle ---------------------------------------------------------
    @app.post("/api/shutdown")
    async def shutdown(request: Request):
        supplied = request.headers.get("X-MXS-Shutdown", "")
        if not hmac.compare_digest(supplied, state.shutdown_token):
            raise HTTPException(403, "bad shutdown token")
        app.state.should_exit = True
        return {"ok": True}

    from mxstudio.app.features import mount_features  # noqa: PLC0415 - feature routers are optional
    mount_features(app, state)
    return app
