"""Factory routes and agent tools."""
from __future__ import annotations

from pathlib import Path

from mxstudio.agent.tools import Tool, ToolError
from mxstudio.factory.demo_story import moon_star_story
from mxstudio.factory.publish import build_pack
from mxstudio.factory.service import build_and_validate, store
from mxstudio.factory.story import Story


HEX = {"type": "string", "pattern": "^#[0-9A-Fa-f]{6}$"}
THEME_SCHEMA = {"type": "object", "additionalProperties": False, "properties": {
    "type_theme": {"type": "string", "description": "id from fonts.list_themes (fonts for titles and body)"},
    "colours": {"type": "object", "additionalProperties": False,
                "properties": {"text": HEX, "panel": HEX, "outline": HEX, "background": HEX}}}}


def resolve_theme(spec: dict | None, registry=None) -> dict | None:
    """Layout theme from {type_theme, colours}; every font must be installed or the build is refused (named)."""
    if not spec:
        return None
    from mxstudio.factory.layouts import DEFAULT_THEME  # noqa: PLC0415
    theme = {"name": DEFAULT_THEME["name"], "fonts": dict(DEFAULT_THEME["fonts"]),
             "colours": dict(DEFAULT_THEME["colours"])}
    if spec.get("type_theme"):
        from mxstudio.fonts.themes import load_themes  # noqa: PLC0415
        found = next((t for t in load_themes()["themes"] if t["id"] == spec["type_theme"]), None)
        if found is None:
            raise ToolError("UNKNOWN_TYPE_THEME", "ثيم الخطوط ده مش موجود — شوف fonts.list_themes.",
                            "unknown type theme; see fonts.list_themes")
        theme["name"], theme["fonts"] = found["name_ar"], {"title": found["ar_title"], "body": found["ar_body"]}
    theme["colours"].update(spec.get("colours") or {})
    if registry is None:
        from slidepoise.arabic.fonts import default_registry  # noqa: PLC0415
        registry = default_registry()
    missing = sorted({f for f in theme["fonts"].values() if not registry.has(f)})
    if missing:
        raise ToolError("FONTS_NOT_INSTALLED", "الخطوط دي مش متسطّبة على الجهاز: " + "، ".join(missing),
                        "these fonts are not installed on this PC: " + ", ".join(missing), {"missing": missing})
    return theme


def register(app, state) -> None:
    out_root = Path(state.workspace.root) / "factory"

    def build(args: dict) -> dict:
        story = moon_star_story() if args.get("demo") else Story.from_dict(args["story"])
        problems = story.validate()
        if problems:
            raise ToolError("STORY_NOT_READY", "القصة لسه مش جاهزة.", "story is not ready", {"problems": problems})
        theme = resolve_theme(args.get("theme"))
        result = build_and_validate(story, out_root / story.key, export=args.get("export", True), theme=theme)
        version = store(state.workspace, story, result, theme)
        record = state.workspace.get("template_set", story.key, version)
        return {"story_key": story.key, "version": version, "ok": result["validation"]["ok"],
                "variants": {k: {"ok": v["ok"], "findings": [f["code"] for f in v["findings"]]}
                             for k, v in result["validation"]["variants"].items()},
                "contact_sheet": result["contact_sheet"], "preview_sha": record["blobs"].get("contact_sheet.png")}

    def preview(args: dict) -> dict:
        record = state.workspace.get("template_set", args["story_key"], args.get("version"))
        if record is None:
            raise ToolError("NOT_FOUND", "مفيش قالب بالاسم ده.", "no template set with this key")
        validation = record["body"].get("validation", {})
        return {"story_key": args["story_key"], "version": record["version"], "approved": record["approved"],
                "ok": validation.get("ok"), "preview_sha": record["blobs"].get("contact_sheet.png"),
                "findings": {k: [f["code"] for f in v.get("findings", [])]
                             for k, v in validation.get("variants", {}).items() if v.get("findings")},
                "theme": record["body"].get("theme"), "story": record["body"].get("story")}

    state.tools.register(Tool(
        name="factory.build", description_ar="ابني كل نسخ القالب (A4/A5 × ولد/بنت × عربي/إنجليزي) واعمل الفحوصات.",
        description_en="Build every template variant (story JSON + optional theme) and run all validators. "
                       "Returns preview_sha: the rendered contact sheet of every page.",
        schema={"type": "object", "properties": {"demo": {"type": "boolean"}, "story": {"type": "object"},
                                                 "theme": THEME_SCHEMA, "export": {"type": "boolean"}},
                "additionalProperties": False},
        handler=build, tags=["factory"]))
    state.tools.register(Tool(
        name="factory.preview", description_ar="اعرض آخر نسخة من القالب: الصفحات والفحوصات والقصة.",
        description_en="Latest (or given) version of a template set: preview sheet, findings, story JSON and theme.",
        schema={"type": "object", "properties": {"story_key": {"type": "string", "minLength": 3},
                                                 "version": {"type": "integer", "minimum": 1}},
                "required": ["story_key"], "additionalProperties": False},
        handler=preview, tags=["factory"]))

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
