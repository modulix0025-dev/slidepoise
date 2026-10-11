"""SVG <-> ``a:custGeom`` converter (svgelements, MIT).

Rule: SVG geometry maps 1:1 onto DrawingML path verbs - lines -> ``lnTo``, cubic -> ``cubicBezTo``,
quadratic -> ``quadBezTo``, axis-aligned elliptical arcs -> ``arcTo`` (visual angles), rotated
arcs -> ``cubicBezTo``. Transforms are applied (reified) first. Each drawable SVG element becomes
its own shape (one fill colour per ``a:custGeom``), so the deck stays editable element by element.

Fill-rule: one ``a:path`` fills even-odd in Office. A ``nonzero`` element whose outline overlaps
itself (sub-paths or a self-intersecting contour, i.e. where the two rules differ) is replaced by its pyclipper non-zero union and reported with the
finding ``nonzero_flattened``; everything else keeps its curves.
"""
from __future__ import annotations

import io
import math
from dataclasses import dataclass, field

import svgelements as se

from . import boolean
from .custgeom import CustomGeometry, GeomPart, Path, param_arc_to_cubics
from .sanitize import SanitizedSvg, sanitize_svg


@dataclass
class ConvertedShape:
    index: int
    geometry: CustomGeometry  # in the SVG viewport frame
    fill: str | None
    fill_opacity: float
    stroke: str | None
    stroke_width: float
    fill_rule: str
    tag: str
    findings: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        local, (x, y, w, h) = self.geometry.cropped()
        return {"index": self.index, "tag": self.tag, "fill": self.fill, "fill_opacity": self.fill_opacity,
                "stroke": self.stroke, "stroke_width": self.stroke_width, "fill_rule": self.fill_rule,
                "bbox": [x, y, w, h], "custgeom": local.to_xml(), "geometry": local.to_json(),
                "findings": self.findings}


@dataclass
class ConversionResult:
    width: float
    height: float
    shapes: list[ConvertedShape]
    sanitized: SanitizedSvg | None
    findings: list[str] = field(default_factory=list)

    def combined(self) -> CustomGeometry:
        """All filled parts in one frame (silhouette; for measurement and single-colour use)."""
        geom = CustomGeometry(self.width, self.height)
        for s in self.shapes:
            for p in s.geometry.parts:
                if s.fill is not None and p.fill != "none":
                    geom.parts.append(GeomPart(p.path, "norm", s.stroke is not None))
        return geom

    def to_json(self) -> dict:
        return {"width": self.width, "height": self.height, "shapes": [s.to_json() for s in self.shapes],
                "findings": self.findings,
                "sanitizer_findings": [f.to_json() for f in self.sanitized.findings] if self.sanitized else []}


def _arc_commands(seg: se.Arc) -> list[tuple]:
    """Arc segment -> [("A", ...)] when axis-aligned, else cubic commands."""
    rot = math.degrees(float(seg.get_rotation())) % 360.0
    k = round(rot / 90.0)
    if abs(rot - 90.0 * k) > 1e-6 or seg.rx <= 0 or seg.ry <= 0:
        out = []
        for c in seg.as_cubic_curves():
            out.append(("C", c.control1.x, c.control1.y, c.control2.x, c.control2.y, c.end.x, c.end.y))
        return out
    k %= 4
    rx, ry = float(seg.rx), float(seg.ry)
    t0 = float(seg.get_start_t())
    sweep = float(seg.sweep)
    t0 += k * math.pi / 2
    if k % 2:
        rx, ry = ry, rx
    if abs(sweep) < 1e-9:
        return [("L", seg.end.x, seg.end.y)]
    # visual angles of the parametric start/end on an axis-aligned ellipse
    st = math.degrees(math.atan2(ry * math.sin(t0), rx * math.cos(t0)))
    out = []
    # split so that every piece stays below 180 degrees (unambiguous unwrap)
    n = max(1, int(math.ceil(abs(sweep) / (math.pi * 0.999))))
    prev_vis = st
    for i in range(1, n + 1):
        tb = t0 + sweep * i / n
        vis = math.degrees(math.atan2(ry * math.sin(tb), rx * math.cos(tb)))
        d = vis - prev_vis
        while sweep > 0 and d <= 0:
            d += 360.0
        while sweep < 0 and d >= 0:
            d -= 360.0
        while abs(d) > 360.0:
            d -= math.copysign(360.0, d)
        out.append(("A", rx, ry, prev_vis, d))
        prev_vis = vis
    return out


