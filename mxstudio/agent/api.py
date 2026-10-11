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

    # -- Claude Desktop connection (human clicks only; these are not agent tools) ----------
    def _entry() -> dict:
        from mxstudio.mcp.server import client_config  # noqa: PLC0415
        return client_config()["mcpServers"]["modulex-studio"]

    def _desktop(call):
        from mxstudio.mcp.clients import ConfigProblem  # noqa: PLC0415
        try:
            return call()
        except ConfigProblem as exc:
            raise HTTPException(409, {"code": "CONFIG_PROBLEM", "ar": exc.ar, "en": exc.en}) from exc

    @app.get("/api/mcp/claude-desktop")
    def desktop_status():
        from mxstudio.mcp import clients  # noqa: PLC0415
        return _desktop(lambda: clients.status(_entry()))

    @app.post("/api/mcp/claude-desktop/install")
    def desktop_install(request: Request):
        from mxstudio.mcp import clients  # noqa: PLC0415
        app.state.human(request)
        return _desktop(lambda: clients.install(_entry()))

    @app.post("/api/mcp/claude-desktop/remove")
    def desktop_remove(request: Request):
        from mxstudio.mcp import clients  # noqa: PLC0415
        app.state.human(request)
        return _desktop(clients.remove)

    @app.post("/api/mcp/self-test")
    def mcp_self_test(request: Request):
        from mxstudio.mcp import clients  # noqa: PLC0415
        app.state.human(request)
        result = clients.self_test(_entry())
        clients.write_state(state.home, last_self_test=result)
        return result

    @app.get("/api/mcp/health")
    def mcp_health():
        from mxstudio.mcp.heal import health  # noqa: PLC0415
        return health(state.home)

    @app.post("/api/mcp/heal")
    def mcp_heal(request: Request):
        from mxstudio.mcp.heal import heal_all  # noqa: PLC0415
        app.state.human(request)
        return heal_all(state, app, workspace=state.workspace.root)

    @app.post("/api/mcp/restart-claude")
    async def mcp_restart_claude(request: Request):
        from mxstudio.mcp import clients  # noqa: PLC0415
        app.state.human(request)
        body = await request.json() if (await request.body()) else {}
        if not body.get("confirm"):  # any conversation running in Claude Desktop is interrupted: ask first
            return {"needs_confirm": True, "ar": "ده هيقفل Claude Desktop ويفتحه تاني — أي رد شغّال فيه هيقف. أكمّل؟",
                    "en": "This quits and reopens Claude Desktop; a reply in progress there stops. Continue?"}
        return clients.restart_claude()

    # -- the stage: the template being worked on ----------------------------------------------------------
    @app.get("/api/studio/current")
    def studio_current(key: str = ""):
        record = state.workspace.get("template_set", key) if key else state.workspace.latest("template_set")
        if record is None:
            return {"story_key": None, "pages": []}
        body = record["body"]
        story = body.get("story") or {}
        validation = body.get("validation") or {}
        variants = validation.get("variants") or {}
        pages = []
        for index, page in enumerate(story.get("pages") or []):
            texts = page.get("texts") or {}
            text = texts.get("ar_girl") or texts.get("ar_boy") or next(iter(texts.values()), "")
            pages.append({"index": index, "number": index + 1, "kind": page.get("kind"), "text": text[:220],
                          "name_style": page.get("name_style"), "rotate": page.get("rotate"),
                          "text_box": page.get("text_box"), "has_art": bool(page.get("art"))})
        return {"story_key": record["key"], "version": record["version"], "approved": record["approved"],
                "title": (story.get("title") or {}).get("ar") or record["key"], "page": story.get("page", "portrait"),
                "layout": story.get("layout", "classic"), "ok": validation.get("ok"),
                "variants_ok": sum(1 for v in variants.values() if v.get("ok")), "variants": len(variants),
                "preview_sha": record["blobs"].get("contact_sheet.png"), "pages": pages,
                "keys": state.workspace.keys("template_set")}

    # -- «الوارد»: pictures for Claude Desktop ---------------------------------------------------------
    @app.get("/api/inbox")
    def inbox_list():
        from mxstudio.agent import inbox  # noqa: PLC0415
        return {"folder": str(inbox.inbox_dir(state.workspace.root)), "pictures": inbox.list_inbox(state.workspace.root)}

    @app.post("/api/inbox")
    async def inbox_add(request: Request):
        from mxstudio.agent import inbox  # noqa: PLC0415
        body = await request.json()
        try:
            data = base64.b64decode(str(body.get("data_b64", "")), validate=True)
            path = inbox.save_to_inbox(state.workspace.root, data, str(body.get("name", "")))
            reference = studio.add_reference(state, data, path.name, "inbox")
        except (binascii.Error, ImageRejected) as exc:
            raise HTTPException(400, {"code": "BAD_IMAGE", "ar": "الملف ده مش صورة سليمة (PNG/JPEG/WebP/GIF).",
                                      "en": str(exc)}) from exc
        return {"ok": True, "name": path.name, "reference": reference}

    # -- requests prepared here, run from Claude Desktop --------------------------------------------
    def _requests():
        from mxstudio.agent.inbox import RequestStore  # noqa: PLC0415
        return RequestStore(state.home / "requests.sqlite3")

    @app.get("/api/requests")
    def requests_list(status: str = "all"):
        return {"requests": _requests().list(None if status == "all" else status)}

    @app.post("/api/requests")
    async def requests_add(request: Request):
        from mxstudio.agent.inbox import InboxError  # noqa: PLC0415
        app.state.human(request)
        body = await request.json()
        try:
            item = _requests().add(str(body.get("text", "")), [str(s) for s in body.get("image_shas") or []][:6],
                                   [str(n) for n in body.get("inbox_names") or []][:6])
        except InboxError as exc:
            raise HTTPException(400, exc.as_dict()) from exc
        return {"ok": True, "request": item,
                "ar": f"الطلب {item['id']} اتحفظ. افتح Claude Desktop واكتب: «نفّذ طلبات الاستوديو».",
                "en": f"Request {item['id']} saved. In Claude Desktop write: “run the Studio requests”."}

    # -- model qualification (a human click; it calls the configured model) ---------------
    @app.post("/api/agent/qualify")
    def qualify_model():
        from mxstudio.agent.evals.cli import qualify  # noqa: PLC0415
        return qualify(_provider(state), state.settings)

    @app.get("/api/agent/model-check")
    def model_check_state():
        from mxstudio.agent import model_check  # noqa: PLC0415
        return model_check.explain(state) | {"check": model_check.read(state.home)}

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
