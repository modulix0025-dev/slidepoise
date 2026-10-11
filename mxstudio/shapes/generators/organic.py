"""Organic shapes: superformula blobs and hand-drawn (rough.js-style) outlines.

The rough outline ports the *idea* of rough.js (MIT, Preet Shihn): every edge is redrawn as a
cubic whose ends and controls are jittered by ``roughness``, bowed sideways by ``bowing``,
and drawn ``strokes`` times. Nothing is copied; parameters keep rough.js's meaning.
"""
from __future__ import annotations

import math

from ..custgeom import CustomGeometry, GeomPart, Path
from ._util import Layer, catmull_rom_closed, catmull_rom_open, ellipse, periodic_noise, polygon


def superformula(phi: float, m: float, n1: float, n2: float, n3: float, a: float = 1.0, b: float = 1.0) -> float:
    t1 = abs(math.cos(m * phi / 4) / a) ** n2
    t2 = abs(math.sin(m * phi / 4) / b) ** n3
    s = (t1 + t2) ** (-1.0 / n1) if (t1 + t2) > 0 else 1.0
    return s


def blob(rng, w=1000.0, h=1000.0, m=5.0, n1=4.0, n2=7.0, n3=7.0, noise=0.12, points=40, wobble_knots=7):
    """Superformula outline modulated by smooth periodic noise, smoothed with Catmull-Rom."""
    noise_fn = periodic_noise(rng, int(wobble_knots))
    rot = rng.uniform(0, 2 * math.pi)
    n = max(8, int(points))
    radii = [superformula(2 * math.pi * i / n, m, n1, n2, n3) for i in range(n)]
    rmax = max(radii) or 1.0
    radii = [max(0.25, r / rmax * (1 + noise * noise_fn(i / n))) for i, r in enumerate(radii)]
    scale = 1 / max(radii)
    pts = []
    for i, r in enumerate(radii):
        phi = 2 * math.pi * i / n + rot
        pts.append((w / 2 + math.cos(phi) * r * scale * (w / 2) * 0.92,
                    h / 2 + math.sin(phi) * r * scale * (h / 2) * 0.92))
    return [Layer("primary", CustomGeometry(w, h, [GeomPart(catmull_rom_closed(pts))]))], {"points": n}


def _gain(length: float) -> float:
    if length < 200:
        return 1.0
    if length > 500:
        return 0.4
    return -0.0016668 * length + 1.233334


def _rough_line(rng, p1, p2, roughness, bowing, max_offset, path: Path, move: bool, overlay: bool):
    (x1, y1), (x2, y2) = p1, p2
    length = math.hypot(x2 - x1, y2 - y1)
    gain = _gain(length / max_offset * 2)  # rough.js gains are tuned for offset 2 px
    offset = max_offset
    if offset * offset * 100 > length * length:
        offset = length / 10
    half = offset / 2
    diverge = 0.2 + rng.random() * 0.2
    mdx = bowing * max_offset * (y2 - y1) / 200
    mdy = bowing * max_offset * (x1 - x2) / 200

    def jitter(v):
        return roughness * gain * (rng.random() * 2 * v - v)

    mdx += jitter(mdx)
    mdy += jitter(mdy)
    o = half if overlay else offset
    if move:
        path.move_to(x1 + jitter(o), y1 + jitter(o))
    path.cubic_to(mdx + x1 + (x2 - x1) * diverge + jitter(o), mdy + y1 + (y2 - y1) * diverge + jitter(o),
                  mdx + x1 + 2 * (x2 - x1) * diverge + jitter(o), mdy + y1 + 2 * (y2 - y1) * diverge + jitter(o),
                  x2 + jitter(o), y2 + jitter(o))


def rough_outline(rng, w=1000.0, h=700.0, base="rect", sides=6, roughness=1.0, bowing=1.0, strokes=2,
                  fill=True, curve_steps=11):
    """Hand-drawn look: clean fill (no line) + ``strokes`` jittered outline passes (line only)."""
    pad = max(w, h) * 0.04
    max_offset = max(w, h) / 120.0
    parts: list[GeomPart] = []
    if base == "ellipse":
        clean = ellipse(w / 2, h / 2, w / 2 - pad, h / 2 - pad)
    elif base == "polygon":
        k = max(3, int(sides))
        pts = [(w / 2 + (w / 2 - pad) * math.cos(-math.pi / 2 + 2 * math.pi * i / k),
                h / 2 + (h / 2 - pad) * math.sin(-math.pi / 2 + 2 * math.pi * i / k)) for i in range(k)]
        clean = polygon(pts)
    else:
        clean = polygon([(pad, pad), (w - pad, pad), (w - pad, h - pad), (pad, h - pad)])
    if fill:
        parts.append(GeomPart(clean, "norm", False))
    for s in range(max(1, int(strokes))):
        p = Path()
        if base == "ellipse":
            n = max(6, int(curve_steps))
            start = rng.uniform(0, 2 * math.pi)
            overlap = rng.uniform(0.05, 0.25)
            pts = []
            for i in range(n + 2):
                a = start + (2 * math.pi + overlap) * i / (n + 1)
                jr = 1 + roughness * rng.uniform(-0.02, 0.02) * (1 + s)
                pts.append((w / 2 + (w / 2 - pad) * jr * math.cos(a) + rng.uniform(-1, 1) * roughness * max_offset * 0.6,
                            h / 2 + (h / 2 - pad) * jr * math.sin(a) + rng.uniform(-1, 1) * roughness * max_offset * 0.6))
            catmull_rom_open(pts, path=p.move_to(*pts[0]))
        else:
            corners = [(c[1], c[2]) for c in clean.commands if c[0] in ("M", "L")]
            for i in range(len(corners)):
                _rough_line(rng, corners[i], corners[(i + 1) % len(corners)], roughness, bowing, max_offset, p,
                            move=True, overlay=s > 0)
        parts.append(GeomPart(p, "none", True))
    return [Layer("primary", CustomGeometry(w, h, parts))], {"strokes": int(strokes)}
