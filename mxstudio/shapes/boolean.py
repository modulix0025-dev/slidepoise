"""Boolean operations and offsets on the path model (pyclipper, MIT/Boost).

Rule: curves are flattened to a tolerance far below print resolution before clipping
(default 0.05 design units), results come back as closed ``lnTo`` polygons whose fill is
non-overlapping, so even-odd and non-zero renderers agree.
"""
from __future__ import annotations

import pyclipper

from .custgeom import CustomGeometry, GeomPart, Path
from .raster import flatten_path

SCALE = 1000.0  # clipper works on integers
OPS = {"union": pyclipper.CT_UNION, "subtract": pyclipper.CT_DIFFERENCE,
       "intersect": pyclipper.CT_INTERSECTION, "xor": pyclipper.CT_XOR}


def to_int_polys(path: Path, tol: float = 0.05) -> list[list[tuple[int, int]]]:
    out = []
    for poly in flatten_path(path, tol):
        pts = [(int(round(x * SCALE)), int(round(y * SCALE))) for x, y in poly]
        dedup = [p for i, p in enumerate(pts) if i == 0 or p != pts[i - 1]]
        if len(dedup) > 1 and dedup[0] == dedup[-1]:
            dedup.pop()
        if len(dedup) >= 3:
            out.append(dedup)
    return out


def from_int_polys(polys) -> Path:
    p = Path()
    for poly in polys:
        if len(poly) < 3:
            continue
        p.move_to(poly[0][0] / SCALE, poly[0][1] / SCALE)
        for x, y in poly[1:]:
            p.line_to(x / SCALE, y / SCALE)
        p.close()
    return p


def _simplify(polys, tol: float):
    if tol <= 0:
        return polys
    eps = tol * SCALE
    out = []
    for poly in polys:
        simp = _rdp_closed(poly, eps)
        if len(simp) >= 3:
            out.append(simp)
    return out


def _rdp_closed(poly, eps):
    if len(poly) < 4:
        return poly
    # split at the farthest point from poly[0] to run open RDP on two halves
    x0, y0 = poly[0]
    far = max(range(len(poly)), key=lambda i: (poly[i][0] - x0) ** 2 + (poly[i][1] - y0) ** 2)
    a = _rdp(poly[: far + 1], eps)
    b = _rdp(poly[far:] + [poly[0]], eps)
    return a[:-1] + b[:-1]


def _rdp(pts, eps):
    if len(pts) < 3:
        return list(pts)
    (x1, y1), (x2, y2) = pts[0], pts[-1]
    dx, dy = x2 - x1, y2 - y1
    norm = (dx * dx + dy * dy) ** 0.5 or 1.0
    best, idx = -1.0, 0
    for i in range(1, len(pts) - 1):
        d = abs(dy * (pts[i][0] - x1) - dx * (pts[i][1] - y1)) / norm
        if d > best:
            best, idx = d, i
    if best <= eps:
        return [pts[0], pts[-1]]
    return _rdp(pts[: idx + 1], eps)[:-1] + _rdp(pts[idx:], eps)


def _normalise(path: Path, tol: float, fill_rule: str):
    """One path -> non-overlapping polygons (outers positive, holes negative) under its fill rule."""
    polys = to_int_polys(path, tol)
    if not polys:
        return []
    pc = pyclipper.Pyclipper()
    pc.AddPaths(polys, pyclipper.PT_SUBJECT, True)
    ft = pyclipper.PFT_NONZERO if fill_rule == "nonzero" else pyclipper.PFT_EVENODD
    return pc.Execute(pyclipper.CT_UNION, ft, ft)


def _execute(a, b, op):
    pc = pyclipper.Pyclipper()
    if a:
        pc.AddPaths(a, pyclipper.PT_SUBJECT, True)
    if b:
        pc.AddPaths(b, pyclipper.PT_CLIP, True)
    if not a:
        return []
    return pc.Execute(op, pyclipper.PFT_EVENODD, pyclipper.PFT_EVENODD)


def _union_sets(sets):
    """Pairwise (divide and conquer) union of normalised polygon sets."""
    sets = [s for s in sets if s]
    if not sets:
        return []
    while len(sets) > 1:
        nxt = []
        for i in range(0, len(sets), 2):
            nxt.append(_execute(sets[i], sets[i + 1], pyclipper.CT_UNION) if i + 1 < len(sets) else sets[i])
        sets = nxt
    return sets[0]


