"""Style-consistency facts across a book (stroke width, corner radius, palette, drawing style).

Rule: this module *measures* and returns named findings with the numbers behind them. It never
scores or approves a book - the operator / host Agent decides whether a finding matters.

Inputs are either shape-usage records (``ShapeUse``) or a .pptx, from which every ``p:sp`` gives
its line width (``a:ln/@w``), solid fill / line colours (``a:srgbClr``), and the corner adjust of
rounded presets (``roundRect`` family ``adj``/``adj1``).
"""
from __future__ import annotations

import statistics
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
ROUNDED = {"roundRect", "round1Rect", "round2SameRect", "round2DiagRect", "snipRoundRect", "flowChartAlternateProcess",
           "wedgeRoundRectCallout"}


@dataclass
class ShapeUse:
    page: str
    name: str
    stroke_width_pt: float | None = None
    corner_radius: float | None = None  # adj ratio 0..50000 (or 0..1 for custom shapes)
    colours: list[str] = field(default_factory=list)
    style: str | None = None


@dataclass(frozen=True)
class Thresholds:
    stroke_rel_tolerance: float = 0.35  # +-35% around the book median
    corner_abs_tolerance: float = 6000.0  # adj units
    palette_delta_e: float = 12.0  # CIEDE2000 to the nearest palette colour
    neutral_chroma: float = 6.0  # near-greys never count as off-palette


def _delta_e(a: str, b: str) -> float:
    from coloraide import Color

    return float(Color(a).delta_e(Color(b), method="2000"))


def _chroma(c: str) -> float:
    from coloraide import Color

    return float(Color(c).convert("lch")["chroma"])


def uses_from_pptx(path: str | Path) -> list[ShapeUse]:
    out: list[ShapeUse] = []
    with zipfile.ZipFile(path) as z:
        slides = sorted((n for n in z.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")),
                        key=lambda n: int("".join(ch for ch in n if ch.isdigit()) or 0))
        for name in slides:
            root = etree.fromstring(z.read(name), etree.XMLParser(resolve_entities=False, no_network=True))
            page = Path(name).stem
            for sp in root.iter(P + "sp"):
                sp_pr = sp.find(P + "spPr")
                if sp_pr is None:
                    continue
                if sp.find(f"{P}nvSpPr/{P}cNvSpPr[@txBox='1']") is not None:
                    continue
                cnv = sp.find(f"{P}nvSpPr/{P}cNvPr")
                use = ShapeUse(page=page, name=cnv.get("name", "") if cnv is not None else "")
                ln = sp_pr.find(A + "ln")
                if ln is not None and ln.get("w") and ln.find(A + "noFill") is None:
                    use.stroke_width_pt = int(ln.get("w")) / 12700.0
                for clr in sp_pr.iter(A + "srgbClr"):
                    use.colours.append("#" + clr.get("val", "000000").upper())
                prst = sp_pr.find(A + "prstGeom")
                if prst is not None and prst.get("prst") in ROUNDED:
                    gd = prst.find(f"{A}avLst/{A}gd")
                    use.corner_radius = float(gd.get("fmla").split()[-1]) if gd is not None else 16667.0
                out.append(use)
    return out


def check(uses: list[ShapeUse], *, palette: list[str] | None = None, thresholds: Thresholds = Thresholds()) -> dict:
    """Facts + named findings (``stroke_width_outlier``, ``corner_radius_outlier``,
    ``off_palette_colour``, ``mixed_styles``)."""
    findings: list[dict] = []
    strokes = [u.stroke_width_pt for u in uses if u.stroke_width_pt]
    corners = [u.corner_radius for u in uses if u.corner_radius is not None]
    facts: dict = {"shapes": len(uses), "stroke_widths_pt": sorted({round(s, 2) for s in strokes}),
                   "corner_radii": sorted({round(c, 1) for c in corners})}
    if strokes:
        med = statistics.median(strokes)
        facts["stroke_median_pt"] = round(med, 3)
        for u in uses:
            if u.stroke_width_pt and abs(u.stroke_width_pt - med) > thresholds.stroke_rel_tolerance * med:
                findings.append({"code": "stroke_width_outlier", "page": u.page, "shape": u.name,
                                 "value_pt": round(u.stroke_width_pt, 3), "median_pt": round(med, 3)})
    if corners:
        medc = statistics.median(corners)
        facts["corner_median"] = medc
        for u in uses:
            if u.corner_radius is not None and abs(u.corner_radius - medc) > thresholds.corner_abs_tolerance:
                findings.append({"code": "corner_radius_outlier", "page": u.page, "shape": u.name,
                                 "value": u.corner_radius, "median": medc})
    if palette:
        seen: dict[str, float] = {}
        for u in uses:
            for c in u.colours:
                if c in seen:
                    d = seen[c]
                else:
                    d = 0.0 if _chroma(c) < thresholds.neutral_chroma else min(_delta_e(c, p) for p in palette)
                    seen[c] = d
                if d > thresholds.palette_delta_e:
                    findings.append({"code": "off_palette_colour", "page": u.page, "shape": u.name, "colour": c,
                                     "delta_e_2000": round(d, 2)})
        facts["colours"] = sorted(seen)
    styles = sorted({u.style for u in uses if u.style})
    facts["styles"] = styles
    if len(styles) > 1:
        counts = {s: sum(1 for u in uses if u.style == s) for s in styles}
        findings.append({"code": "mixed_styles", "counts": counts})
    return {"facts": facts, "findings": findings}
