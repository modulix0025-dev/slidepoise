"""Confetti / star scatter with seeded Poisson-disk placement (Bridson 2007).

Rule: nothing is placed inside a keep-out rectangle (text boxes and faces from the page's
semantic map, grown by ``margin`` + the piece radius), and no two pieces are closer than
``radius``. The keep-out list is a fact handed in by the caller; this code never guesses it.
"""
from __future__ import annotations

import math

from ..custgeom import CustomGeometry, GeomPart, Path
from ._util import Layer, circle, polygon, rotate, star_points


def keepouts_from_semantic_map(semantic_map: dict) -> list[list[float]]:
    """Text boxes and faces (``[x, y, w, h]``) that confetti must avoid."""
    out = []
    for box in semantic_map.get("text_boxes", []) or []:
        out.append([float(v) for v in (box.get("bbox") if isinstance(box, dict) else box)])
    for char in semantic_map.get("characters", []) or []:
        for key in ("face", "bbox"):
            if char.get(key) is not None and len(char[key]) == 4:
                out.append([float(v) for v in char[key]])
                break
    for box in semantic_map.get("keep_out", []) or []:
        out.append([float(v) for v in box])
    return out


def poisson_disk(rng, w: float, h: float, radius: float, keepouts=(), margin: float = 0.0, k: int = 30,
                 max_points: int = 4000) -> list[tuple[float, float]]:
    cell = radius / math.sqrt(2)
    gw, gh = int(math.ceil(w / cell)), int(math.ceil(h / cell))
    grid: dict[tuple[int, int], tuple[float, float]] = {}
    boxes = [(x - margin, y - margin, x + bw + margin, y + bh + margin) for x, y, bw, bh in keepouts]

    def free(pt):
        x, y = pt
        if not (margin <= x <= w - margin and margin <= y <= h - margin):
            return False
        if any(x0 <= x <= x1 and y0 <= y <= y1 for x0, y0, x1, y1 in boxes):
            return False
        gx, gy = int(x / cell), int(y / cell)
        for i in range(max(gx - 2, 0), min(gx + 3, gw)):
            for j in range(max(gy - 2, 0), min(gy + 3, gh)):
                q = grid.get((i, j))
                if q and (q[0] - x) ** 2 + (q[1] - y) ** 2 < radius * radius:
                    return False
        return True

    points: list[tuple[float, float]] = []
    active: list[tuple[float, float]] = []
    for _ in range(200):  # first sample outside keep-outs
        p0 = (rng.uniform(margin, w - margin), rng.uniform(margin, h - margin))
        if free(p0):
            break
    else:
        return []
    grid[(int(p0[0] / cell), int(p0[1] / cell))] = p0
    points.append(p0)
    active.append(p0)
    while active and len(points) < max_points:
        idx = rng.randrange(len(active))
        base = active[idx]
        for _ in range(k):
            a = rng.uniform(0, 2 * math.pi)
            d = rng.uniform(radius, 2 * radius)
            cand = (base[0] + math.cos(a) * d, base[1] + math.sin(a) * d)
            if free(cand):
                grid[(int(cand[0] / cell), int(cand[1] / cell))] = cand
                points.append(cand)
                active.append(cand)
                break
        else:
            active.pop(idx)
    return points


def _piece(kind: str, x: float, y: float, s: float, rot: float) -> Path:
    if kind == "circle":
        return circle(x, y, s * 0.5)
    if kind == "star":
        return polygon(star_points(5, x, y, s * 0.6, s * 0.26, rot - 90))
    if kind == "triangle":
        return polygon([rotate((x + s * 0.55 * math.cos(math.radians(a)), y + s * 0.55 * math.sin(math.radians(a))),
                               rot, (x, y)) for a in (-90, 30, 150)])
    # rect strip
    pts = [(x - s * 0.5, y - s * 0.18), (x + s * 0.5, y - s * 0.18), (x + s * 0.5, y + s * 0.18),
           (x - s * 0.5, y + s * 0.18)]
    return polygon([rotate(p, rot, (x, y)) for p in pts])


def confetti_scatter(rng, w=1480.0, h=2100.0, radius=110.0, size=34.0, kinds="star,circle,rect,triangle",
                     colors=4, keepouts=(), margin=24.0, semantic_map=None):
    """Poisson-disk confetti; one layer per colour group (``confetti_0`` ...)."""
    boxes = [list(map(float, b)) for b in keepouts]
    if semantic_map:
        boxes += keepouts_from_semantic_map(semantic_map)
    kinds_list = [k.strip() for k in str(kinds).split(",") if k.strip()] or ["circle"]
    radius = max(float(radius), float(size) * 1.45)  # pieces never touch
    pts = poisson_disk(rng, w, h, radius, boxes, margin + size * 0.7)  # 0.7*size >= piece extent
    groups = [Path() for _ in range(max(1, int(colors)))]
    placed = []
    for x, y in pts:
        kind = kinds_list[rng.randrange(len(kinds_list))]
        g = rng.randrange(len(groups))
        s = size * rng.uniform(0.7, 1.15)
        rot = rng.uniform(0, 360)
        groups[g].extend(_piece(kind, x, y, s, rot))
        placed.append({"x": round(x, 3), "y": round(y, 3), "kind": kind, "group": g})
    layers = [Layer(f"confetti_{i}", CustomGeometry(w, h, [GeomPart(p)])) for i, p in enumerate(groups) if p.commands]
    if not layers:
        raise ValueError("no room for confetti outside the keep-out areas")
    return layers, {"pieces": placed, "keepouts": boxes, "min_distance": radius}
