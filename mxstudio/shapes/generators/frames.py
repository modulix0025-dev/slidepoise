"""Frames: scalloped, postage stamp, cloud, torn paper, themed page borders, drop caps, mandalas."""
from __future__ import annotations

import math

from ..boolean import boolean, stroke_to_fill, union_all
from ..custgeom import Path
from ._util import (arc_between, catmull_rom_open, circle, ellipse, polygon, rounded_rect, sine_edge,
                    single, star_points)


def _edge_counts(length: float, size: float) -> int:
    return max(2, int(round(length / max(size, 1e-6))))


def scalloped_frame(rng, w=1000.0, h=700.0, scallop=70.0, band=90.0, inward=False, hole=True):
    """Rectangle whose edge is a run of semicircles (``inward`` turns them into bites)."""
    r_guess = scallop / 2
    inset = 0.0 if inward else r_guess
    x0, y0, x1, y1 = inset, inset, w - inset, h - inset
    nx, ny = _edge_counts(x1 - x0, scallop), _edge_counts(y1 - y0, scallop)
    dx, dy = (x1 - x0) / nx, (y1 - y0) / ny
    sw = -180.0 if inward else 180.0
    p = Path().move_to(x0, y0)
    for _ in range(nx):
        p.arc_to(dx / 2, dx / 2, 180, sw)
    for _ in range(ny):
        p.arc_to(dy / 2, dy / 2, 270, sw)
    for _ in range(nx):
        p.arc_to(dx / 2, dx / 2, 0, sw)
    for _ in range(ny):
        p.arc_to(dy / 2, dy / 2, 90, sw)
    p.close()
    if hole:
        b = max(band, scallop * 0.75)
        p.extend(rounded_rect(b, b, w - 2 * b, h - 2 * b, b * 0.25))
    return [single("primary", p, w, h)], {"scallops": 2 * (nx + ny)}


def stamp_frame(rng, w=800.0, h=1000.0, perforation=46.0, notch=0.55, band=70.0, hole=True):
    """Postage-stamp outline: straight edges with evenly spaced inward semicircle notches."""
    nx, ny = _edge_counts(w, perforation), _edge_counts(h, perforation)
    p = Path().move_to(0, 0)

    def edge(n, length, start_angle, along):
        step = length / n
        r = step * notch / 2
        for i in range(n):
            a = i * step + step / 2 - r
            p.line_to(*along(a))
            p.arc_to(r, r, start_angle, -180)  # ends at along(a + 2r): an inward bite
        ex, ey = along(length)
        p.line_to(ex, ey)

    edge(nx, w, 180, lambda s: (s, 0.0))
    edge(ny, h, 270, lambda s: (w, s))
    edge(nx, w, 0, lambda s: (w - s, h))
    edge(ny, h, 90, lambda s: (0.0, h - s))
    p.close()
    if hole:
        b = max(band, perforation)
        p.extend(rounded_rect(b, b, w - 2 * b, h - 2 * b, 0))
    return [single("primary", p, w, h)], {"notches": 2 * (nx + ny)}


def cloud_frame(rng, w=1000.0, h=700.0, bumps=14, variance=0.25, puff=0.35, hole=True, hole_inset=0.22):
    """Cloud made of circular bumps around an ellipse; optional elliptical window."""
    bumps = max(5, int(bumps))
    cx, cy = w / 2, h / 2
    # leave room for the bulge: chord ~ 2*pi*R/bumps, bulge <= chord
    margin = max(w, h) * math.pi / bumps * (0.55 + puff * 0.45)
    rx, ry = w / 2 - margin, h / 2 - margin
    if rx <= 0 or ry <= 0:
        raise ValueError("too few bumps for this size")
    angles = []
    for i in range(bumps):
        jitter = rng.uniform(-variance, variance) * 0.5
        angles.append((i + 0.5 + jitter) / bumps * 2 * math.pi)
    pts = [(cx + rx * math.cos(a), cy + ry * math.sin(a)) for a in angles]
    p = Path().move_to(*pts[0])
    for i in range(bumps):
        a, b = pts[i], pts[(i + 1) % bumps]
        chord = math.hypot(b[0] - a[0], b[1] - a[1])
        k = 1.0 + puff * rng.uniform(0.6, 1.0)
        r = chord / 2 * k
        mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        # outward unit normal of the chord (the centre must sit on its perpendicular bisector)
        nx, ny = (b[1] - a[1]) / chord, -(b[0] - a[0]) / chord
        if nx * (mx - cx) + ny * (my - cy) < 0:
            nx, ny = -nx, -ny
        d = math.sqrt(max(r * r - chord * chord / 4, 0.0))
        center = (mx - nx * d, my - ny * d)
        p.commands.append(arc_between(a, b, center, (nx, ny)))
    p.close()
    if hole:
        p.extend(ellipse(cx, cy, rx * (1 - hole_inset), ry * (1 - hole_inset)))
    return [single("primary", p, w, h)], {"bumps": bumps}