def _element_path(element) -> Path:
    sp = abs(se.Path(element))  # reify transforms
    p = Path()
    started = False
    for seg in sp:
        if isinstance(seg, se.Move):
            p.move_to(seg.end.x, seg.end.y)
            started = True
        elif not started:
            continue
        elif isinstance(seg, se.Close):
            p.close()
        elif isinstance(seg, se.Line):
            p.line_to(seg.end.x, seg.end.y)
        elif isinstance(seg, se.CubicBezier):
            p.cubic_to(seg.control1.x, seg.control1.y, seg.control2.x, seg.control2.y, seg.end.x, seg.end.y)
        elif isinstance(seg, se.QuadraticBezier):
            p.quad_to(seg.control.x, seg.control.y, seg.end.x, seg.end.y)
        elif isinstance(seg, se.Arc):
            p.commands.extend(_arc_commands(seg))
    return p


def _close_open_subpaths(p: Path) -> Path:
    """Filled, unstroked sub-paths are closed explicitly (SVG fills them as if closed)."""
    out = Path()
    open_sub = False
    for cmd in p.commands:
        if cmd[0] == "M":
            if open_sub:
                out.close()
            open_sub = False
        else:
            open_sub = cmd[0] != "Z"
        out.commands.append(cmd)
    if open_sub:
        out.close()
    return out


def _color(value) -> tuple[str | None, float]:
    if value is None:
        return None, 0.0
    try:
        if value.value is None:
            return None, 0.0
        return value.hexrgb.upper(), float(value.opacity)
    except AttributeError:
        return None, 0.0


def svg_to_shapes(svg_text: str | bytes, *, sanitize: bool = True, strict: bool = False) -> ConversionResult:
    """Parse (optionally sanitised) SVG into editable custGeom shapes in the viewport frame."""
    sanitized = None
    if sanitize:
        sanitized = sanitize_svg(svg_text, strict=strict)
        text = sanitized.svg
    else:
        text = svg_text.decode("utf-8") if isinstance(svg_text, bytes) else svg_text
    doc = se.SVG.parse(io.StringIO(text), reify=True)
    width = float(doc.width or 0) or float(getattr(doc.viewbox, "width", 0) or 0)
    height = float(doc.height or 0) or float(getattr(doc.viewbox, "height", 0) or 0)
    if width <= 0 or height <= 0:
        raise ValueError("SVG has no usable viewport")
    shapes: list[ConvertedShape] = []
    findings: list[str] = []
    for element in doc.elements():
        if not isinstance(element, se.Shape) or isinstance(element, se.SVG):
            continue
        if element.values.get("visibility") == "hidden" or element.values.get("display") == "none":
            continue
        fill, fill_op = _color(element.fill)
        stroke, _ = _color(element.stroke)
        sw = float(element.stroke_width or 0) if stroke else 0.0
        if stroke and hasattr(element, "implicit_stroke_width"):
            sw = float(element.implicit_stroke_width or sw)
        if fill is None and (stroke is None or sw <= 0):
            continue
        path = _element_path(element)
        if not any(c[0] != "M" for c in path.commands):
            continue
        rule = str(element.values.get("fill-rule", "nonzero")).strip().lower()
        local: list[str] = []
        if fill is not None:
            if stroke is None:
                path = _close_open_subpaths(path)
            if rule != "evenodd":
                a_nz = boolean.area(path, fill_rule="nonzero")
                a_eo = boolean.area(path, fill_rule="evenodd")
                if abs(a_nz - a_eo) > 1e-4 * max(a_nz, 1e-9):
                    path = boolean.union_all([path], tol=0.01, fill_rule="nonzero")
                    local.append("nonzero_flattened")
        geom = CustomGeometry(width, height, [GeomPart(path, "norm" if fill else "none", stroke is not None)])
        shapes.append(ConvertedShape(len(shapes), geom, fill, fill_op, stroke, sw, rule,
                                     type(element).__name__.lower(), local))
        findings.extend(local)
    if not shapes:
        findings.append("no_drawable_geometry")
    return ConversionResult(width, height, shapes, sanitized, sorted(set(findings)))


def svg_to_custgeom(svg_text: str | bytes, *, sanitize: bool = True) -> CustomGeometry:
    """Single-colour silhouette of the whole SVG as one ``a:custGeom`` (viewport frame)."""
    return svg_to_shapes(svg_text, sanitize=sanitize).combined()


def custgeom_to_svg(xml: str, fill: str = "#000000", width_px: float | None = None) -> str:
    geom = CustomGeometry.from_xml(xml)
    return geom.to_svg(fill=fill, width_px=width_px,
                       height_px=(width_px * geom.height / geom.width) if width_px else None)


def path_from_cubics_only(p: Path) -> Path:  # pragma: no cover - convenience re-export
    return p.only_mlcz()


__all__ = ["ConvertedShape", "ConversionResult", "svg_to_shapes", "svg_to_custgeom", "custgeom_to_svg",
           "param_arc_to_cubics"]
