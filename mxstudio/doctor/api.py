"""Doctor routes: every check with its «إصلاح» action; fixes that elevate need explicit consent."""
from __future__ import annotations

from fastapi import Request


def register(app, state) -> None:
    from mxstudio.agent.tools import Tool  # noqa: PLC0415
    from mxstudio.doctor.checks import run_all, summary  # noqa: PLC0415
    from mxstudio.doctor.fixers import run_fix  # noqa: PLC0415

    @app.get("/api/doctor/summary")
    def doctor_summary():
        results = run_all()
        return {"facts": {"summary": summary(results), "checks": results},
                "actions": [{"label_ar": f"إصلاح: {r['ar']}", "label_en": f"Fix: {r['en']}", "tool": "doctor.fix",
                             "args": {"fix_id": r["fix_id"]}} for r in results if r.get("fix_id") and not r.get("ok")]}

    @app.post("/api/doctor/fix")
    async def doctor_fix(request: Request):
        body = await request.json()
        return run_fix(str(body.get("fix_id")), consent=bool(body.get("consent", False)))

    state.tools.register(Tool(
        name="doctor.run", description_ar="شغّل الفحص الشامل للجهاز.", description_en="Run all Doctor checks.",
        schema={"type": "object", "additionalProperties": False},
        handler=lambda a: {"summary": summary(results := run_all()), "checks": results}, tags=["doctor"]))
    state.tools.register(Tool(
        name="doctor.fix", description_ar="نفّذ إصلاح (اللي محتاج صلاحيات مدير بيطلب موافقتك).",
        description_en="Run a Doctor fix (elevating fixes ask for consent).",
        schema={"type": "object", "properties": {"fix_id": {"type": "string"}}, "required": ["fix_id"],
                "additionalProperties": False},
        handler=lambda a: run_fix(a["fix_id"], consent=False), tags=["doctor"]))
