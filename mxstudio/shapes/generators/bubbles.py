"""Speech and thought bubbles whose tail aims at a character.

Rule: the anchor is a *fact* taken from the page's semantic map (a character's mouth/face/head
point or bounding box), never guessed from pixels here. The tail tip stops ``gap`` short of the
anchor so it points at the speaker without covering the face. Output is in page coordinates.
"""
from __future__ import annotations

import math

from ..custgeom import CustomGeometry, GeomPart, Path, param_arc_to_cubics
from ._util import Layer, circle

ANCHOR_KEYS = ("mouth", "speech_anchor", "face", "head")


def anchor_from_semantic_map(semantic_map: dict, character_id: str | None = None) -> tuple[float, float]:
    """Pick the speaker anchor from a page semantic map.

    Accepted shape (Studio page map)::

        {"characters": [{"id": "hero", "mouth": [x, y]} | {"id": ..., "face": [x, y, w, h]} |
                        {"id": ..., "bbox": [x, y, w, h]}]}

    Points are used as-is; boxes give their centre (``face``) or upper-third centre (``head``/``bbox``).
    """
    chars = semantic_map.get("characters") or []
    if not chars:
        raise ValueError("semantic map has no characters")
    char = next((c for c in chars if character_id is None or c.get("id") == character_id), None)
    if char is None:
        raise KeyError(f"character {character_id!r} not on this page")
    for key in ANCHOR_KEYS + ("bbox",):
        v = char.get(key)
        if v is None:
            continue
        v = [float(x) for x in v]
        if len(v) == 2:
            return (v[0], v[1])
        if len(v) == 4:
            x, y, w, h = v
            return (x + w / 2, y + h / 2) if key in ("face", "mouth", "speech_anchor") else (x + w / 2, y + h / 3)
    raise ValueError(f"character {char.get('id')!r} has no usable anchor")


def _tip(base_c, anchor, gap, min_len):
    dx, dy = anchor[0] - base_c[0], anchor[1] - base_c[1]
    dist = math.hypot(dx, dy) or 1.0
    reach = max(min_len, dist - gap)
    return (base_c[0] + dx / dist * reach, base_c[1] + dy / dist * reach)


def _tail(path: Path, b1, tip, b2, curve: float) -> None:
    """b1 -> tip -> b2 with both edges bending to the same side (curved comic tail)."""
    mx, my = (b1[0] + b2[0]) / 2, (b1[1] + b2[1]) / 2
    ux, uy = tip[0] - mx, tip[1] - my
    length = math.hypot(ux, uy) or 1.0
    nx, ny = -uy / length, ux / length
    bend = curve * length
    c1 = ((b1[0] + tip[0]) / 2 + nx * bend, (b1[1] + tip[1]) / 2 + ny * bend)
    c2 = ((b2[0] + tip[0]) / 2 + nx * bend, (b2[1] + tip[1]) / 2 + ny * bend)
    path.quad_to(*c1, *tip)
    path.quad_to(*c2, *b2)