def boolean(subject: list[Path], clip: list[Path], op: str, tol: float = 0.05, simplify: float = 0.0,
            fill_rule: str = "evenodd") -> Path:
    """``op`` in union/subtract/intersect/xor over filled paths.

    Each input path is first read under ``fill_rule`` (DrawingML paths are even-odd), so the
    orientation in which a sub-path was drawn never punches accidental holes.
    """
    if op not in OPS:
        raise ValueError(f"op must be one of {sorted(OPS)}")
    subj = _union_sets([_normalise(p, tol, fill_rule) for p in subject])
    clp = _union_sets([_normalise(p, tol, fill_rule) for p in clip])
    if not subj:
        return Path()
    if not clp:
        if op == "intersect":
            return Path()
        return from_int_polys(_simplify(subj, simplify))
    return from_int_polys(_simplify(_execute(subj, clp, OPS[op]), simplify))


def union_all(paths: list[Path], tol: float = 0.05, fill_rule: str = "evenodd") -> Path:
    return boolean(paths, [], "union", tol, fill_rule=fill_rule)


def offset(paths: list[Path], delta: float, tol: float = 0.05, join: str = "round",
           arc_tolerance: float = 0.05, outer_only: bool = False) -> Path:
    """Grow (``delta`` > 0) or shrink a filled outline; ``outer_only`` drops holes (die-cut)."""
    jt = {"round": pyclipper.JT_ROUND, "miter": pyclipper.JT_MITER, "square": pyclipper.JT_SQUARE}[join]
    pco = pyclipper.PyclipperOffset(miter_limit=2.0, arc_tolerance=arc_tolerance * SCALE)
    base = _union_sets([_normalise(p, tol, "evenodd") for p in paths])
    if not base:
        return Path()
    pco.AddPaths(base, jt, pyclipper.ET_CLOSEDPOLYGON)
    result = pco.Execute(delta * SCALE)
    if outer_only:
        result = [p for p in result if pyclipper.Orientation(p)]
    return from_int_polys(result)


def stroke_to_fill(path: Path, width: float, tol: float = 0.05, cap: str = "round", join: str = "round") -> Path:
    """Outline an open stroke as a filled polygon (for strokes that must print as shapes)."""
    et = {"round": pyclipper.ET_OPENROUND, "butt": pyclipper.ET_OPENBUTT, "square": pyclipper.ET_OPENSQUARE}[cap]
    jt = {"round": pyclipper.JT_ROUND, "miter": pyclipper.JT_MITER, "square": pyclipper.JT_SQUARE}[join]
    pco = pyclipper.PyclipperOffset(arc_tolerance=tol * SCALE)
    for poly in flatten_path(path, tol):
        pts = [(int(round(x * SCALE)), int(round(y * SCALE))) for x, y in poly]
        if len(pts) >= 2:
            pco.AddPath(pts, jt, et)
    result = pco.Execute(width / 2 * SCALE)
    pc = pyclipper.Pyclipper()
    if not result:
        return Path()
    pc.AddPaths(result, pyclipper.PT_SUBJECT, True)
    return from_int_polys(pc.Execute(pyclipper.CT_UNION, pyclipper.PFT_NONZERO, pyclipper.PFT_NONZERO))


def area(path: Path, tol: float = 0.05, fill_rule: str = "evenodd") -> float:
    polys = to_int_polys(path, tol)
    if not polys:
        return 0.0
    pc = pyclipper.Pyclipper()
    pc.AddPaths(polys, pyclipper.PT_SUBJECT, True)
    ft = pyclipper.PFT_NONZERO if fill_rule == "nonzero" else pyclipper.PFT_EVENODD
    res = pc.Execute(pyclipper.CT_UNION, ft, ft)
    return sum(pyclipper.Area(p) for p in res) / (SCALE * SCALE)


def geometry_boolean(subject: CustomGeometry, clip: CustomGeometry, op: str) -> CustomGeometry:
    res = boolean([p.path for p in subject.parts if p.fill != "none"],
                  [p.path for p in clip.parts if p.fill != "none"], op)
    return CustomGeometry(subject.width, subject.height, [GeomPart(res)])