def _displace(rng, a, b, depth, amp, normal, lo, hi):
    pts = [a, b]
    offs = [0.0, 0.0]
    for level in range(depth):
        new_pts, new_offs = [pts[0]], [offs[0]]
        scale = amp / (2 ** (level * 0.9))
        for i in range(len(pts) - 1):
            mx = (pts[i][0] + pts[i + 1][0]) / 2
            my = (pts[i][1] + pts[i + 1][1]) / 2
            mo = (offs[i] + offs[i + 1]) / 2 + rng.uniform(-scale, scale)
            mo = max(lo, min(hi, mo))
            new_pts += [(mx, my), pts[i + 1]]
            new_offs += [mo, offs[i + 1]]
        pts, offs = new_pts, new_offs
    return [(x + normal[0] * o, y + normal[1] * o) for (x, y), o in zip(pts, offs)]


def torn_paper(rng, w=1000.0, h=600.0, edges="top,bottom", roughness=0.035, detail=7):
    """Paper rectangle with torn (fractal midpoint displacement) edges, kept inside the frame."""
    torn = {e.strip() for e in str(edges).split(",") if e.strip()}
    amp = roughness * max(w, h)
    depth = max(2, min(10, int(detail)))
    band = amp * 1.6
    corners = [(0, 0), (w, 0), (w, h), (0, h)]
    sides = [("top", (0, 1)), ("right", (-1, 0)), ("bottom", (0, -1)), ("left", (1, 0))]
    pts = []
    for i, (name, inward) in enumerate(sides):
        a, b = corners[i], corners[(i + 1) % 4]
        if name in torn:
            a2 = (a[0] + inward[0] * band / 2, a[1] + inward[1] * band / 2)
            b2 = (b[0] + inward[0] * band / 2, b[1] + inward[1] * band / 2)
            seg = _displace(rng, a2, b2, depth, amp, inward, -band / 2, band / 2)
            pts.extend(seg[:-1])
        else:
            pts.append(a)
    return [single("primary", polygon(pts), w, h)], {"torn_edges": sorted(torn)}


def _leaf(cx, cy, length, width, angle_deg) -> Path:
    a = math.radians(angle_deg)
    ux, uy = math.cos(a), math.sin(a)
    nx, ny = -uy, ux
    tip = (cx + ux * length, cy + uy * length)
    p = Path().move_to(cx, cy)
    p.cubic_to(cx + ux * length * 0.3 + nx * width, cy + uy * length * 0.3 + ny * width,
               cx + ux * length * 0.8 + nx * width * 0.5, cy + uy * length * 0.8 + ny * width * 0.5, *tip)
    p.cubic_to(cx + ux * length * 0.8 - nx * width * 0.5, cy + uy * length * 0.8 - ny * width * 0.5,
               cx + ux * length * 0.3 - nx * width, cy + uy * length * 0.3 - ny * width, cx, cy)
    return p.close()


