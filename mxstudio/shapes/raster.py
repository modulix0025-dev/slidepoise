"""Flattening and rasterising for *measurement* (IoU, similarity, sanity checks).

Rule: these rasters are facts for tests and search - never a visual verdict and never
what goes to print (print output stays vector ``a:custGeom``).

Fill semantics: inside one ``a:path`` sub-paths combine even-odd (what Office does for a
single freeform path); separate ``a:path`` parts are painted independently (union).
"""
from __future__ import annotations

import math

import cv2
import numpy as np

from .custgeom import CustomGeometry, Path, arc_geometry



def _n_cubic(p0, p1, p2, p3, tol: float) -> int:
    dd = max(math.hypot(p0[0] - 2 * p1[0] + p2[0], p0[1] - 2 * p1[1] + p2[1]),
             math.hypot(p1[0] - 2 * p2[0] + p3[0], p1[1] - 2 * p2[1] + p3[1]))
    return max(2, min(512, int(math.ceil(math.sqrt(6 * dd / (8 * max(tol, 1e-6)))))))


def flatten_path(path: Path, tol: float = 0.25) -> list[list[tuple[float, float]]]:
    """Polylines (one per sub-path) approximating ``path`` within ``tol`` units."""
    polys: list[list[tuple[float, float]]] = []
    cur_poly: list[tuple[float, float]] = []
    for cmd, cur, end in path.walk():
        op = cmd[0]
        if op == "M":
            if len(cur_poly) > 1:
                polys.append(cur_poly)
            cur_poly = [end]
            continue
        if not cur_poly:
            cur_poly = [cur]
        if op == "L":
            cur_poly.append(end)
        elif op == "Z":
            if len(cur_poly) > 1:
                polys.append(cur_poly)
            cur_poly = [end]
        elif op == "C":
            p0, p1, p2, p3 = cur, (cmd[1], cmd[2]), (cmd[3], cmd[4]), (cmd[5], cmd[6])
            n = _n_cubic(p0, p1, p2, p3, tol)
            for i in range(1, n + 1):
                t = i / n
                mt = 1 - t
                cur_poly.append((mt ** 3 * p0[0] + 3 * mt * mt * t * p1[0] + 3 * mt * t * t * p2[0] + t ** 3 * p3[0],
                                 mt ** 3 * p0[1] + 3 * mt * mt * t * p1[1] + 3 * mt * t * t * p2[1] + t ** 3 * p3[1]))
        elif op == "Q":
            p0, p1, p2 = cur, (cmd[1], cmd[2]), (cmd[3], cmd[4])
            dd = math.hypot(p0[0] - 2 * p1[0] + p2[0], p0[1] - 2 * p1[1] + p2[1])
            n = max(2, min(512, int(math.ceil(math.sqrt(2 * dd / (8 * max(tol, 1e-6)))))))
            for i in range(1, n + 1):
                t = i / n
                mt = 1 - t
                cur_poly.append((mt * mt * p0[0] + 2 * mt * t * p1[0] + t * t * p2[0],
                                 mt * mt * p0[1] + 2 * mt * t * p1[1] + t * t * p2[1]))
        elif op == "A":
            w_r, h_r = cmd[1], cmd[2]
            (cx, cy), t0, t1, _ = arc_geometry(cur, w_r, h_r, cmd[3], cmd[4])
            r = max(w_r, h_r, 1e-9)
            step = 2 * math.acos(max(-1.0, min(1.0, 1 - tol / r))) if tol < r else math.pi / 4
            n = max(2, min(2048, int(math.ceil(abs(t1 - t0) / max(step, 1e-4)))))
            for i in range(1, n + 1):
                t = t0 + (t1 - t0) * i / n
                cur_poly.append((cx + w_r * math.cos(t), cy + h_r * math.sin(t)))
    if len(cur_poly) > 1:
        polys.append(cur_poly)
    return polys


