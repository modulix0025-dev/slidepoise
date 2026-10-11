"""Shared helpers for the procedural generators.

Rule: generators are pure functions of ``(name, seed, params)``. Randomness comes only from a
``random.Random`` seeded with a *string* (Python's string seeding is stable across processes
and platforms, unlike ``hash()``), so the same seed always yields byte-identical XML.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Iterable

from ..custgeom import CustomGeometry, GeomPart, Path, param_arc_to_cubics

Point = tuple[float, float]


def make_rng(name: str, seed: int | str) -> random.Random:
    return random.Random(f"mxstudio.shapes.generators:{name}:{seed}")


@dataclass
class Layer:
    """One editable PowerPoint shape: a role (palette slot) and its geometry."""

    role: str
    geometry: CustomGeometry

    def to_json(self) -> dict:
        return {"role": self.role, "geometry": self.geometry.to_json(), "custgeom": self.geometry.to_xml()}


@dataclass
class GeneratedShape:
    name: str
    seed: int
    params: dict
    layers: list[Layer]
    meta: dict = field(default_factory=dict)

    @property
    def width(self) -> float:
        return self.layers[0].geometry.width

    @property
    def height(self) -> float:
        return self.layers[0].geometry.height

    def merged(self) -> CustomGeometry:
        """All layers in one ``a:custGeom`` (single colour; parts keep their fill modes)."""
        g = CustomGeometry(self.width, self.height)
        for layer in self.layers:
            g.parts.extend(layer.geometry.parts)
        return g

    def to_xml(self) -> str:
        """Deterministic serialisation of every layer (used by the determinism gate)."""
        return "".join(f'<!-- layer:{layer.role} -->{layer.geometry.to_xml()}' for layer in self.layers)

    def to_json(self) -> dict:
        return {"name": self.name, "seed": self.seed, "params": self.params, "width": self.width,
                "height": self.height, "layers": [layer.to_json() for layer in self.layers], "meta": self.meta}


def single(role: str, path: Path, w: float, h: float, fill: str = "norm", stroke: bool = True) -> Layer:
    return Layer(role, CustomGeometry(w, h, [GeomPart(path, fill, stroke)]))


# ---------------------------------------------------------------- primitives
def polygon(points: Iterable[Point]) -> Path:
    pts = list(points)
    p = Path().move_to(*pts[0])
    for x, y in pts[1:]:
        p.line_to(x, y)
    return p.close()


def circle(cx: float, cy: float, r: float) -> Path:
    return ellipse(cx, cy, r, r)


def ellipse(cx: float, cy: float, rx: float, ry: float) -> Path:
    """Closed ellipse as two 180-degree ``arcTo`` (clockwise, starts at the right-most point)."""
    return Path().move_to(cx + rx, cy).arc_to(rx, ry, 0, 180).arc_to(rx, ry, 180, 180).close()


def rounded_rect(x: float, y: float, w: float, h: float, r: float) -> Path:
    r = max(0.0, min(r, w / 2, h / 2))
    p = Path().move_to(x + r, y).line_to(x + w - r, y)
    if r:
        p.arc_to(r, r, 270, 90)
    p.line_to(x + w, y + h - r)
    if r:
        p.arc_to(r, r, 0, 90)
    p.line_to(x + r, y + h)
    if r:
        p.arc_to(r, r, 90, 90)
    p.line_to(x, y + r)
    if r:
        p.arc_to(r, r, 180, 90)
    return p.close()


def star_points(n: int, cx: float, cy: float, r1: float, r2: float, rot_deg: float = -90.0) -> list[Point]:
    pts = []
    for i in range(2 * n):
        r = r1 if i % 2 == 0 else r2
        a = math.radians(rot_deg + i * 180.0 / n)
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def rotate(pt: Point, deg: float, c: Point = (0.0, 0.0)) -> Point:
    a = math.radians(deg)
    x, y = pt[0] - c[0], pt[1] - c[1]
    return (c[0] + x * math.cos(a) - y * math.sin(a), c[1] + x * math.sin(a) + y * math.cos(a))


def catmull_rom_closed(pts: list[Point], tension: float = 0.5) -> Path:
    """Smooth closed curve through ``pts`` as cubic Beziers (centripetal-free, uniform)."""
    n = len(pts)
    p = Path().move_to(*pts[0])
    k = tension / 3.0 * 2.0
    for i in range(n):
        p0, p1, p2, p3 = pts[(i - 1) % n], pts[i], pts[(i + 1) % n], pts[(i + 2) % n]
        c1 = (p1[0] + (p2[0] - p0[0]) * k / 2, p1[1] + (p2[1] - p0[1]) * k / 2)
        c2 = (p2[0] - (p3[0] - p1[0]) * k / 2, p2[1] - (p3[1] - p1[1]) * k / 2)
        p.cubic_to(*c1, *c2, *p2)
    return p.close()


def catmull_rom_open(pts: list[Point], tension: float = 0.5, path: Path | None = None) -> Path:
    p = path if path is not None else Path().move_to(*pts[0])
    k = tension / 3.0 * 2.0
    n = len(pts)
    for i in range(n - 1):
        p0, p1, p2 = pts[max(i - 1, 0)], pts[i], pts[i + 1]
        p3 = pts[min(i + 2, n - 1)]
        c1 = (p1[0] + (p2[0] - p0[0]) * k / 2, p1[1] + (p2[1] - p0[1]) * k / 2)
        c2 = (p2[0] - (p3[0] - p1[0]) * k / 2, p2[1] - (p3[1] - p1[1]) * k / 2)
        p.cubic_to(*c1, *c2, *p2)
    return p


def periodic_noise(rng: random.Random, knots: int = 8):
    """Smooth periodic value noise on [0, 1) with cosine interpolation, range [-1, 1]."""
    vals = [rng.uniform(-1.0, 1.0) for _ in range(max(2, knots))]

    def f(t: float) -> float:
        x = (t % 1.0) * len(vals)
        i = int(math.floor(x))
        frac = x - i
        a, b = vals[i % len(vals)], vals[(i + 1) % len(vals)]
        w = (1 - math.cos(frac * math.pi)) / 2
        return a * (1 - w) + b * w

    return f


def arc_between(p_from: Point, p_to: Point, center: Point, bulge_dir: Point) -> tuple:
    """``("A", r, r, st, sw)`` circle arc from ``p_from`` to ``p_to`` passing on the ``bulge_dir`` side."""
    r = math.hypot(p_from[0] - center[0], p_from[1] - center[1])
    a0 = math.degrees(math.atan2(p_from[1] - center[1], p_from[0] - center[0]))
    a1 = math.degrees(math.atan2(p_to[1] - center[1], p_to[0] - center[0]))
    s = (a1 - a0) % 360.0
    mid = math.radians(a0 + s / 2)
    if math.cos(mid) * bulge_dir[0] + math.sin(mid) * bulge_dir[1] < 0:
        s -= 360.0
    return ("A", r, r, a0, s)


def sine_edge(path: Path, p0: Point, p1: Point, waves: float, amp: float, normal: Point) -> None:
    """Append a sine-displaced edge p0->p1 (cubic Hermite per quarter wave); 0 at both ends."""
    length = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    steps = max(1, int(round(waves * 4)))
    ux, uy = (p1[0] - p0[0]) / length, (p1[1] - p0[1]) / length

    def pos(s: float) -> Point:
        d = amp * math.sin(2 * math.pi * waves * s)
        return (p0[0] + ux * length * s + normal[0] * d, p0[1] + uy * length * s + normal[1] * d)

    def deriv(s: float) -> Point:
        dd = amp * 2 * math.pi * waves * math.cos(2 * math.pi * waves * s)
        return (ux * length + normal[0] * dd, uy * length + normal[1] * dd)

    for i in range(steps):
        s0, s1 = i / steps, (i + 1) / steps
        a, b = pos(s0), pos(s1)
        da, db = deriv(s0), deriv(s1)
        h = (s1 - s0) / 3
        path.cubic_to(a[0] + da[0] * h, a[1] + da[1] * h, b[0] - db[0] * h, b[1] - db[1] * h, b[0], b[1])


def ellipse_arc_cubics(cx, cy, rx, ry, t0, t1) -> list[tuple]:
    return param_arc_to_cubics(cx, cy, rx, ry, t0, t1)


def clampf(v, lo, hi) -> float:
    return max(lo, min(hi, float(v)))
