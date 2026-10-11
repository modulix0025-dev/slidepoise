"""Core tools every installation has. Feature areas register more tools at start-up
(`mxstudio.app.features.register_feature_tools`)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from mxstudio.agent.tools import Tool, ToolError

if TYPE_CHECKING:  # pragma: no cover
    from mxstudio.app.state import AppState


def register_core_tools(state: "AppState") -> None:
    tools = state.tools

    tools.register(Tool(
        name="workspace.list", description_ar="اعرض العناصر المحفوظة من نوع معيّن.",
        description_en="List workspace records of a kind.",
        schema={"type": "object", "properties": {"kind": {"type": "string", "minLength": 1}},
                "required": ["kind"], "additionalProperties": False},
        handler=lambda a: {"keys": state.workspace.keys(a["kind"])}, tags=["workspace"]))

    tools.register(Tool(
        name="workspace.history", description_ar="اعرض نسخ عنصر.", description_en="Version history of a record.",
        schema={"type": "object", "properties": {"kind": {"type": "string"}, "key": {"type": "string"}},
                "required": ["kind", "key"], "additionalProperties": False},
        handler=lambda a: {"versions": [{k: v for k, v in r.items() if k != "body"}
                                        for r in state.workspace.history(a["kind"], a["key"])]}, tags=["workspace"]))

    def approve(args: dict) -> dict:
        record = state.workspace.approve(args["kind"], args["key"], args["version"], args["approved_by"])
        return {"approved": True, "version": record["version"]}

    tools.register(Tool(
        name="workspace.approve", description_ar="اعتماد نسخة (مالهاش رجوع).",
        description_en="Approve (freeze) a version — irreversible.",
        schema={"type": "object", "properties": {"kind": {"type": "string"}, "key": {"type": "string"},
                                                 "version": {"type": "integer", "minimum": 1},
                                                 "approved_by": {"type": "string", "minLength": 1}},
                "required": ["kind", "key", "version", "approved_by"], "additionalProperties": False},
        handler=approve, irreversible=True, tags=["workspace", "approval"]))

    tools.register(Tool(
        name="jobs.list", description_ar="اعرض المهام.", description_en="List background jobs.",
        schema={"type": "object", "properties": {"state": {"enum": ["queued", "running", "done", "failed",
                                                                    "cancelled"]}},
                "additionalProperties": False},
        handler=lambda a: {"jobs": state.queue.list(a.get("state"))}, tags=["jobs"]))

    tools.register(Tool(
        name="budget.status", description_ar="مصاريف الذكاء الاصطناعي النهارده.", description_en="AI spend today.",
        schema={"type": "object", "additionalProperties": False},
        handler=lambda a: state.budget.dashboard(), tags=["budget"]))

    def refuse_photo_alteration(args: dict) -> dict:
        raise ToolError("FORBIDDEN_BY_OPERATOR_RULE", "صور العملاء عمرها ما تتعدّل بالذكاء الاصطناعي — ده قرار ثابت.",
                        "customer photos are never altered with AI (operator rule)")

    tools.register(Tool(
        name="customer_photo.ai_edit",
        description_ar="ممنوع: صور العملاء عمرها ما تتعدّل بالذكاء الاصطناعي — الأداة موجودة عشان ترفض دايمًا.",
        description_en="Forbidden: customer photos are never AI-altered. This tool exists only to refuse.",
        schema={"type": "object"}, handler=refuse_photo_alteration, irreversible=False, tags=["safety"]))
