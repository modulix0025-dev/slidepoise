"""QA gate in the Studio: run the same pure gate the operator's systems use, on any deck + PDF."""
from __future__ import annotations

import sys
from pathlib import Path

from mxstudio.agent.tools import Tool, ToolError

MXLIBS = Path(__file__).resolve().parents[2] / "mxlibs"
if str(MXLIBS) not in sys.path:
    sys.path.insert(0, str(MXLIBS))


def register(app, state) -> None:
    from mx_qagate import BLOCKERS, run_gate  # noqa: PLC0415

    def gate(args: dict) -> dict:
        deck, pdf = Path(args["deck"]), Path(args["pdf"])
        if not deck.is_file() or not pdf.is_file():
            raise ToolError("FILE_NOT_FOUND", "الملف مش موجود.", "deck or pdf not found")
        return run_gate(deck, pdf, approved_pages=int(args["approved_pages"]), child_name=args.get("child_name", ""))

    state.tools.register(Tool(
        name="qa.run_gate", description_ar="فحص المجلة قبل الطباعة (موانع واضحة بالاسم).",
        description_en="Run the pre-print QA gate on a deck + PDF.",
        schema={"type": "object", "properties": {"deck": {"type": "string"}, "pdf": {"type": "string"},
                                                 "approved_pages": {"type": "integer", "minimum": 1},
                                                 "child_name": {"type": "string"}},
                "required": ["deck", "pdf", "approved_pages"], "additionalProperties": False},
        handler=gate, tags=["qa"]))

    @app.get("/api/qa/summary")
    def summary():
        return {"facts": {"blockers": {code: {"ar": ar, "en": en} for code, (ar, en) in BLOCKERS.items()},
                          "advisory": "AI checks are advisory and never change a print job's state"},
                "actions": []}
