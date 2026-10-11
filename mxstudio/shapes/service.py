"""API-agnostic service layer for the shape studio (plain dicts in, JSON-safe dicts out).

The HTTP routes in ``api.py`` and the agent tools are thin wrappers over these methods, so the
same rules hold whichever door a request comes through:

* discovery runs only when the library has too few matches (or the operator forces it);
* imports are resolved from the *server-side* copy of the search result - a client cannot
  upgrade a licence by editing JSON - and need an operator name;
* AI and vectorised shapes are candidates until an operator approves them;
* every response carries facts and named findings, never a visual verdict.
"""
from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import consistency, credits, presets, warps
from .ai_shapes import ImageModel, ShapeCandidate, TextModel, VisionCritic, describe_to_shape, image_to_shape
from .boolean import boolean as clip_boolean
from .custgeom import CustomGeometry, GeomPart, Path as GPath
from .discovery import SEARCHERS, Candidate, PoliteClient, import_candidate, inspiration_candidate
from .discovery.base import DiscoveryError, sources
from .generators import generate, list_generators
from .library import STYLES, ShapeLibrary
from .raster import mask_from_png
from .sanitize import SvgRejected, sanitize_svg
from .svg_convert import svg_to_shapes
from .vectorize import vectorize_image

MAX_CANVAS_PATHS = 400
MAX_CANVAS_COMMANDS = 50_000
MAX_UPLOAD_BYTES = 8_000_000


class ServiceError(ValueError):
    def __init__(self, code: str, message_ar: str, message_en: str) -> None:
        super().__init__(message_en)
        self.code, self.message_ar, self.message_en = code, message_ar, message_en

    def to_json(self) -> dict:
        return {"ok": False, "code": self.code, "ar": self.message_ar, "en": self.message_en}


def _b64(data: str) -> bytes:
    try:
        raw = base64.b64decode(data.split(",", 1)[-1], validate=True)
    except (binascii.Error, ValueError):
        raise ServiceError("BAD_BASE64", "الملف مش مقروء.", "invalid base64 payload") from None
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ServiceError("TOO_LARGE", "الملف كبير قوي.", "upload too large")
    return raw


def _geometry_from_body(item) -> CustomGeometry:
    if isinstance(item, dict) and "parts" in item:
        return CustomGeometry.from_json(item)
    if isinstance(item, dict) and "commands" in item:
        w, h = float(item.get("width", 1000)), float(item.get("height", 1000))
        return CustomGeometry(w, h, [GeomPart(GPath.from_json(item["commands"]))])
    raise ServiceError("BAD_GEOMETRY", "الشكل مش مفهوم.", "expected a geometry {width,height,parts} or {commands}")


