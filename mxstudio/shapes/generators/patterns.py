"""Vector pattern fills (dots, stripes, checks, hearts) clipped to a region.

Rule: motifs fully inside the region keep their curves; only motifs crossing the region edge
are clipped (pyclipper), so the fill stays print-sharp and editable as one ``a:custGeom``.
"""
from __future__ import annotations

import math

from ..boolean import area, boolean
from ..custgeom import CustomGeometry, GeomPart, Path
from ._util import Layer, circle, ellipse, polygon, rotate, rounded_rect


def heart(cx: float, cy: float, s: float) -> Path:
    p = Path().move_to(cx, cy + s * 0.45)
    p.cubic_to(cx - s * 0.55, cy + s * 0.05, cx - s * 0.55, cy - s * 0.45, cx - s * 0.25, cy - s * 0.45)
    p.cubic_to(cx - s * 0.1, cy - s * 0.45, cx, cy - s * 0.35, cx, cy - s * 0.2)
    p.cubic_to(cx, cy - s * 0.35, cx + s * 0.1, cy - s * 0.45, cx + s * 0.25, cy - s * 0.45)
    p.cubic_to(cx + s * 0.55, cy - s * 0.45, cx + s * 0.55, cy + s * 0.05, cx, cy + s * 0.45)
    return p.close()


def region_path(region, w: float, h: float) -> Path:
    if region in (None, "rect"):
        return rounded_rect(0, 0, w, h, 0)
    if region == "roundrect":
        return rounded_rect(0, 0, w, h, min(w, h) * 0.12)
    if region == "ellipse":
        return ellipse(w / 2, h / 2, w / 2, h / 2)
    if isinstance(region, dict):
        geom = CustomGeometry.from_json(region)
        sx, sy = w / geom.width, h / geom.height
        p = Path()
        for part in geom.parts:
            if part.fill != "none":
                p.extend(part.path.map_points(lambda x, y: (x * sx, y * sy)))
        return p
    raise ValueError("region must be rect, roundrect, ellipse or a geometry JSON object")


def pattern_fill(rng, kind="dots", w=1000.0, h=1000.0, spacing=90.0, size=0.42, angle=0.0, region="rect",
                 stagger=True):
    """Tile ``kind`` over the region; returns one layer whose parts never overlap."""
    reg = region_path(region, w, h)
    motifs: list[Path] = []
    s = spacing
    diag = math.hypot(w, h)
    if kind in ("dots", "hearts"):
        rows = int(math.ceil(diag / s)) + 2
        for j in range(-rows, rows):
            for i in range(-rows, rows):
                off = s / 2 if (stagger and j % 2) else 0.0
                x, y = w / 2 + i * s + off, h / 2 + j * s
                x, y = rotate((x, y), angle, (w / 2, h / 2))
                if -s < x < w + s and -s < y < h + s:
                    motifs.append(circle(x, y, s * size / 2) if kind == "dots" else heart(x, y, s * size * 1.1))
    elif kind == "stripes":
        band = s * size
        n = int(math.ceil(diag / s)) + 2
        for i in range(-n, n):
            x = w / 2 + i * s
            pts = [(x, h / 2 - diag), (x + band, h / 2 - diag), (x + band, h / 2 + diag), (x, h / 2 + diag)]
            motifs.append(polygon([rotate(p, angle, (w / 2, h / 2)) for p in pts]))
    elif kind == "checks":
        n = int(math.ceil(diag / s)) + 2
        for j in range(-n, n):
            for i in range(-n, n):
                if (i + j) % 2:
                    continue
                x, y = w / 2 + i * s, h / 2 + j * s
                pts = [(x, y), (x + s, y), (x + s, y + s), (x, y + s)]
                motifs.append(polygon([rotate(p, angle, (w / 2, h / 2)) for p in pts]))
    else:
        raise ValueError("kind must be dots, stripes, checks or hearts")
    out = Path()
    kept = clipped = 0
    touch = kind == "checks"  # checks share corners: merge them so no two sub-paths overlap
    if touch:
        merged = boolean(motifs, [reg], "intersect", tol=0.05)
        out.extend(merged)
        clipped = len(motifs)
    else:
        for m in motifs:
            a = area(m, tol=0.2)
            ai = area(boolean([m], [reg], "intersect", tol=0.2), tol=0.2)
            if ai <= 1e-9:
                continue
            if abs(ai - a) <= 1e-6 * a + 1e-6:
                out.extend(m)
                kept += 1
            else:
                out.extend(boolean([m], [reg], "intersect", tol=0.05))
                clipped += 1
    return [Layer("primary", CustomGeometry(w, h, [GeomPart(out)]))], {"kept_whole": kept, "clipped": clipped}
