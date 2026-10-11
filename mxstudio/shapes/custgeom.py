"""Path model <-> DrawingML ``a:custGeom`` <-> SVG.

Rule enforced here: every shape the Studio authors leaves as an *editable vector*
``a:custGeom`` built only from ``moveTo / lnTo / cubicBezTo / quadBezTo / arcTo / close``
(ECMA-376 Part 1, 20.1.9) - never as a picture.

Conventions
* Coordinates are floats in a y-down design space of ``width x height``.
* Commands are tuples::

      ("M", x, y) | ("L", x, y) | ("C", x1, y1, x2, y2, x, y) | ("Q", x1, y1, x, y)
      ("A", wR, hR, stAngDeg, swAngDeg) | ("Z",)

* ``A`` follows DrawingML ``arcTo`` semantics: it continues from the current point, which
  lies on an axis-aligned ellipse (radii ``wR``, ``hR``) at the *visual* angle ``stAng``
  (the angle of the ray from the ellipse centre, clockwise, y-down), and sweeps ``swAng``.
  This is how presetShapeDefinitions use it (they move to ``cat2/sat2`` of the visual angle
  before calling ``arcTo``).
* Serialisation quantises to integers in a path space whose larger side is ``quantum``
  (default 100000 -> 1e-5 of the shape size), so equal inputs give byte-equal XML.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Callable, Iterable, Iterator

from lxml import etree

A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
SVG_NS = "http://www.w3.org/2000/svg"
_A = "{%s}" % A_NS

Command = tuple
FILL_MODES = ("norm", "none", "lighten", "lightenLess", "darken", "darkenLess")
_ARITY = {"M": 2, "L": 2, "C": 6, "Q": 4, "A": 4, "Z": 0}


# --------------------------------------------------------------------------- arcs
def ellipse_point_at_visual(w_r: float, h_r: float, angle_deg: float) -> tuple[float, float]:
    """Offset from the centre of the point at *visual* angle ``angle_deg`` (DrawingML)."""
    th = math.radians(angle_deg)
    t = math.atan2(w_r * math.sin(th), h_r * math.cos(th))
    return w_r * math.cos(t), h_r * math.sin(t)


def visual_to_param(w_r: float, h_r: float, angle_deg: float) -> float:
    th = math.radians(angle_deg)
    return math.atan2(w_r * math.sin(th), h_r * math.cos(th))


def arc_param_range(w_r: float, h_r: float, st: float, sw: float) -> tuple[float, float]:
    """Parametric start/end (radians) of an ``arcTo``; end unwrapped to follow the sweep."""
    t0 = visual_to_param(w_r, h_r, st)
    t1 = visual_to_param(w_r, h_r, st + sw)
    swr = math.radians(sw)
    # The visual->parametric map is monotonic and fixes multiples of 90 degrees, so the
    # parametric sweep has the sign and the number of turns of the visual one.
    k = round(((t0 + swr) - t1) / (2 * math.pi))
    t1 += k * 2 * math.pi
    return t0, t1


def arc_geometry(cur: tuple[float, float], w_r: float, h_r: float, st: float, sw: float):
    """Centre, parametric range and end point of an ``arcTo`` starting at ``cur``."""
    ox, oy = ellipse_point_at_visual(w_r, h_r, st)
    cx, cy = cur[0] - ox, cur[1] - oy
    t0, t1 = arc_param_range(w_r, h_r, st, sw)
    end = (cx + w_r * math.cos(t1), cy + h_r * math.sin(t1))
    return (cx, cy), t0, t1, end


def param_arc_to_cubics(cx: float, cy: float, rx: float, ry: float, t0: float, t1: float) -> list[Command]:
    """Axis-aligned elliptical arc (parametric angles) as cubic ``C`` commands (<= 90 deg each)."""
    n = max(1, int(math.ceil(abs(t1 - t0) / (math.pi / 2) - 1e-9)))
    out: list[Command] = []
    step = (t1 - t0) / n
    k = 4.0 / 3.0 * math.tan(step / 4.0)
    for i in range(n):
        a, b = t0 + i * step, t0 + (i + 1) * step
        ca, sa, cb, sb = math.cos(a), math.sin(a), math.cos(b), math.sin(b)
        x0, y0 = cx + rx * ca, cy + ry * sa
        x3, y3 = cx + rx * cb, cy + ry * sb
        out.append(("C", x0 - k * rx * sa, y0 + k * ry * ca, x3 + k * rx * sb, y3 - k * ry * cb, x3, y3))
    return out


# --------------------------------------------------------------------------- path
@dataclass
class Path:
    """An ordered list of drawing commands (see module docstring)."""

    commands: list[Command] = field(default_factory=list)

    # fluent builders --------------------------------------------------------
    def move_to(self, x: float, y: float) -> "Path":
        self.commands.append(("M", float(x), float(y)))
        return self

    def line_to(self, x: float, y: float) -> "Path":
        self.commands.append(("L", float(x), float(y)))
        return self

    def cubic_to(self, x1, y1, x2, y2, x, y) -> "Path":
        self.commands.append(("C", float(x1), float(y1), float(x2), float(y2), float(x), float(y)))
        return self

    def quad_to(self, x1, y1, x, y) -> "Path":
        self.commands.append(("Q", float(x1), float(y1), float(x), float(y)))
        return self

    def arc_to(self, w_r, h_r, st_deg, sw_deg) -> "Path":
        self.commands.append(("A", float(w_r), float(h_r), float(st_deg), float(sw_deg)))
        return self

    def close(self) -> "Path":
        self.commands.append(("Z",))
        return self

    def extend(self, other: "Path") -> "Path":
        self.commands.extend(other.commands)
        return self

    # walking ------------------------------------------------------------------
    def walk(self) -> Iterator[tuple[Command, tuple[float, float], tuple[float, float]]]:
        """Yield ``(command, start_point, end_point)``; arcs are resolved to their end point."""
        cur = (0.0, 0.0)
        start = (0.0, 0.0)
        for cmd in self.commands:
            op = cmd[0]
            if op == "M":
                cur = start = (cmd[1], cmd[2])
                yield cmd, cur, cur
                continue
            if op == "Z":
                yield cmd, cur, start
                cur = start
                continue
            if op == "A":
                _, _, _, end = arc_geometry(cur, cmd[1], cmd[2], cmd[3], cmd[4])
            else:
                end = (cmd[-2], cmd[-1])
            yield cmd, cur, end
            cur = end

    def subpaths(self) -> list["Path"]:
        out: list[Path] = []
        for cmd in self.commands:
            if cmd[0] == "M" or not out:
                out.append(Path())
            out[-1].commands.append(cmd)
        return [p for p in out if any(c[0] != "M" for c in p.commands)]

    def without_arcs(self) -> "Path":
        """Same outline with every ``arcTo`` replaced by cubic Beziers."""
        out = Path()
        for cmd, cur, _end in self.walk():
            if cmd[0] == "A":
                (cx, cy), t0, t1, _ = arc_geometry(cur, cmd[1], cmd[2], cmd[3], cmd[4])
                out.commands.extend(param_arc_to_cubics(cx, cy, cmd[1], cmd[2], t0, t1))
            else:
                out.commands.append(cmd)
        return out

    def only_mlcz(self) -> "Path":
        """Same outline using only M/L/C/Z (quadratics elevated, arcs converted)."""
        out = Path()
        for cmd, cur, _end in self.without_arcs().walk():
            if cmd[0] == "Q":
                x1, y1, x, y = cmd[1:]
                out.commands.append(("C", cur[0] + 2 / 3 * (x1 - cur[0]), cur[1] + 2 / 3 * (y1 - cur[1]),
                                     x + 2 / 3 * (x1 - x), y + 2 / 3 * (y1 - y), x, y))
            else:
                out.commands.append(cmd)
        return out

    def map_points(self, fn: Callable[[float, float], tuple[float, float]]) -> "Path":
        """Apply a point map to every coordinate (arcs are converted to cubics first)."""
        out = Path()
        for cmd in self.without_arcs().commands:
            op = cmd[0]
            if op == "Z":
                out.commands.append(cmd)
                continue
            vals = list(cmd[1:])
            mapped: list[float] = []
            for i in range(0, len(vals), 2):
                mapped.extend(fn(vals[i], vals[i + 1]))
            out.commands.append((op, *[float(v) for v in mapped]))
        return out

    def translated(self, dx: float, dy: float) -> "Path":
        out = Path()
        for cmd in self.commands:
            op = cmd[0]
            if op in ("Z", "A"):
                out.commands.append(cmd)
                continue
            vals = list(cmd[1:])
            out.commands.append((op, *[v + (dx if i % 2 == 0 else dy) for i, v in enumerate(vals)]))
        return out

    def scaled(self, s: float) -> "Path":
        """Uniform scale about the origin (keeps arcs: visual angles survive uniform scaling)."""
        out = Path()
        for cmd in self.commands:
            op = cmd[0]
            if op == "Z":
                out.commands.append(cmd)
            elif op == "A":
                out.commands.append(("A", cmd[1] * s, cmd[2] * s, cmd[3], cmd[4]))
            else:
                out.commands.append((op, *[v * s for v in cmd[1:]]))
        return out

    def affine(self, a: float, b: float, c: float, d: float, e: float, f: float) -> "Path":
        """x' = a*x + c*y + e ; y' = b*x + d*y + f (SVG matrix order)."""
        return self.map_points(lambda x, y: (a * x + c * y + e, b * x + d * y + f))

    def bbox(self, tol: float = 0.25) -> tuple[float, float, float, float]:
        from .raster import flatten_path
        polys = flatten_path(self, tol)
        xs = [p[0] for poly in polys for p in poly]
        ys = [p[1] for poly in polys for p in poly]
        if not xs:
            return (0.0, 0.0, 0.0, 0.0)
        return (min(xs), min(ys), max(xs), max(ys))

    def node_count(self) -> int:
        return len(self.commands)

    # json -----------------------------------------------------------------------
    def to_json(self) -> list[list]:
        return [[c[0], *[round(v, 4) for v in c[1:]]] for c in self.commands]

    @classmethod
    def from_json(cls, data: Iterable) -> "Path":
        p = cls()
        for item in data:
            if not isinstance(item, (list, tuple)) or not item:
                raise ValueError("path command must be a non-empty list")
            op = str(item[0]).upper()
            if op not in _ARITY:
                raise ValueError(f"unknown path op {op!r}")
            vals = [float(v) for v in item[1:]]
            if len(vals) != _ARITY[op]:
                raise ValueError(f"op {op} needs {_ARITY[op]} numbers, got {len(vals)}")
            if any(not math.isfinite(v) or abs(v) > 1e7 for v in vals):
                raise ValueError("path coordinate out of range")
            p.commands.append((op, *vals))
        if p.commands and p.commands[0][0] != "M":
            raise ValueError("path must start with M")
        return p


@dataclass
class GeomPart:
    """One ``a:path``: its own fill mode and stroke flag (shared shape fill/line colours)."""

    path: Path
    fill: str = "norm"
    stroke: bool = True

    def __post_init__(self) -> None:
        if self.fill not in FILL_MODES:
            raise ValueError(f"fill mode must be one of {FILL_MODES}")


@dataclass
class CustomGeometry:
    """A whole ``a:custGeom``: a ``width x height`` frame and its parts."""

    width: float
    height: float
    parts: list[GeomPart] = field(default_factory=list)

    @classmethod
    def single(cls, path: Path, width: float, height: float, fill: str = "norm", stroke: bool = True):
        return cls(width, height, [GeomPart(path, fill, stroke)])

    def node_count(self) -> int:
        return sum(p.path.node_count() for p in self.parts)

    def bbox(self) -> tuple[float, float, float, float]:
        boxes = [p.path.bbox() for p in self.parts if p.path.commands]
        if not boxes:
            return (0.0, 0.0, 0.0, 0.0)
        return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))

    def cropped(self, pad: float = 0.0) -> tuple["CustomGeometry", tuple[float, float, float, float]]:
        """Geometry re-framed to its own bounding box; returns ``(geometry, (x, y, w, h))``."""
        x0, y0, x1, y1 = self.bbox()
        x0, y0, x1, y1 = x0 - pad, y0 - pad, x1 + pad, y1 + pad
        w, h = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)
        parts = [GeomPart(p.path.translated(-x0, -y0), p.fill, p.stroke) for p in self.parts]
        return CustomGeometry(w, h, parts), (x0, y0, w, h)

    def to_json(self) -> dict:
        return {"width": self.width, "height": self.height,
                "parts": [{"fill": p.fill, "stroke": p.stroke, "commands": p.path.to_json()} for p in self.parts]}

    @classmethod
    def from_json(cls, data: dict) -> "CustomGeometry":
        w, h = float(data["width"]), float(data["height"])
        if not (0 < w <= 1e7 and 0 < h <= 1e7):
            raise ValueError("geometry frame out of range")
        parts = [GeomPart(Path.from_json(p["commands"]), p.get("fill", "norm"), bool(p.get("stroke", True)))
                 for p in data.get("parts", [])]
        return cls(w, h, parts)

    def dumps(self) -> str:
        return json.dumps(self.to_json(), sort_keys=True, separators=(",", ":"))

    # ------------------------------------------------------------------ DrawingML
    def to_xml(self, quantum: int = 100000, with_ns: bool = True) -> str:
        """Serialise as ``<a:custGeom>`` with integer path coordinates."""
        s = quantum / max(self.width, self.height)
        pw, ph = max(1, round(self.width * s)), max(1, round(self.height * s))
        q = lambda v: str(int(round(v * s)))  # noqa: E731
        ang = lambda v: str(int(round(v * 60000)))  # noqa: E731
        out = ['<a:custGeom%s>' % (f' xmlns:a="{A_NS}"' if with_ns else ""),
               "<a:avLst/><a:gdLst/><a:ahLst/><a:cxnLst/>",
               '<a:rect l="l" t="t" r="r" b="b"/><a:pathLst>']
        for part in self.parts:
            attrs = f' w="{pw}" h="{ph}"'
            if part.fill != "norm":
                attrs += f' fill="{part.fill}"'
            if not part.stroke:
                attrs += ' stroke="0"'
            out.append(f"<a:path{attrs}>")
            for cmd in part.path.commands:
                op = cmd[0]
                if op == "M":
                    out.append(f'<a:moveTo><a:pt x="{q(cmd[1])}" y="{q(cmd[2])}"/></a:moveTo>')
                elif op == "L":
                    out.append(f'<a:lnTo><a:pt x="{q(cmd[1])}" y="{q(cmd[2])}"/></a:lnTo>')
                elif op == "C":
                    pts = "".join(f'<a:pt x="{q(cmd[i])}" y="{q(cmd[i + 1])}"/>' for i in (1, 3, 5))
                    out.append(f"<a:cubicBezTo>{pts}</a:cubicBezTo>")
                elif op == "Q":
                    pts = "".join(f'<a:pt x="{q(cmd[i])}" y="{q(cmd[i + 1])}"/>' for i in (1, 3))
                    out.append(f"<a:quadBezTo>{pts}</a:quadBezTo>")
                elif op == "A":
                    out.append(f'<a:arcTo wR="{q(cmd[1])}" hR="{q(cmd[2])}" stAng="{ang(cmd[3])}" swAng="{ang(cmd[4])}"/>')
                elif op == "Z":
                    out.append("<a:close/>")
            out.append("</a:path>")
        out.append("</a:pathLst></a:custGeom>")
        return "".join(out)

    @classmethod
    def from_xml(cls, xml: str | bytes | etree._Element) -> "CustomGeometry":
        """Parse an ``a:custGeom`` (literal coordinates only) back into the path model.

        Every ``a:path`` is mapped into the frame of the first path's ``w x h``.
        """
        root = xml if isinstance(xml, etree._Element) else etree.fromstring(
            xml.encode("utf-8") if isinstance(xml, str) else xml,
            etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False))
        if root.tag != _A + "custGeom":
            found = root.find(".//" + _A + "custGeom")
            if found is None:
                raise ValueError("no a:custGeom element")
            root = found
        paths = root.findall(f"{_A}pathLst/{_A}path")
        if not paths:
            raise ValueError("custGeom has no a:path")
        fw, fh = float(paths[0].get("w", "0")), float(paths[0].get("h", "0"))
        if fw <= 0 or fh <= 0:
            raise ValueError("first a:path needs positive w/h")
        geom = cls(fw, fh)
        for el in paths:
            pw, ph = float(el.get("w", fw) or fw), float(el.get("h", fh) or fh)
            sx, sy = fw / pw, fh / ph
            p = Path()
            for child in el:
                tag = etree.QName(child).localname
                pts = [(float(pt.get("x")) * sx, float(pt.get("y")) * sy) for pt in child.findall(_A + "pt")]
                if tag == "moveTo":
                    p.move_to(*pts[0])
                elif tag == "lnTo":
                    p.line_to(*pts[0])
                elif tag == "cubicBezTo":
                    p.cubic_to(*pts[0], *pts[1], *pts[2])
                elif tag == "quadBezTo":
                    p.quad_to(*pts[0], *pts[1])
                elif tag == "arcTo":
                    p.arc_to(float(child.get("wR")) * sx, float(child.get("hR")) * sy,
                             float(child.get("stAng")) / 60000.0, float(child.get("swAng")) / 60000.0)
                elif tag == "close":
                    p.close()
                else:
                    raise ValueError(f"unsupported path element a:{tag}")
            stroke_attr = el.get("stroke", "1")
            geom.parts.append(GeomPart(p, el.get("fill", "norm"), stroke_attr not in ("0", "false")))
        return geom

    # ------------------------------------------------------------------ SVG
    def to_svg_d(self, part: GeomPart) -> str:
        return path_to_svg_d(part.path)

    def to_svg(self, fill: str = "#000000", stroke: str | None = None, stroke_width: float = 0.0,
               width_px: float | None = None, height_px: float | None = None) -> str:
        """Standalone SVG; each part becomes a ``<path>`` honouring its fill/stroke flags."""
        wpx = width_px or self.width
        hpx = height_px or self.height
        els = []
        for part in self.parts:
            f = "none" if part.fill == "none" else fill
            st = stroke if (stroke and part.stroke) else "none"
            sw = f' stroke-width="{stroke_width:g}"' if st != "none" else ""
            els.append(f'<path d="{path_to_svg_d(part.path)}" fill="{f}" fill-rule="evenodd" stroke="{st}"{sw}/>')
        return (f'<svg xmlns="{SVG_NS}" width="{wpx:g}" height="{hpx:g}" '
                f'viewBox="0 0 {self.width:g} {self.height:g}">{"".join(els)}</svg>')


def _fmt(v: float) -> str:
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def path_to_svg_d(path: Path) -> str:
    """SVG path data; ``arcTo`` becomes SVG ``A`` (split when the sweep reaches 360 deg)."""
    parts: list[str] = []
    for cmd, cur, end in path.walk():
        op = cmd[0]
        if op in ("M", "L"):
            parts.append(f"{op}{_fmt(cmd[1])} {_fmt(cmd[2])}")
        elif op == "C":
            parts.append("C" + " ".join(_fmt(v) for v in cmd[1:]))
        elif op == "Q":
            parts.append("Q" + " ".join(_fmt(v) for v in cmd[1:]))
        elif op == "Z":
            parts.append("Z")
        elif op == "A":
            w_r, h_r, st, sw = cmd[1:]
            (cx, cy), t0, t1, _ = arc_geometry(cur, w_r, h_r, st, sw)
            n = max(1, int(math.ceil(abs(t1 - t0) / math.pi - 1e-9)))
            for i in range(n):
                tb = t0 + (t1 - t0) * (i + 1) / n
                seg = abs(t1 - t0) / n
                x, y = cx + w_r * math.cos(tb), cy + h_r * math.sin(tb)
                large = 1 if seg > math.pi + 1e-12 else 0
                sweep = 1 if sw > 0 else 0
                parts.append(f"A{_fmt(w_r)} {_fmt(h_r)} 0 {large} {sweep} {_fmt(x)} {_fmt(y)}")
    return " ".join(parts)


# --------------------------------------------------------------------------- validation
_PATH_CHILDREN = {"moveTo": 1, "lnTo": 1, "cubicBezTo": 3, "quadBezTo": 2, "arcTo": 0, "close": 0}
_CUSTGEOM_ORDER = ["avLst", "gdLst", "ahLst", "cxnLst", "rect", "pathLst"]


def validate_custgeom_xml(xml: str | bytes) -> list[str]:
    """Structural check against CT_CustomGeometry2D / CT_Path2D (ECMA-376 Part 1, 20.1.9).

    Returns named findings; an empty list means the element is well-formed for Office.
    """
    findings: list[str] = []
    try:
        root = etree.fromstring(xml.encode("utf-8") if isinstance(xml, str) else xml,
                                etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False))
    except etree.XMLSyntaxError as exc:
        return [f"xml_syntax: {exc}"]
    if root.tag != _A + "custGeom":
        return ["root_not_a_custGeom"]
    names = [etree.QName(c).localname for c in root]
    idx = [(_CUSTGEOM_ORDER.index(n) if n in _CUSTGEOM_ORDER else -1) for n in names]
    if -1 in idx:
        findings.append("unknown_custGeom_child")
    if idx != sorted(idx):
        findings.append("custGeom_child_order")
    if "pathLst" not in names:
        findings.append("missing_pathLst")
    for path in root.iterfind(f"{_A}pathLst/{_A}path"):
        for attr in ("w", "h"):
            v = path.get(attr)
            if v is None or not v.isdigit() or int(v) <= 0:
                findings.append(f"path_{attr}_not_positive_long")
        if path.get("fill") not in (None, *FILL_MODES):
            findings.append("path_fill_mode")
        if path.get("stroke") not in (None, "0", "1", "true", "false"):
            findings.append("path_stroke_flag")
        kids = list(path)
        if kids and etree.QName(kids[0]).localname != "moveTo":
            findings.append("path_must_start_with_moveTo")
        for child in kids:
            tag = etree.QName(child).localname
            if tag not in _PATH_CHILDREN:
                findings.append(f"unknown_path_element:{tag}")
                continue
            pts = child.findall(_A + "pt")
            if len(pts) != _PATH_CHILDREN[tag] or len(child) != len(pts):
                findings.append(f"{tag}_point_count")
            for pt in pts:
                for attr in ("x", "y"):
                    v = pt.get(attr, "")
                    if not v.lstrip("-").isdigit() or abs(int(v)) > 27273042316900:
                        findings.append(f"{tag}_coordinate_not_long")
            if tag == "arcTo":
                for attr in ("wR", "hR", "stAng", "swAng"):
                    v = child.get(attr, "")
                    if not v.lstrip("-").isdigit():
                        findings.append(f"arcTo_{attr}_not_long")
    return sorted(set(findings))