@dataclass
class ShapeService:
    library: ShapeLibrary
    client_factory: Callable[[], PoliteClient] | None = None
    text_model: TextModel | None = None
    critic: VisionCritic | None = None
    image_model: ImageModel | None = None
    discovery_enabled: dict = field(default_factory=lambda: {"iconify": True, "openverse": True, "wikimedia": True})
    _found: dict = field(default_factory=dict)
    _candidates: dict = field(default_factory=dict)

    @classmethod
    def at(cls, library_path: str | Path, **kw) -> "ShapeService":
        return cls(ShapeLibrary(library_path), **kw)

    # ------------------------------------------------------------- catalogues
    def presets(self, body: dict | None = None) -> dict:
        return presets.catalog()

    def warps(self, body: dict | None = None) -> dict:
        return warps.catalog()

    def preset_xml(self, body: dict) -> dict:
        """``a:prstGeom`` for a preset with the operator's handle values (resolved + clamped by Office)."""
        try:
            prst = str(body["prst"])
            adj = presets.resolve_adjustments(prst, body.get("adj") or {})
            return {"ok": True, "prst": prst, "adj": dict(adj), "xml": presets.prst_geom_xml(prst, dict(adj))}
        except KeyError as exc:
            raise ServiceError("UNKNOWN_PRESET", "الشكل الجاهز ده مش موجود.", str(exc)) from None
        except ValueError as exc:
            raise ServiceError("BAD_HANDLE", "ذراع الضبط مش معروف.", str(exc)) from None

    def warp_xml(self, body: dict) -> dict:
        try:
            prst = str(body["prst"])
            adj = warps.resolve(prst, body.get("adj") or {})
            return {"ok": True, "prst": prst, "adj": dict(adj), "xml": warps.prst_tx_warp_xml(prst, dict(adj))}
        except KeyError as exc:
            raise ServiceError("UNKNOWN_WARP", "الانحناء ده مش موجود.", str(exc)) from None
        except ValueError as exc:
            raise ServiceError("BAD_HANDLE", "ذراع الضبط مش معروف.", str(exc)) from None

    def generators(self, body: dict | None = None) -> dict:
        return {"generators": list_generators(), "styles": list(STYLES)}

    # ------------------------------------------------------------- making shapes
    def generate(self, body: dict) -> dict:
        try:
            g = generate(str(body["name"]), int(body.get("seed", 0)), body.get("params") or {})
        except KeyError as exc:
            raise ServiceError("UNKNOWN_GENERATOR", "المولّد ده مش موجود.", f"unknown generator {exc}") from None
        except (TypeError, ValueError) as exc:
            raise ServiceError("BAD_PARAMS", "الإعدادات مش مظبوطة.", str(exc)) from None
        out = g.to_json()
        out["svg_preview"] = g.merged().to_svg(fill="#E63946", stroke="#222222", stroke_width=max(g.width, g.height) / 300)
        return out

    def sanitize(self, body: dict) -> dict:
        try:
            return {"ok": True, **sanitize_svg(str(body["svg"]), strict=bool(body.get("strict"))).to_json()}
        except SvgRejected as exc:
            return {"ok": False, "code": exc.code, "detail": exc.detail}

    def svg_to_custgeom(self, body: dict) -> dict:
        try:
            res = svg_to_shapes(str(body["svg"]))
        except SvgRejected as exc:
            raise ServiceError("SVG_REJECTED", "الـSVG ده مرفوض لأسباب أمان.", f"{exc.code}: {exc.detail}") from None
        return {"ok": True, **res.to_json(), "silhouette": res.combined().to_xml()}

    def boolean(self, body: dict) -> dict:
        op = str(body.get("op", "union"))
        subj = [_geometry_from_body(g) for g in body.get("subject", [])]
        clip = [_geometry_from_body(g) for g in body.get("clip", [])]
        if not subj:
            raise ServiceError("EMPTY", "مفيش أشكال.", "no subject shapes")
        w, h = float(body.get("width", subj[0].width)), float(body.get("height", subj[0].height))
        try:
            res = clip_boolean([p.path for g in subj for p in g.parts if p.fill != "none"],
                               [p.path for g in clip for p in g.parts if p.fill != "none"], op)
        except ValueError as exc:
            raise ServiceError("BAD_OP", "العملية مش معروفة.", str(exc)) from None
        geom = CustomGeometry(w, h, [GeomPart(res)])
        return {"ok": True, "op": op, "geometry": geom.to_json(), "custgeom": geom.to_xml(), "svg": geom.to_svg()}

    def canvas_commit(self, body: dict) -> dict:
        """Paths drawn on the canvas -> one editable custGeom (optionally saved to the library)."""
        w, h = float(body.get("width", 1000)), float(body.get("height", 1000))
        paths = body.get("paths") or []
        if not paths or len(paths) > MAX_CANVAS_PATHS:
            raise ServiceError("BAD_CANVAS", "الرسمة فاضية أو كبيرة قوي.", "need 1..400 paths")
        parts = []
        total = 0
        for item in paths:
            try:
                p = GPath.from_json(item.get("commands") or [])
            except ValueError as exc:
                raise ServiceError("BAD_PATH", "مسار مش سليم.", str(exc)) from None
            total += len(p.commands)
            if total > MAX_CANVAS_COMMANDS:
                raise ServiceError("TOO_COMPLEX", "الرسمة معقدة قوي.", "too many path commands")
            closed = bool(item.get("closed", any(c[0] == "Z" for c in p.commands)))
            filled = bool(item.get("fill")) and closed
            parts.append(GeomPart(p, "norm" if filled else "none", bool(item.get("stroke", not filled))))
        geom = CustomGeometry(w, h, parts)
        local, bbox = geom.cropped()
        line = body.get("line") or {}
        out = {"ok": True, "geometry": local.to_json(), "custgeom": local.to_xml(), "bbox": list(bbox),
               "line": {"width_pt": float(line.get("width_pt", 1.5)), "dash": str(line.get("dash", "solid")),
                        "cap": str(line.get("cap", "rnd")), "colour": str(line.get("colour", "#222222"))},
               "svg": local.to_svg(fill=str(body.get("fill_colour", "#E63946")), stroke="#222222",
                                   stroke_width=max(local.width, local.height) / 200)}
        if body.get("save"):
            author = str(body.get("author") or "").strip()
            if not author:
                raise ServiceError("APPROVAL", "اكتب اسم المشغّل علشان نحفظ.", "operator name required to save")
            out["asset_id"] = self.library.add_original(
                local, "canvas", author=author, source_url="mxstudio://canvas", name_ar=str(body.get("name_ar", "")),
                name_en=str(body.get("name_en", "")), tags=list(body.get("tags") or []),
                style=str(body.get("style", "flat")), theme=str(body.get("theme", "")), approved_by=author)
        return out

    def vectorize(self, body: dict) -> dict:
        res = vectorize_image(_b64(str(body["image_base64"])), max_nodes=int(body.get("max_nodes", 1500)))
        cand = ShapeCandidate("upload", "vectorize", res.geometry, res.geometry.to_svg(), None,
                              findings=res.findings)
        key = self._remember(cand)
        return {"ok": True, "candidate_id": key, **res.to_json(), "status": cand.status}

    # ------------------------------------------------------------- AI (authoring only)
    def ai_describe(self, body: dict) -> dict:
        if not self.text_model:
            raise ServiceError("NO_PROVIDER", "مفيش موديل نصوص متوصل.", "no text model configured")
        insp = [c.to_json() if isinstance(c, Candidate) else c for c in body.get("inspiration") or []]
        cand = describe_to_shape(str(body["brief"]), self.text_model, self.critic,
                                 max_rounds=int(body.get("max_rounds", 3)), inspiration=insp)
        return {"ok": cand.geometry is not None, "candidate_id": self._remember(cand), **cand.to_json()}

    def ai_image(self, body: dict) -> dict:
        if not self.image_model:
            raise ServiceError("NO_PROVIDER", "مفيش موديل صور متوصل.", "no image model configured")
        cand = image_to_shape(str(body["brief"]), self.image_model)
        return {"ok": True, "candidate_id": self._remember(cand), **cand.to_json()}

    def _remember(self, cand: ShapeCandidate) -> str:
        import secrets

        key = secrets.token_hex(8)
        self._candidates[key] = cand
        return key

    def approve_candidate(self, body: dict) -> dict:
        cand: ShapeCandidate | None = self._candidates.get(str(body.get("candidate_id")))
        if cand is None:
            raise ServiceError("UNKNOWN_CANDIDATE", "الاقتراح ده مش موجود.", "unknown candidate")
        operator = str(body.get("approved_by") or "").strip()
        if not operator:
            raise ServiceError("APPROVAL", "لازم المشغّل يوافق باسمه.", "operator approval required")
        cand.approve(operator)
        origin = "ai" if cand.route == "describe" else "vectorized"
        asset_id = self.library.add_original(
            cand.geometry, origin, author=f"{operator} (AI-assisted)" if origin == "ai" else operator,
            source_url=f"mxstudio://{cand.route}", name_ar=str(body.get("name_ar", "")),
            name_en=str(body.get("name_en", cand.brief[:60])), tags=list(body.get("tags") or []),
            style=str(body.get("style", "flat")), approved_by=operator)
        return {"ok": True, "asset_id": asset_id}

    # ------------------------------------------------------------- discovery
    def discover(self, body: dict) -> dict:
        query = str(body.get("query", ""))
        min_hits = int(body.get("min_library_hits", 3))
        local = self.library.search_text(query, limit=20)
        if len(local) >= min_hits and not body.get("force"):
            return {"ok": True, "from": "library", "library": [a.to_json() for a in local], "printable": [],
                    "refused": [], "errors": {}}
        if not self.client_factory:
            raise ServiceError("OFFLINE", "البحث على النت مش متاح دلوقتي.", "no discovery client configured")
        client = self.client_factory()
        enabled = [s for s in body.get("sources") or list(SEARCHERS) if self.discovery_enabled.get(s)]
        results, errors = [], {}
        for name in enabled:
            try:
                results.extend(SEARCHERS[name](client, query, limit=int(body.get("limit", 20))))
            except DiscoveryError as exc:
                errors[name] = str(exc)
        for c in results:
            self._found[f"{c.source}:{c.source_id}"] = c
        return {"ok": True, "from": "apis", "library": [a.to_json() for a in local],
                "printable": [dict(c.to_json(), key=f"{c.source}:{c.source_id}") for c in results if c.decision.printable],
                "refused": [dict(c.to_json(), key=f"{c.source}:{c.source_id}") for c in results
                            if not c.decision.printable], "errors": errors}

    def inspiration(self, body: dict) -> dict:
        c = inspiration_candidate(str(body["url"]), str(body.get("title", "")))
        self._found[f"{c.source}:{c.source_id}"] = c
        return {"ok": True, "key": f"{c.source}:{c.source_id}", **c.to_json()}

    def import_asset(self, body: dict) -> dict:
        cand: Candidate | None = self._found.get(str(body.get("key")))
        if cand is None:
            raise ServiceError("UNKNOWN_RESULT", "النتيجة دي مش من آخر بحث.", "import only results from a search")
        if not self.client_factory:
            raise ServiceError("OFFLINE", "مفيش اتصال.", "no discovery client configured")
        try:
            imported = import_candidate(cand, self.client_factory(), approved_by=str(body.get("approved_by", "")))
        except DiscoveryError as exc:
            raise ServiceError(exc.code.upper(), "الاستيراد اترفض.", str(exc)) from None
        if imported.media == "svg":
            geom = svg_to_shapes(imported.svg, sanitize=False).combined()
        else:
            geom = vectorize_image(imported.raster).geometry
        asset_id = self.library.add(geometry=geom, origin="discovered", provenance=imported.provenance,
                                    name_ar=str(body.get("name_ar", "")), name_en=str(body.get("name_en", cand.title)),
                                    tags=list(body.get("tags") or cand.tags), style=str(body.get("style", "flat")),
                                    theme=str(body.get("theme", "")), approved_by=imported.provenance.approved_by)
        return {"ok": True, "asset_id": asset_id, "provenance": imported.provenance.to_json(),
                "findings": imported.findings}

    # ------------------------------------------------------------- library
    def library_search(self, body: dict) -> dict:
        found = self.library.search_text(str(body.get("q", "")), style=body.get("style"), theme=body.get("theme"),
                                         age=body.get("age"), favourites_only=bool(body.get("favourites")),
                                         limit=int(body.get("limit", 50)))
        return {"ok": True, "assets": [a.to_json() for a in found]}

    def library_similar(self, body: dict) -> dict:
        if body.get("sketch_png_base64"):
            hits = self.library.search_similar(mask=mask_from_png(_b64(body["sketch_png_base64"])),
                                               limit=int(body.get("limit", 10)))
        else:
            hits = self.library.search_similar(geometry=_geometry_from_body(body.get("geometry") or body),
                                               limit=int(body.get("limit", 10)))
        return {"ok": True, "assets": [dict(a.to_json(), distance=d) for d, a in hits]}

    def library_get(self, body: dict) -> dict:
        try:
            return {"ok": True, **self.library.get(str(body["id"])).to_json(with_geometry=True)}
        except KeyError:
            raise ServiceError("NOT_FOUND", "الشكل مش موجود.", "asset not found") from None

    def favourite(self, body: dict) -> dict:
        self.library.set_favourite(str(body["id"]), bool(body.get("on", True)))
        return {"ok": True}

    def record_use(self, body: dict) -> dict:
        return {"ok": True, "use_count": self.library.record_use(str(body["id"]), str(body["book_id"]),
                                                                  body.get("page"))}

    # ------------------------------------------------------------- book checks
    def consistency(self, body: dict) -> dict:
        if body.get("pptx_path"):
            uses = consistency.uses_from_pptx(Path(str(body["pptx_path"])))
        else:
            uses = [consistency.ShapeUse(**u) for u in body.get("uses") or []]
        return {"ok": True, **consistency.check(uses, palette=body.get("palette"))}

    def licence_report(self, body: dict) -> dict:
        ids = body.get("asset_ids")
        if ids is None and body.get("book_id"):
            ids = sorted({u["asset_id"] for u in self.library.uses_in_book(str(body["book_id"]))})
        assets = [self.library.get(i) for i in (ids or [])]
        report = credits.licence_report([a.provenance for a in assets])
        return {"ok": True, **report, "markdown": credits.report_markdown(report)}

    def sources(self, body: dict | None = None) -> dict:
        return sources()


