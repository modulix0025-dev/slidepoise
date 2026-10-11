"""Agent routes: manual, a run endpoint (needs a qualified model), and the last eval report."""
from __future__ import annotations

import json

from fastapi import HTTPException, Request


def register(app, state) -> None:
    from mxstudio.agent.manual import build_manual  # noqa: PLC0415

    @app.get("/api/agent/manual")
    def manual():
        built = build_manual(state, app)
        return {"sha256": built["sha256"], "sections": [{"id": s["id"], "title": s["title"]} for s in built["sections"]]}

    @app.post("/api/agent/run")
    async def run(request: Request):
        from mxstudio.agent import loop  # noqa: PLC0415
        from mxstudio.providers import ProviderError, build_text_provider  # noqa: PLC0415
        body = await request.json()
        settings = state.settings.load()
        mode = settings["agent"].get("mode", "suggest_only")
        try:
            provider = build_text_provider(settings["providers"]["text_vision"],
                                           state.secrets.get("provider.text_vision"))
        except ProviderError as exc:
            raise HTTPException(409, f"no text/vision model configured: {exc}") from exc
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
        return {"facts": {"mode": state.settings.load()["agent"].get("mode"), "evals": facts}, "actions": []}
