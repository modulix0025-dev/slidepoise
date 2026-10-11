"""Factory routes and agent tools."""
from __future__ import annotations

from pathlib import Path

from mxstudio.agent.tools import Tool, ToolError
from mxstudio.factory.demo_story import moon_star_story
from mxstudio.factory.publish import build_pack
from mxstudio.factory.service import build_and_validate, store
from mxstudio.factory.story import Story


def register(app, state) -> None:
    out_root = Path(state.workspace.root) / "factory"

    def build(args: dict) -> dict:
        story = moon_star_story() if args.get("demo") else Story.from_dict(args["story"])
        problems = story.validate()
        if problems:
            raise ToolError("STORY_NOT_READY", "القصة لسه مش جاهزة.", "story is not ready", {"problems": problems})
        result = build_and_validate(story, out_root / story.key, export=args.get("export", True))
        version = store(state.workspace, story, result)
        return {"story_key": story.key, "version": version, "ok": result["validation"]["ok"],
                "variants": {k: {"ok": v["ok"], "findings": [f["code"] for f in v["findings"]]}
                             for k, v in result["validation"]["variants"].items()},
                "contact_sheet": result["contact_sheet"]}

    state.tools.register(Tool(
        name="factory.build", description_ar="ابني كل نسخ القالب (A4/A5 × ولد/بنت × عربي/إنجليزي) واعمل الفحوصات.",
        description_en="Build every template variant and run all validators.",
        schema={"type": "object", "properties": {"demo": {"type": "boolean"}, "story": {"type": "object"},
                                                 "export": {"type": "boolean"}}, "additionalProperties": False},
        handler=build, tags=["factory"]))

    def publish_pack(args: dict) -> dict:
        record = state.workspace.latest_approved("template_set", args["story_key"])
        if record is None:
            raise ToolError("NOT_APPROVED", "لازم تعتمد نسخة القالب الأول.", "approve the template set first")
        if not all(v["ok"] for v in record["body"]["validation"]["variants"].values()):
            raise ToolError("VALIDATION_FAILED", "فيه فحوصات فاشلة — مش هننشر.", "validators failed; not publishing")
        secret = state.secrets.get("modulex.hmac")
        if not secret:
            raise ToolError("HMAC_SECRET_MISSING", "حط المفتاح المشترك بتاع أنظمة ModuleX في الإعدادات (modulex.hmac) الأول.",
                            "set the shared ModuleX HMAC secret (modulex.hmac) in Settings first")
        story = Story.from_dict(record["body"]["story"])
        built = record["body"]["built"]
        for entry in built["variants"].values():  # the exact approved bytes, never a rebuild
            sha = record["blobs"][entry["file"]]
            if not state.workspace.verify_blob(sha):
                raise ToolError("BLOB_CORRUPT", "ملف القالب المعتمد اتغيّر على القرص.", "approved file changed on disk")
            entry["path"] = str(state.workspace.blob_path(sha))
        out = build_pack(out_root / f"{story.key}-v{record['version']}.magpack.zip", story, built,
                         record["body"]["validation"], secret)
        return {"pack": out["pack"], "sha256": out["sha256"], "story_key": story.key, "version": record["version"]}

    state.tools.register(Tool(
        name="factory.publish_pack", description_ar="جهّز حزمة موقّعة للنشر (مالهاش رجوع).",
        description_en="Produce the signed publish pack for OM/Console — irreversible.",
        schema={"type": "object", "properties": {"story_key": {"type": "string", "minLength": 3}},
                "required": ["story_key"], "additionalProperties": False},
        handler=publish_pack, irreversible=True, tags=["factory", "publish"]))

    @app.get("/api/factory/summary")
    def summary():
        sets = []
        for key in state.workspace.keys("template_set"):
            record = state.workspace.get("template_set", key)
            sets.append({"story_key": key, "version": record["version"], "approved": record["approved"],
                         "ok": record["body"].get("validation", {}).get("ok")})
        return {"facts": {"template_sets": sets},
                "actions": [{"label_ar": "ابني القصة التجريبية «نجمة القمر»", "label_en": "Build the demo story",
                             "tool": "factory.build", "args": {"demo": True}}]}