ENDPOINTS = [
    ("GET", "/api/shapes/presets", "presets"),
    ("GET", "/api/shapes/warps", "warps"),
    ("GET", "/api/shapes/generators", "generators"),
    ("GET", "/api/shapes/sources", "sources"),
    ("POST", "/api/shapes/presets/xml", "preset_xml"),
    ("POST", "/api/shapes/warps/xml", "warp_xml"),
    ("POST", "/api/shapes/generate", "generate"),
    ("POST", "/api/shapes/sanitize", "sanitize"),
    ("POST", "/api/shapes/svg-to-custgeom", "svg_to_custgeom"),
    ("POST", "/api/shapes/boolean", "boolean"),
    ("POST", "/api/shapes/canvas/commit", "canvas_commit"),
    ("POST", "/api/shapes/vectorize", "vectorize"),
    ("POST", "/api/shapes/ai/describe", "ai_describe"),
    ("POST", "/api/shapes/ai/image", "ai_image"),
    ("POST", "/api/shapes/candidates/approve", "approve_candidate"),
    ("POST", "/api/shapes/discover", "discover"),
    ("POST", "/api/shapes/inspiration", "inspiration"),
    ("POST", "/api/shapes/import", "import_asset"),
    ("POST", "/api/shapes/library/search", "library_search"),
    ("POST", "/api/shapes/library/similar", "library_similar"),
    ("POST", "/api/shapes/library/get", "library_get"),
    ("POST", "/api/shapes/library/favourite", "favourite"),
    ("POST", "/api/shapes/library/use", "record_use"),
    ("POST", "/api/shapes/consistency", "consistency"),
    ("POST", "/api/shapes/licence-report", "licence_report"),
]