def page_border(rng, theme="sea_waves", w=1480.0, h=2100.0, band=120.0, density=1.0):
    """Themed page border: ``sea_waves``, ``vines``, ``stars`` or ``candy`` (A5 in 0.1 mm by default)."""
    b = band
    if theme == "sea_waves":
        wl = 160.0 / max(density, 0.2)
        amp = b * 0.22
        inner = Path().move_to(b, b)
        for p0, p1, nrm in (((b, b), (w - b, b), (0, 1)), ((w - b, b), (w - b, h - b), (-1, 0)),
                            ((w - b, h - b), (b, h - b), (0, -1)), ((b, h - b), (b, b), (1, 0))):
            length = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
            sine_edge(inner, p0, p1, max(1, round(length / wl)), amp, nrm)
        inner.close()
        outer = rounded_rect(0, 0, w, h, b * 0.3)
        return [single("primary", outer.extend(inner), w, h)], {"theme": theme}
    if theme == "vines":
        paths = []
        mid = b / 2
        step = 120.0 / max(density, 0.2)
        for p0, p1, nrm in (((mid, mid), (w - mid, mid), (0, 1)), ((w - mid, mid), (w - mid, h - mid), (-1, 0)),
                            ((w - mid, h - mid), (mid, h - mid), (0, -1)), ((mid, h - mid), (mid, mid), (1, 0))):
            length = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
            stem = Path().move_to(*p0)
            sine_edge(stem, p0, p1, max(1, round(length / (step * 2))), b * 0.12, nrm)
            paths.append(stroke_to_fill(stem, b * 0.07, tol=0.5))
            n = int(length // step)
            ux, uy = (p1[0] - p0[0]) / length, (p1[1] - p0[1]) / length
            base = math.degrees(math.atan2(uy, ux))
            for i in range(1, n):
                s = i * step + rng.uniform(-step * 0.15, step * 0.15)
                side = 1 if i % 2 else -1
                cx, cy = p0[0] + ux * s, p0[1] + uy * s
                ang = base + side * (50 + rng.uniform(-12, 12))
                paths.append(_leaf(cx, cy, b * 0.42, b * 0.14, ang))
        return [single("primary", union_all(paths, tol=0.5), w, h)], {"theme": theme}
    if theme == "stars":
        mid = b / 2
        step = 130.0 / max(density, 0.2)
        stars = []
        perimeter = [((mid, mid), (w - mid, mid)), ((w - mid, mid), (w - mid, h - mid)),
                     ((w - mid, h - mid), (mid, h - mid)), ((mid, h - mid), (mid, mid))]
        k = 0
        for p0, p1 in perimeter:
            length = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
            n = max(1, int(length // step))
            for i in range(n):
                s = (i + 0.5) / n
                cx, cy = p0[0] + (p1[0] - p0[0]) * s, p0[1] + (p1[1] - p0[1]) * s
                r = b * (0.42 if k % 2 == 0 else 0.28)
                stars.append(polygon(star_points(5, cx, cy, r, r * 0.45, -90 + rng.uniform(-15, 15))))
                k += 1
        return [single("primary", union_all(stars, tol=0.5), w, h)], {"theme": theme, "stars": k}
    if theme == "candy":
        outer = rounded_rect(0, 0, w, h, b * 0.5)
        inner = rounded_rect(b, b, w - 2 * b, h - 2 * b, b * 0.2)
        frame = Path().extend(outer).extend(inner)
        stripes = []
        sw = b * 0.5 / max(density, 0.2)
        x = -h
        while x < w + h:
            stripes.append(polygon([(x, 0), (x + sw, 0), (x + sw + h, h), (x + h, h)]))
            x += sw * 2
        striped = boolean(stripes, [outer], "intersect", tol=0.5)
        striped = boolean([striped], [inner], "subtract", tol=0.5)
        dots = []
        for cx, cy in ((b / 2, b / 2), (w - b / 2, b / 2), (w - b / 2, h - b / 2), (b / 2, h - b / 2)):
            dots.append(circle(cx, cy, b * 0.42))
        return ([single("secondary", frame, w, h), single("primary", striped, w, h),
                 single("accent", Path().extend(dots[0]).extend(dots[1]).extend(dots[2]).extend(dots[3]), w, h)],
                {"theme": theme})
    raise ValueError("theme must be sea_waves, vines, stars or candy")


def drop_cap_ornament(rng, w=600.0, h=600.0, flourish=0.5, frame=0.08, shape="square"):
    """Frame for a drop-cap letter with a spiral curl at each corner (the letter is a text box)."""
    b = min(w, h) * frame
    m = b * 1.9  # margin that holds the curls
    if shape == "circle":
        outer = ellipse(w / 2, h / 2, w / 2 - m, h / 2 - m)
        inner = ellipse(w / 2, h / 2, w / 2 - m - b, h / 2 - m - b)
        corners = [(w / 2 + (w / 2 - m) * math.cos(a) * 0.98, h / 2 + (h / 2 - m) * math.sin(a) * 0.98, a)
                   for a in (math.radians(d) for d in (225, 315, 45, 135))]
    else:
        outer = rounded_rect(m, m, w - 2 * m, h - 2 * m, b)
        inner = rounded_rect(m + b, m + b, w - 2 * m - 2 * b, h - 2 * m - 2 * b, b * 0.6)
        corners = [(m + b * 0.3, m + b * 0.3, math.radians(225)), (w - m - b * 0.3, m + b * 0.3, math.radians(315)),
                   (w - m - b * 0.3, h - m - b * 0.3, math.radians(45)), (m + b * 0.3, h - m - b * 0.3, math.radians(135))]
    ring = boolean([outer], [inner], "subtract", tol=0.3)
    curls = []
    turns = 1.0 + 0.8 * flourish
    big = m * 0.62
    for x0, y0, out_ang in corners:
        # curl centre sits outside the corner; the spiral starts at the corner and winds inward
        cx, cy = x0 + math.cos(out_ang) * big, y0 + math.sin(out_ang) * big
        start = out_ang + math.pi
        pts = []
        for i in range(33):
            t = i / 32
            r = big * (1 - 0.8 * t)
            ang = start + t * turns * 2 * math.pi
            pts.append((cx + math.cos(ang) * r, cy + math.sin(ang) * r))
        curls.append(stroke_to_fill(catmull_rom_open(pts), b * 0.32, tol=0.3))
    return [single("primary", union_all([ring, *curls], tol=0.3), w, h)], {
        "text_box": [m + b, m + b, w - 2 * (m + b), h - 2 * (m + b)]}


def mandala_frame(rng, w=1000.0, h=1000.0, symmetry=12, rings=3, petal=0.5, hole=0.42):
    """Radial-symmetry frame: rings of almond petals (x``symmetry``) around a round window."""
    n = max(3, int(symmetry))
    cx, cy = w / 2, h / 2
    rmax = min(w, h) / 2
    rhole = rmax * hole
    petals = []
    for k in range(max(1, int(rings))):
        t = (k + 1) / max(1, int(rings))
        r0 = rhole * 0.92 + (rmax - rhole) * (t - 1 / max(1, int(rings))) * 0.9
        length = (rmax - rhole) / max(1, int(rings)) * (1.25 + 0.3 * petal)
        width = 2 * math.pi * (r0 + length / 2) / n * (0.35 + 0.4 * petal)
        offset = 0.5 if k % 2 else 0.0
        for i in range(n):
            ang = (i + offset) * 360.0 / n
            a = math.radians(ang)
            sx, sy = cx + math.cos(a) * r0, cy + math.sin(a) * r0
            length_k = min(length, rmax - r0 - 1)
            petals.append(_leaf(sx, sy, length_k, width / 2, ang))
    petals.append(boolean([circle(cx, cy, rhole * 1.08)], [circle(cx, cy, rhole)], "subtract", tol=0.3))
    body = union_all(petals, tol=0.3)
    body = boolean([body], [circle(cx, cy, rhole)], "subtract", tol=0.3)
    return [single("primary", body, w, h)], {"symmetry": n, "window": [cx - rhole, cy - rhole, 2 * rhole, 2 * rhole]}
