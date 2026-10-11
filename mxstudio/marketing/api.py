"""Marketing routes and agent tools: preview flipbook, social carousels, institution sales deck.

Sources are the exported PDFs of an APPROVED template set (the exact approved bytes from the
workspace). Outputs go to <workspace>/marketing/… and never include a print file.
"""
from __future__ import annotations

import time
from pathlib import Path

from mxstudio.agent.tools import Tool, ToolError


def register(app, state) -> None:
    from mxstudio.marketing import carousel, flipbook, sales_deck  # noqa: PLC0415

    out_root = Path(state.workspace.root) / "marketing"

    def approved_pdf(story_key: str, variant: str | None) -> tuple[Path, dict, str]:
        record = state.workspace.latest_approved("template_set", story_key)
        if record is None:
            raise ToolError("NOT_APPROVED", "لازم تعتمد نسخة القالب الأول — التسويق بيستخدم المعتمد بس.",
                            "approve the template set first; marketing uses approved material only")
        pdfs = sorted(name for name in record["blobs"] if name.endswith(".pdf"))
        if variant:
            pdfs = [name for name in pdfs if variant in name]
        if not pdfs:
            raise ToolError("NO_APPROVED_PDF", "مفيش PDF معتمد للنسخة دي.", "no approved PDF for this variant",
                            {"available": sorted(n for n in record["blobs"] if n.endswith(".pdf"))})
        sha = record["blobs"][pdfs[0]]
        if not state.workspace.verify_blob(sha):
            raise ToolError("BLOB_CORRUPT", "الملف المعتمد اتغيّر على القرص.", "approved file changed on disk")
        return state.workspace.blob_path(sha), record, pdfs[0]

    def stamp() -> str:
        return time.strftime("%Y%m%d-%H%M%S")

    def make_flipbook(args: dict) -> dict:
        pdf, record, name = approved_pdf(args["story_key"], args.get("variant"))
        title = record["body"]["story"].get("title", {}).get("ar") or args["story_key"]
        parts = Path(name).stem.split("_")  # <key>_<ar|en>_<boy|girl>_<A4|A5>
        language = "en" if len(parts) >= 3 and parts[-3] == "en" else "ar"
        out = flipbook.build_flipbook(pdf, out_root / args["story_key"] / f"flipbook-{stamp()}", title,
                                      language=language)
        return dict(out, source=name, approved_version=record["version"])

    def make_carousel(args: dict) -> dict:
        if args.get("pdf_path"):  # anything outside the approved template set may carry a real child's data
            pdf, name, child = Path(args["pdf_path"]), Path(args["pdf_path"]).name, True
            if not pdf.is_file():
                raise ToolError("FILE_NOT_FOUND", "الملف مش موجود.", "file not found")
        else:
            pdf, _record, name = approved_pdf(args["story_key"], args.get("variant"))
            child = bool(args.get("contains_child_data", False))
        try:
            out = carousel.build_carousel(pdf, out_root / (args.get("story_key") or "external") / f"carousel-{stamp()}",
                                          args["aspect"], caption=args.get("caption", "قصة باسم طفلك — ModuleX"),
                                          contains_child_data=child, consent=args.get("consent"),
                                          pages=args.get("pages"))
        except carousel.ConsentRequired as exc:
            raise ToolError(exc.code, exc.ar, exc.en) from None
        return dict(out, source=name)

    def make_sales_deck(args: dict) -> dict:
        samples: list[Path] = []
        if args.get("story_key"):
            book = make_flipbook({"story_key": args["story_key"], "variant": args.get("variant")})
            pages = sorted((Path(book["folder"]) / "pages").glob("*.jpg"))
            samples = pages[:1] + pages[2:4] if len(pages) >= 4 else pages
        safe = "".join(c for c in args["institution"] if c.isalnum() or c in " _-")[:40].strip() or "institution"
        out = out_root / "sales" / f"{safe}-{stamp()}.pptx"
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            built = sales_deck.build_sales_deck(out, args["institution"], args.get("offer") or {}, samples,
                                                theme=args.get("theme"))
        except (ValueError, LookupError) as exc:
            raise ToolError("DECK_NOT_BUILT", "العرض ماتبناش — نص مش داخل مكانه أو خط مش متسطّب.", str(exc)) from None
        return {"pptx": built["pptx"], "slides": built["slides"], "samples": [str(p) for p in samples]}

    string = {"type": "string"}
    state.tools.register(Tool(
        "marketing.flipbook", "اعمل كتاب معاينة بعلامة مائية من الـPDF المعتمد (مش ملف الطباعة).",
        "Watermarked preview flipbook from the approved PDF (never the print file).",
        {"type": "object", "properties": {"story_key": string, "variant": string}, "required": ["story_key"],
         "additionalProperties": False}, make_flipbook, tags=["marketing"]))
    state.tools.register(Tool(
        "marketing.carousel", "اعمل كاروسيل سوشيال 4:5 أو 1:1 (بيانات طفل حقيقي بموافقة صريحة بس).",
        "Social carousel 4:5 or 1:1 (a real child's data only with explicit consent).",
        {"type": "object", "properties": {
            "story_key": string, "variant": string, "pdf_path": string, "aspect": {"enum": sorted(carousel.ASPECTS)},
            "caption": string, "pages": {"type": "array", "items": {"type": "integer", "minimum": 1}, "maxItems": 10},
            "contains_child_data": {"type": "boolean"},
            "consent": {"type": "object", "properties": {"granted": {"type": "boolean"}, "granted_by": string,
                                                         "reference": string,
                                                         "scope": {"type": "array", "items": string}}}},
         "required": ["aspect"], "additionalProperties": False}, make_carousel, tags=["marketing"]))
    state.tools.register(Tool(
        "marketing.sales_deck", "اعمل عرض مبيعات للمدارس 16:9 عربي قابل للتعديل.",
        "Institution sales deck: 16:9 editable PPTX, Arabic right-to-left.",
        {"type": "object", "properties": {"institution": {"type": "string", "minLength": 2}, "story_key": string,
                                          "variant": string, "offer": {"type": "object"}, "theme": {"type": "object"}},
         "required": ["institution"], "additionalProperties": False}, make_sales_deck, tags=["marketing"]))

    @app.get("/api/marketing/summary")
    def summary():
        made = sorted(str(p.relative_to(out_root)) for p in out_root.glob("*/*") if p.exists())[-20:] \
            if out_root.is_dir() else []
        return {"facts": {"outputs": made, "rules": ["previews are watermarked and low-resolution",
                                                     "a real child's data needs explicit consent",
                                                     "sales decks stay editable PowerPoint"]},
                "actions": [{"label_ar": "عرض مبيعات تجريبي", "label_en": "Sample sales deck",
                             "tool": "marketing.sales_deck", "args": {"institution": "مدرسة النور"}}]}
