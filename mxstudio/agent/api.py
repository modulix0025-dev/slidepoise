"""Agent routes: «ابدأ هنا» chat (text + reference images + revisions), pending approvals, manual, evals.

Every POST here goes through the server's CSRF guard (Studio window only). Decisions on
pending approvals need the human UI session; the model has no route to make them.
"""
from __future__ import annotations

import base64
import binascii
import json

from fastapi import HTTPException, Request, Response

from mxstudio.agent.tools import Tool, ToolError


def _provider(state):
    from mxstudio.providers import ProviderError, build_text_provider  # noqa: PLC0415
    settings = state.settings.load()
    try:
        return build_text_provider(settings["providers"]["text_vision"], state.secrets.get("provider.text_vision"))
    except ProviderError as exc:
        raise HTTPException(409, {"code": "NO_MODEL", "en": f"no text/vision model configured: {exc}",
                                  "ar": "مفيش موديل متظبط — من «الإعدادات» اختار Claude وحط المفتاح، "
                                        "أو حط عنوان موديل الـGPU بتاعك."}) from exc


def register(app, state) -> None:
    from mxstudio.agent import studio  # noqa: PLC0415
    from mxstudio.agent.images import ImageRejected  # noqa: PLC0415
    from mxstudio.agent.manual import build_manual  # noqa: PLC0415
    from mxstudio.providers.base import ProviderError, image_media_type  # noqa: PLC0415

    # -- tools the agent uses for the operator's uploads ------------------------------
    state.tools.register(Tool(
        "studio.references", "اعرض صور التصميم اللي المشغّل رفعها.",
        "List the design reference images the operator uploaded (sha256, size, note).",
        {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100}},
         "additionalProperties": False},
        lambda args: {"references": studio.list_references(state, int(args.get("limit", 30)))}, tags=["studio"]))

    # -- uploads & pictures ----------------------------------------------------------
    @app.post("/api/uploads")
    async def upload(request: Request):
        body = await request.json()
        try:
            data = base64.b64decode(str(body.get("data_b64", "")), validate=True)
            return {"ok": True, "reference": studio.add_reference(state, data, body.get("name", ""),
                                                                  body.get("note", ""))}
        except (binascii.Error, ImageRejected) as exc:
            raise HTTPException(400, {"code": "BAD_IMAGE", "ar": "الملف ده مش صورة سليمة (PNG/JPEG/WebP/GIF).",
                                      "en": str(exc)}) from exc

    @app.get("/api/references")
    def references():
        return {"references": studio.list_references(state)}

    @app.get("/api/blobs/{sha}")
    def blob(sha: str):
        try:
            path = state.workspace.blob_path(sha)
        except ValueError as exc:
            raise HTTPException(404) from exc
        if not path.is_file():
            raise HTTPException(404)
        data = path.read_bytes()
        try:
            media = image_media_type(data[:16])
        except ProviderError as exc:  # only pictures are served here
            raise HTTPException(404) from exc
        return Response(data, media_type=media, headers={"Cache-Control": "private, max-age=3600"})

    # -- pending approvals (irreversible requests from any agent, decided by the human) --
    @app.get("/api/pending")
    def pending(status: str = "pending"):
        return {"pending": state.tools.pending.list(None if status == "all" else status)}

    @app.post("/api/pending/{pending_id}/decide")
    async def decide(pending_id: str, request: Request):
        body = await request.json()
        try:
            return state.tools.decide(pending_id, bool(body.get("approve")), app.state.human(request))
        except ToolError as exc:
            raise HTTPException(409, exc.as_dict()) from exc

    # -- conversations -------------------------------------------------------------------
    @app.get("/api/agent/conversations")
    def conversations():
        return {"conversations": studio.list_conversations(state)}

    @app.post("/api/agent/conversations")
    async def create_conversation(request: Request):
        body = await request.json()
        return {"id": studio.new_conversation(state, str(body.get("title", "")))}

    @app.get("/api/agent/conversations/{conversation_id}")
    def conversation(conversation_id: str):
        shown = studio.transcript(state, conversation_id)
        if shown is None:
            raise HTTPException(404)
        return shown

    @app.post("/api/agent/conversations/{conversation_id}/messages")
    async def message(conversation_id: str, request: Request):
        body = await request.json()
        text = str(body.get("text", "")).strip()[:8000]
        refs = [str(s) for s in body.get("references") or []][:6]
        if not text and not refs:
            raise HTTPException(400, {"code": "EMPTY", "ar": "اكتب طلبك أو ارفع صورة.", "en": "empty message"})
        provider = _provider(state)
        try:
            return studio.chat_turn(state, app, provider, conversation_id, text or "(see the image)", refs)
        except KeyError as exc:
            raise HTTPException(404) from exc
        except ProviderError as exc:
            raise HTTPException(502, {"code": "MODEL_ERROR", "ar": "الموديل مارد صح — جرّب تاني.",
                                      "en": str(exc)[:300]}) from exc

    @app.get("/api/mcp/config")
    def mcp_config():
        from mxstudio.mcp.server import client_config  # noqa: PLC0415
        return {"config": client_config()}

    # -- model qualification (a human click; it calls the configured model) ---------------
    @app.post("/api/agent/qualify")
    def qualify_model():
        from mxstudio.agent.evals.cli import qualify  # noqa: PLC0415
        return qualify(_provider(state), state.settings)

    # -- manual, one-shot run, eval summary ---------------------------------------------
    @app.get("/api/agent/manual")
    def manual():
        built = build_manual(state, app)
        return {"sha256": built["sha256"], "sections": [{"id": s["id"], "title": s["title"]} for s in built["sections"]]}

    @app.post("/api/agent/run")
    async def run(request: Request):
        from mxstudio.agent import loop  # noqa: PLC0415
        body = await request.json()
        provider = _provider(state)
        mode = state.settings.load()["agent"].get("mode", "suggest_only")
        task = str(body.get("task", ""))[:4000]
        if mode != "full":
            task = ("SUGGESTION-ONLY MODE: do not call any tool that changes state; reply with a plan and final.\n"
                    + task)
        result = loop.run(state, provider, task, build_manual(state, app))
        return {"mode": mode, "status": result.status, "plan": result.plan, "report": result.report,
                "pending_confirmation": result.pending, "flags": result.flags}

    @app.get("/api/agent/summary")
    def summary():
        report = state.home / "evals_report.json"
        facts = json.loads(report.read_text(encoding="utf-8"))["summary"] if report.is_file() else \
            {"note": "run `python -m mxstudio evals run --report <app_home>/evals_report.json`"}
        return {"facts": {"mode": state.settings.load()["agent"].get("mode"), "evals": facts,
                          "pending_approvals": len(state.tools.pending.list())}, "actions": []}
