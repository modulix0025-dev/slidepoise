"""Decorations: ribbon banners, rosette badges, rainbows and wave dividers."""
from __future__ import annotations

import math

from ..boolean import union_all
from ..custgeom import CustomGeometry, GeomPart, Path
from ._util import Layer, circle, polygon, single, star_points


def _subdivide(pts, n=16):
    out = []
    for i in range(len(pts)):
        a, b = pts[i], pts[(i + 1) % len(pts)]
        for k in range(n):
            t = k / n
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return out


def ribbon_banner(rng, w=1200.0, h=300.0, tail=0.14, notch=0.45, fold=0.05, band=0.72, arch=0.0):
    """Classic banner: band (``norm``), tails (``darkenLess``), folds (``darken``) in one shape.

    Parts never overlap, so every renderer fills them identically; ``arch`` bends the banner.
    """
    a = tail * w
    f = fold * w
    bh = band * h
    d = h - bh
    nd = notch * a
    band_pts = [(a, 0), (w - a, 0), (w - a, bh), (a, bh)]
    lt = [(0, d), (a, d), (a, h), (0, h), (nd, (d + h) / 2)]
    rt = [(w - a, d), (w, d), (w - nd, (d + h) / 2), (w, h), (w - a, h)]
    lf = [(a, bh), (a + f, bh), (a, h)]
    rf = [(w - a - f, bh), (w - a, bh), (w - a, h)]
    pad = abs(arch) * h

    def shape(pts):
        if arch:
            pts = _subdivide(pts)
            pts = [(x, y + pad + arch * h * (1 - ((x - w / 2) / (w / 2)) ** 2) * -1) for x, y in pts]
        else:
            pts = [(x, y + pad) for x, y in pts]
        return polygon(pts)

    H = h + 2 * pad
    parts = [GeomPart(shape(lt).extend(shape(rt)), "darkenLess"), GeomPart(shape(lf).extend(shape(rf)), "darken"),
             GeomPart(shape(band_pts), "norm")]
    return [Layer("primary", CustomGeometry(w, H, parts))], {"text_box": [a + f, pad, w - 2 * (a + f), bh]}


def rosette_badge(rng, w=1000.0, points=28, ring=0.16, tails=True):
    """Award rosette: pleated ring, centre disc, optional V-notched ribbon tails (three layers)."""
    r = w / 2 * 0.96
    cx, cy = w / 2, w / 2
    h = w * 1.45 if tails else w
    layers = []
    if tails:
        tw = w * 0.2
        left = [(cx - tw * 1.3, cy), (cx - tw * 0.1, cy), (cx - tw * 0.45, h), (cx - tw * 0.9, h - tw * 0.45),
                (cx - tw * 1.55, h)]
        right = [(cx + tw * 0.1, cy), (cx + tw * 1.3, cy), (cx + tw * 1.55, h), (cx + tw * 0.9, h - tw * 0.45),
                 (cx + tw * 0.45, h)]
        layers.append(single("secondary", union_all([polygon(left), polygon(right)]), w, h))
    pleats = star_points(max(8, int(points)), cx, cy, r, r * (1 - ring * 0.45), -90)
    layers.append(single("primary", polygon(pleats), w, h))
    layers.append(single("accent", circle(cx, cy, r * (1 - ring)), w, h))
    inner = r * (1 - ring) * 0.82
    return layers, {"text_box": [cx - inner * 0.7, cy - inner * 0.7, inner * 1.4, inner * 1.4]}


def rainbow(rng, w=1000.0, bands=6, inner=0.38, gap=0.0):
    """Concentric half annuli (one layer per band so each takes its own colour)."""
    n = max(1, int(bands))
    R = w / 2
    h = R
    rin = R * inner
    step = (R - rin) / n
    layers = []
    for i in range(n):
        ro = R - i * step
        ri = ro - step * (1 - gap)
        p = Path().move_to(R - ro, h).arc_to(ro, ro, 180, 180).line_to(R + ri, h).arc_to(ri, ri, 0, -180).close()
        layers.append(single(f"band_{i}", p, w, h))
    return layers, {"bands": n}


def wave_divider(rng, w=2000.0, h=300.0, waves=3.0, amplitude=0.3, layers=2, phase_shift=0.25):
    """Full-width divider band(s) with a sine top edge (cubic Hermite per quarter wave)."""
    out = []
    n = max(1, int(layers))
    for k in range(n):
        top = h * (0.3 + 0.45 * k / n)
        amp = min(amplitude * h * 0.5 * (1 - 0.25 * k), top * 0.95)
        phase = 2 * math.pi * phase_shift * k
        steps = max(4, int(math.ceil(waves * 4)))

        def y(x):
            return top - amp * math.sin(2 * math.pi * waves * x / w + phase)

        def dy(x):
            return -amp * 2 * math.pi * waves / w * math.cos(2 * math.pi * waves * x / w + phase)

        p = Path().move_to(0, h).line_to(0, y(0))
        for i in range(steps):
            x0, x1 = w * i / steps, w * (i + 1) / steps
            hx = (x1 - x0) / 3
            p.cubic_to(x0 + hx, y(x0) + dy(x0) * hx, x1 - hx, y(x1) - dy(x1) * hx, x1, y(x1))
        p.line_to(w, h).close()
        out.append(single(f"wave_{k}", p, w, h))
    return out, {"layers": n}
