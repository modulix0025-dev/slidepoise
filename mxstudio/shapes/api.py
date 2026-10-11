"""Shape-studio routes and agent tools (mounted by ``mxstudio.app.features``).

Every route is a thin wrapper over ``ShapeService`` (see ``service.ENDPOINTS``). The library lives
in the workspace (``<workspace>/shapes/library.sqlite3``). Discovery uses a polite client with an
on-disk cache in the app home; providers for AI shapes are injected by whoever owns them
(``state.shape_providers`` if present) - without them the AI routes answer ``NO_PROVIDER``.
"""
from __future__ import annotations

from mxstudio.agent.tools import Tool, ToolError

from .service import ENDPOINTS, ServiceError, ShapeService

READ_ONLY_TOOLS = {"presets", "warps", "generators", "generate", "library_search", "svg_to_custgeom", "consistency",
                   "licence_report"}


def build_service(state) -> ShapeService:
    from .discovery.base import PoliteClient

    settings = state.settings.load()
    providers = getattr(state, "shape_providers", None) or {}
    disc = settings.get("discovery", {})
    cache = state.home / "cache" / "shape_discovery"
    return ShapeService.at(state.workspace.root / "shapes" / "library.sqlite3",
                           client_factory=lambda: PoliteClient(cache_dir=cache),
                           text_model=providers.get("text"), critic=providers.get("critic"),
                           image_model=providers.get("image"),
                           discovery_enabled={k: bool(disc.get(k, True)) for k in ("iconify", "openverse", "wikimedia")})


def register(app, state) -> None:
    from fastapi import Body
    from fastapi.responses import JSONResponse

    service = build_service(state)
    app.state.mxs_shapes = service
    if hasattr(state, "closers"):
        state.closers.append(service.library.close)

    def make(method_name: str, http: str):
        handler = getattr(service, method_name)

        if http == "GET":
            def route():
                return handler({})
        else:
            def route(body: dict = Body(default_factory=dict)):
                try:
                    return handler(body)
                except ServiceError as exc:
                    return JSONResponse(exc.to_json(), status_code=400)
                except (KeyError, TypeError, ValueError) as exc:
                    return JSONResponse({"ok": False, "code": "BAD_REQUEST", "ar": "الطلب ناقص أو مش مظبوط.",
                                         "en": f"{type(exc).__name__}: {exc}"}, status_code=400)
        route.__name__ = f"shapes_{method_name}"
        return route

    for http, path, name in ENDPOINTS:
        (app.get if http == "GET" else app.post)(path)(make(name, http))

    def tool_handler(name):
        def run(args: dict) -> dict:
            try:
                return getattr(service, name)(args)
            except ServiceError as exc:
                raise ToolError(exc.code, exc.message_ar, exc.message_en) from None
        return run

    obj = {"type": "object"}
    for name, ar, en in (("presets", "اعرض الأشكال الجاهزة وأذرع ضبطها.", "List preset geometries and adjust handles."),
                         ("warps", "اعرض انحناءات النص.", "List text warps."),
                         ("generators", "اعرض مولّدات الأشكال.", "List procedural generators."),
                         ("generate", "ولّد شكل (بذرة ثابتة = نفس النتيجة).", "Generate a seeded shape."),
                         ("library_search", "دوّر في مكتبة الأشكال.", "Search the shape library."),
                         ("consistency", "افحص تناسق الأشكال في الكتاب.", "Style-consistency facts for a book."),
                         ("licence_report", "تقرير التراخيص وصفحة الاعتمادات.", "Licence report and credits.")):
        state.tools.register(Tool(f"shapes.{name}", ar, en, obj, tool_handler(name), tags=["shapes"]))

    @app.get("/api/shapes/summary")
    def summary():
        counts = {"presets": len(service.presets().get("presets", [])), "warps": len(service.warps().get("warps", [])),
                  "generators": len(service.generators()["generators"])}
        return {"facts": dict(counts, canvas="/ui/canvas/index.html",
                              rule="shapes stay editable vector geometry; licences gate print use"),
                "actions": [{"label_ar": "مولّدات الأشكال", "label_en": "Shape generators", "tool": "shapes.generators",
                             "args": {}}]}