def scanline_evenodd(polys, width_px: int, height_px: int) -> np.ndarray:
    """Exact even-odd coverage at pixel centres (no anti-aliasing, no edge bias).

    Every polygon is implicitly closed; crossings of all polygons count together, so
    overlapping sub-paths XOR exactly like one DrawingML ``a:path``.
    """
    mask = np.zeros((height_px, width_px), dtype=np.uint8)
    segs = []
    for poly in polys:
        if len(poly) < 3:
            continue
        arr = np.asarray(poly, dtype=np.float64)
        segs.append(np.hstack([arr, np.roll(arr, -1, axis=0)]))
    if not segs:
        return mask
    e = np.vstack(segs)
    x0, y0, x1, y1 = e[:, 0], e[:, 1], e[:, 2], e[:, 3]
    keep = y0 != y1
    x0, y0, x1, y1 = x0[keep], y0[keep], x1[keep], y1[keep]
    ylo, yhi = np.minimum(y0, y1), np.maximum(y0, y1)
    r0 = np.clip(np.ceil(ylo - 0.5), 0, height_px).astype(np.int64)
    r1 = np.clip(np.ceil(yhi - 0.5), 0, height_px).astype(np.int64)  # exclusive
    counts = np.maximum(r1 - r0, 0)
    total = int(counts.sum())
    if total == 0:
        return mask
    idx = np.repeat(np.arange(len(counts)), counts)
    starts = np.repeat(np.cumsum(counts) - counts, counts)
    rows = r0[idx] + (np.arange(total) - starts)
    yc = rows + 0.5
    xs = x0[idx] + (yc - y0[idx]) * (x1[idx] - x0[idx]) / (y1[idx] - y0[idx])
    order = np.lexsort((xs, rows))
    rows, xs = rows[order], xs[order]
    # pair consecutive crossings inside each row
    first = np.r_[True, rows[1:] != rows[:-1]]
    rank = np.arange(len(rows)) - np.maximum.accumulate(np.where(first, np.arange(len(rows)), 0))
    a_idx = np.nonzero(rank % 2 == 0)[0]
    a_idx = a_idx[a_idx + 1 < len(rows)]
    a_idx = a_idx[rows[a_idx + 1] == rows[a_idx]]
    ra = rows[a_idx]
    ca = np.clip(np.ceil(xs[a_idx] - 0.5), 0, width_px).astype(np.int64)
    cb = np.clip(np.ceil(xs[a_idx + 1] - 0.5), 0, width_px).astype(np.int64)
    ok = cb > ca
    diff = np.zeros((height_px, width_px + 1), dtype=np.int32)
    np.add.at(diff, (ra[ok], ca[ok]), 1)
    np.add.at(diff, (ra[ok], cb[ok]), -1)
    mask[:] = (np.cumsum(diff, axis=1)[:, :width_px] > 0)
    return mask


def _fill_xor(mask: np.ndarray, polys, sx: float, sy: float, ox: float = 0.0, oy: float = 0.0) -> None:
    scaled = [[((x + ox) * sx, (y + oy) * sy) for x, y in poly] for poly in polys]
    mask |= scanline_evenodd(scaled, mask.shape[1], mask.shape[0])


def rasterize_geometry(geom: CustomGeometry, width_px: int, height_px: int | None = None,
                       frame: tuple[float, float] | None = None, offset: tuple[float, float] = (0.0, 0.0),
                       into: np.ndarray | None = None) -> np.ndarray:
    """Binary fill mask (uint8 0/1) of the filled parts of ``geom``.

    ``frame`` is the design-space size mapped onto the raster (defaults to the geometry's
    own frame); ``offset`` places the geometry inside that frame.
    """
    fw, fh = frame or (geom.width, geom.height)
    if height_px is None:
        height_px = max(1, round(width_px * fh / fw))
    mask = into if into is not None else np.zeros((height_px, width_px), dtype=np.uint8)
    sx, sy = width_px / fw, height_px / fh
    tol = 0.1 / max(sx, sy)
    for part in geom.parts:
        if part.fill == "none":
            continue
        _fill_xor(mask, flatten_path(part.path, tol), sx, sy, offset[0], offset[1])
    return mask


def render_svg_mask(svg: str, width_px: int, height_px: int) -> np.ndarray:
    """Coverage mask (uint8 0/1, alpha >= 50%) of an SVG rendered by resvg."""
    import resvg_py

    png = resvg_py.svg_to_bytes(svg_string=svg, width=int(width_px), height=int(height_px))
    img = cv2.imdecode(np.frombuffer(bytes(png), np.uint8), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError("resvg produced no image")
    if img.ndim == 2:
        alpha = img
    elif img.shape[2] == 4:
        alpha = img[:, :, 3]
    else:
        alpha = 255 - cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if alpha.shape != (height_px, width_px):
        alpha = cv2.resize(alpha, (width_px, height_px), interpolation=cv2.INTER_AREA)
    return (alpha >= 128).astype(np.uint8)


def render_svg_png(svg: str, width_px: int, height_px: int | None = None, background: str | None = None) -> bytes:
    import resvg_py

    kwargs = {"svg_string": svg, "width": int(width_px)}
    if height_px:
        kwargs["height"] = int(height_px)
    if background:
        kwargs["background"] = background
    return bytes(resvg_py.svg_to_bytes(**kwargs))


def iou(a: np.ndarray, b: np.ndarray) -> float:
    a = a.astype(bool)
    b = b.astype(bool)
    union = np.logical_or(a, b).sum()
    if union == 0:
        return 1.0
    return float(np.logical_and(a, b).sum() / union)


def mask_from_png(png: bytes, threshold: int = 128) -> np.ndarray:
    """Foreground mask of a PNG: alpha when present, else dark pixels on a light ground."""
    img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError("not a decodable image")
    if img.ndim == 3 and img.shape[2] == 4 and int(img[:, :, 3].min()) < 250:
        return (img[:, :, 3] >= threshold).astype(np.uint8)
    gray = img if img.ndim == 2 else cv2.cvtColor(img[:, :, :3], cv2.COLOR_BGR2GRAY)
    return (gray < threshold).astype(np.uint8)
