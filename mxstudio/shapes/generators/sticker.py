"""Die-cut sticker outlines: an outward offset of the artwork silhouette (pyclipper).

Rule: the cut line is the *outer* boundary of ``silhouette (+) offset`` - holes are dropped,
so the sticker is one piece - then smoothed with Catmull-Rom so the cutter gets curves.
Spot-colour naming for the cutter (e.g. a ``CutContour`` swatch) is a print-shop step that is
pending on-device proof; this module only produces the geometry.
"""
from __future__ import annotations

import math

import cv2
import numpy as np

from ..boolean import SCALE, offset, to_int_polys
from ..custgeom import CustomGeometry, GeomPart, Path
from ._util import Layer, catmull_rom_closed


def _resample(poly: list[tuple[float, float]], step: float) -> list[tuple[float, float]]:
    out = []
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        d = math.hypot(b[0] - a[0], b[1] - a[1])
        k = max(1, int(d // step))
        for j in range(k):
            t = j / k
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return out


def _smooth(path: Path, step: float) -> Path:
    out = Path()
    for poly in to_int_polys(path, 0.05):
        pts = [(x / SCALE, y / SCALE) for x, y in poly]
        pts = _resample(pts, step)
        if len(pts) >= 4:
            out.extend(catmull_rom_closed(pts[::max(1, len(pts) // 400)]))
    return out


def silhouette_from_mask(mask: np.ndarray, w: float, h: float) -> Path:
    """External contours of a binary mask, scaled into a ``w x h`` design frame."""
    m = (mask > 0).astype(np.uint8)
    contours, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    sx, sy = w / m.shape[1], h / m.shape[0]
    p = Path()
    for c in contours:
        if cv2.contourArea(c) < 4:
            continue
        pts = [((float(x) + 0.5) * sx, (float(y) + 0.5) * sy) for x, y in c.reshape(-1, 2)]
        p.move_to(*pts[0])
        for x, y in pts[1:]:
            p.line_to(x, y)
        p.close()
    return p


def sticker_outline(rng, source=None, mask=None, w=1000.0, h=1000.0, offset_by=40.0, smooth=True, include_art=False):
    """Cut line around ``source`` (geometry JSON) or ``mask`` (2-D array); frame grows by the offset."""
    if source is not None:
        geom = source if isinstance(source, CustomGeometry) else CustomGeometry.from_json(source)
        w, h = geom.width, geom.height
        art = [p.path for p in geom.parts if p.fill != "none"]
    elif mask is not None:
        art = [silhouette_from_mask(np.asarray(mask), w, h)]
    else:
        raise ValueError("sticker_outline needs source geometry or a mask")
    d = float(offset_by)
    cut = offset([a.translated(d, d) for a in art], d, tol=0.1, join="round", outer_only=True)
    if smooth:
        cut = _smooth(cut, step=max(d / 3, 2.0))
    W, H = w + 2 * d, h + 2 * d
    layers = [Layer("cut", CustomGeometry(W, H, [GeomPart(cut)]))]
    if include_art:
        layers.append(Layer("art", CustomGeometry(W, H, [GeomPart(a.translated(d, d)) for a in art])))
    return layers, {"offset": d, "frame_grew_by": d}