def speech_bubble(rng, page_w=1480.0, page_h=2100.0, body=(200.0, 200.0, 700.0, 380.0), anchor=(1100.0, 1100.0),
                  kind="ellipse", tail_width=0.22, gap=60.0, curve=0.12, corner=0.18):
    """Ellipse or rounded-rectangle bubble with one tail aimed at ``anchor`` (page units)."""
    x, y, bw, bh = [float(v) for v in body]
    cx, cy = x + bw / 2, y + bh / 2
    anchor = (float(anchor[0]), float(anchor[1]))
    hw = tail_width * min(bw, bh) / 2
    p = Path()
    if kind == "ellipse":
        rx, ry = bw / 2, bh / 2
        # parametric angle whose point faces the anchor
        tc = math.atan2((anchor[1] - cy) / ry, (anchor[0] - cx) / rx)
        circumference = math.pi * (3 * (rx + ry) - math.sqrt((3 * rx + ry) * (rx + 3 * ry)))
        delta = min(0.6, hw / circumference * 2 * math.pi)
        t_start, t_end = tc + delta, tc - delta + 2 * math.pi
        b2 = (cx + rx * math.cos(t_start), cy + ry * math.sin(t_start))
        b1 = (cx + rx * math.cos(t_end), cy + ry * math.sin(t_end))
        base_c = (cx + rx * math.cos(tc), cy + ry * math.sin(tc))
        p.move_to(*b2)
        p.commands.extend(param_arc_to_cubics(cx, cy, rx, ry, t_start, t_end))
        tip = _tip(base_c, anchor, gap, min(bw, bh) * 0.2)
        _tail(p, b1, tip, b2, curve)
        p.close()
    elif kind in ("roundrect", "rect"):
        r = corner * min(bw, bh) if kind == "roundrect" else 0.0
        ndx, ndy = (anchor[0] - cx) / (bw / 2), (anchor[1] - cy) / (bh / 2)
        if abs(ndx) > abs(ndy):
            side = 1 if ndx > 0 else 3
        else:
            side = 2 if ndy > 0 else 0
        # clockwise edges: (start, end) and the corner arc that follows each edge
        edges = [((x + r, y), (x + bw - r, y), 270), ((x + bw, y + r), (x + bw, y + bh - r), 0),
                 ((x + bw - r, y + bh), (x + r, y + bh), 90), ((x, y + bh - r), (x, y + r), 180)]
        (s0, s1, _) = edges[side]
        length = math.hypot(s1[0] - s0[0], s1[1] - s0[1])
        ux, uy = (s1[0] - s0[0]) / length, (s1[1] - s0[1]) / length
        proj = (anchor[0] - s0[0]) * ux + (anchor[1] - s0[1]) * uy
        hw = min(hw, length / 2 - 1e-6)
        proj = max(hw, min(length - hw, proj))
        b1 = (s0[0] + ux * (proj - hw), s0[1] + uy * (proj - hw))
        b2 = (s0[0] + ux * (proj + hw), s0[1] + uy * (proj + hw))
        base_c = (s0[0] + ux * proj, s0[1] + uy * proj)
        p.move_to(*b2).line_to(*s1)
        for k in range(1, 5):
            i = (side + k - 1) % 4
            if r:
                p.arc_to(r, r, edges[i][2], 90)
            if k < 4:
                p.line_to(*edges[(i + 1) % 4][1])
        p.line_to(*edges[side][0]).line_to(*b1)
        tip = _tip(base_c, anchor, gap, min(bw, bh) * 0.2)
        _tail(p, b1, tip, b2, curve)
        p.close()
    else:
        raise ValueError("kind must be ellipse, roundrect or rect")
    geom = CustomGeometry(float(page_w), float(page_h), [GeomPart(p)])
    return [Layer("primary", geom)], {"tip": [round(tip[0], 3), round(tip[1], 3)], "anchor": list(anchor),
                                      "text_box": [x + bw * 0.15, y + bh * 0.18, bw * 0.7, bh * 0.64]}


def thought_bubble(rng, page_w=1480.0, page_h=2100.0, body=(200.0, 200.0, 700.0, 420.0), anchor=(1100.0, 1100.0),
                   bumps=11, trail=3, gap=60.0):
    """Cloud body plus a trail of shrinking circles walking toward ``anchor``."""
    from .frames import cloud_frame

    x, y, bw, bh = [float(v) for v in body]
    layers, _ = cloud_frame(rng, w=bw, h=bh, bumps=bumps, variance=0.2, puff=0.3, hole=False)
    cloud = layers[0].geometry.parts[0].path.translated(x, y)
    cx, cy = x + bw / 2, y + bh / 2
    dx, dy = anchor[0] - cx, anchor[1] - cy
    dist = math.hypot(dx, dy) or 1.0
    ux, uy = dx / dist, dy / dist
    edge = 1.0 / math.sqrt((ux / (bw / 2)) ** 2 + (uy / (bh / 2)) ** 2)
    start, end = edge * 1.02, dist - gap
    p = Path().extend(cloud)
    tip = (cx + ux * end, cy + uy * end)
    n = max(1, int(trail))
    rmax = min(bw, bh) * 0.09
    for i in range(n):
        t = (i + 0.5) / n
        d = start + (end - start) * t
        r = rmax * (1 - 0.6 * t)
        if d - r <= edge + rmax * 0.3:
            continue
        p.extend(circle(cx + ux * d, cy + uy * d, r))
    geom = CustomGeometry(float(page_w), float(page_h), [GeomPart(p)])
    return [Layer("primary", geom)], {"tip": [round(tip[0], 3), round(tip[1], 3)], "anchor": list(anchor)}
