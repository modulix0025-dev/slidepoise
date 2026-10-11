"""Colour & taste routes and agent tools (facts and named findings; taste is advisory)."""
from __future__ import annotations

from pathlib import Path

from mxstudio.agent.tools import Tool, ToolError


def register(app, state) -> None:
    from mxstudio.colour import cvd, extract, harmony, palettes, print_safety  # noqa: PLC0415

    def list_pal(args: dict) -> dict:
        found = palettes.list_palettes(args.get("theme"), args.get("age"), args.get("mood"), args.get("mode"))
        if not found and args.get("theme"):  # "desert" → "desert_egypt", "nile" → "river_nile"
            wanted = str(args["theme"]).lower()
            found = [p for p in palettes.list_palettes(None, args.get("age"), args.get("mood"), args.get("mode"))
                     if any(wanted in t or t in wanted for t in p.get("themes", []))]
        return {"count": len(found), "palettes": found[: int(args.get("limit", 20))]}

    def harmonies(args: dict) -> dict:
        return harmony.all_harmonies(args["base"])

    def print_check(args: dict) -> dict:
        return print_safety.check_palette(args["colours"])

    def meanings(args: dict) -> dict:
        return cvd.check_colour_meanings(args["meanings"], args.get("cues"))

    def from_art(args: dict) -> dict:
        if args.get("reference"):  # an image the operator uploaded in the Studio (workspace blob sha)
            if not state.workspace.verify_blob(str(args["reference"])):
                raise ToolError("FILE_NOT_FOUND", "الصورة المرفوعة مش موجودة.", "uploaded image not found")
            args = dict(args, image=str(state.workspace.blob_path(str(args["reference"]))))
        if not args.get("image"):
            raise ToolError("INVALID_ARGUMENTS", "ابعت image أو reference.", "give image or reference")
        path = Path(args["image"])
        if not path.is_file():
            raise ToolError("FILE_NOT_FOUND", "الصورة مش موجودة.", "image not found")
        result = extract.extract_palette(str(path), k=int(args.get("k", 6)))
        result["nearest_curated"] = palettes.nearest_palettes([c["hex"] for c in result.get("colours", [])
                                                               if isinstance(c, dict) and "hex" in c][:6] or ["#888888"])
        return result

    obj = {"type": "object"}
    state.tools.register(Tool("colour.list_palettes", "اعرض باليتات الأطفال المختارة.", "List curated kids' palettes.",
                              {"type": "object", "properties": {"theme": {"type": "string"}, "age": {"type": "string"},
                                                                "mood": {"type": "string"}, "mode": {"type": "string"},
                                                                "limit": {"type": "integer", "minimum": 1}},
                               "additionalProperties": False}, list_pal, tags=["colour"]))
    state.tools.register(Tool("colour.harmonies", "ألوان متناسقة مع لون أساسي.", "Colour harmonies for a base colour.",
                              {"type": "object", "properties": {"base": {"type": "string"}}, "required": ["base"],
                               "additionalProperties": False}, harmonies, tags=["colour"]))
    state.tools.register(Tool("colour.print_check", "هل الألوان دي هتطلع صح في الطباعة؟", "CMYK print safety facts.",
                              {"type": "object", "properties": {"colours": {"type": "array", "items": {"type": "string"},
                                                                            "minItems": 1}},
                               "required": ["colours"], "additionalProperties": False}, print_check, tags=["colour"]))
    state.tools.register(Tool("colour.cvd_meanings", "المعنى بيفضل واضح لعمى الألوان؟", "Colour-vision-deficiency check.",
                              {"type": "object", "properties": {"meanings": obj, "cues": obj}, "required": ["meanings"],
                               "additionalProperties": False}, meanings, tags=["colour"]))
    state.tools.register(Tool("colour.from_art", "طلّع باليتة من الرسمة المعتمدة.", "Extract a palette from approved art.",
                              {"type": "object", "properties": {"image": {"type": "string"},
                                                                "reference": {"type": "string",
                                                                              "pattern": "^[0-9a-f]{64}$"},
                                                                "k": {"type": "integer", "minimum": 2, "maximum": 12}},
                               "additionalProperties": False}, from_art, tags=["colour"]))

    @app.get("/api/colour/summary")
    def summary():
        catalog = palettes.load_catalog()
        items = catalog.get("palettes", catalog if isinstance(catalog, list) else [])
        return {"facts": {"palettes": len(items), "profiles": print_safety.known_profiles(),
                          "rule": "objective failures block; taste is advisory and never auto-publishes"},
                "actions": [{"label_ar": "باليتات البحر لسن 6-8", "label_en": "Sea palettes, ages 6-8",
                             "tool": "colour.list_palettes", "args": {"theme": "sea", "age": "6-8"}}]}
