"""Fonts routes and agent tools: type themes, typography defaults and font eligibility (facts, named findings)."""
from __future__ import annotations

import json

from mxstudio.agent.tools import Tool, ToolError


def register(app, state) -> None:
    from mxstudio.fonts import themes as themes_mod  # noqa: PLC0415
    from mxstudio.fonts import typography  # noqa: PLC0415
    from mxstudio.fonts.paths import QA_JSON  # noqa: PLC0415

    def qa() -> dict:
        return json.loads(QA_JSON.read_text(encoding="utf-8"))

    def list_themes(args: dict) -> dict:
        wanted = str(args.get("query", "")).lower()
        found = [t for t in themes_mod.load_themes()["themes"]
                 if not wanted or wanted in t["id"].lower() or wanted in t.get("name_en", "").lower()
                 or wanted in t.get("name_ar", "")]
        return {"count": len(found), "themes": found[: int(args.get("limit", 40))]}

    def role_defaults(args: dict) -> dict:
        try:
            return typography.defaults(args["role"], args["page"], args["age"], args["script"]).as_dict()
        except ValueError as exc:
            raise ToolError("BAD_ARGS", "الدور أو المقاس أو السن مش معروف.", str(exc)) from exc

    def allowed(args: dict) -> dict:
        if args["role"] not in typography.ROLES:
            raise ToolError("BAD_ARGS", "الدور مش معروف.", f"role must be one of {typography.ROLES}")
        ok, reasons = typography.font_allowed(args["family"], args["role"], args["script"], qa(),
                                              vowelized=bool(args.get("vowelized")),
                                              lam_prefix=bool(args.get("lam_prefix")))
        return {"family": args["family"], "role": args["role"], "allowed": ok, "findings": reasons}

    enum = {"type": "string"}
    state.tools.register(Tool("fonts.list_themes", "اعرض ثيمات الخطوط (عربي ↔ إنجليزي).",
                              "List type themes (Arabic ↔ English pairings).",
                              {"type": "object",
                               "properties": {"query": enum, "limit": {"type": "integer", "minimum": 1}},
                               "additionalProperties": False}, list_themes, tags=["fonts"]))
    state.tools.register(Tool("fonts.role_defaults", "مقاسات البداية للدور حسب المقاس والسن.",
                              "Starting size range for a role × page × age × script.",
                              {"type": "object", "properties": {"role": {"enum": list(typography.ROLES)},
                                                                "page": {"enum": list(typography.PAGES)},
                                                                "age": {"enum": list(typography.AGES)},
                                                                "script": {"enum": list(typography.SCRIPTS)}},
                               "required": ["role", "page", "age", "script"], "additionalProperties": False},
                              role_defaults, tags=["fonts"]))
    state.tools.register(Tool("fonts.check_allowed", "ينفع الخط ده للدور ده في الطباعة؟",
                              "Is this font certified for this role in print?",
                              {"type": "object", "properties": {"family": enum, "role": enum,
                                                                "script": {"enum": list(typography.SCRIPTS)},
                                                                "vowelized": {"type": "boolean"},
                                                                "lam_prefix": {"type": "boolean"}},
                               "required": ["family", "role", "script"], "additionalProperties": False},
                              allowed, tags=["fonts"]))

    @app.get("/api/fonts/summary")
    def summary():
        status = qa()
        return {"facts": {"counts": status.get("counts", {}), "themes": len(themes_mod.load_themes()["themes"]),
                          "rule": "only certified_print fonts in print; on-device export proof is pending"},
                "actions": [{"label_ar": "ثيمات الخطوط", "label_en": "Type themes", "tool": "fonts.list_themes",
                             "args": {}}]}
