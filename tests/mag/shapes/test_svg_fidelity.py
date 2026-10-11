"""Gate C: SVG -> custGeom fidelity on a 50-shape corpus (IoU >= 0.99, resvg vs the emitted XML)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from mxstudio.shapes.custgeom import CustomGeometry, GeomPart, Path as GPath, validate_custgeom_xml
from mxstudio.shapes.raster import iou, rasterize_geometry, render_svg_mask
from mxstudio.shapes.svg_convert import svg_to_shapes

CORPUS = sorted((Path(__file__).resolve().parent / "corpus").glob("*.svg"))
RES = 1024


def xml_round_trip_mask(svg: str) -> tuple[np.ndarray, set[str], list[str]]:
    """Rasterise what PowerPoint receives: each shape's emitted a:custGeom XML, placed at its bbox."""
    res = svg_to_shapes(svg)
    h = round(RES * res.height / res.width)
    mask = np.zeros((h, RES), np.uint8)
    ops: set[str] = set()
    for shape in res.shapes:
        local, (x, y, w, hh) = shape.geometry.cropped()
        xml = local.to_xml()
        assert validate_custgeom_xml(xml) == []
        parsed = CustomGeometry.from_xml(xml)  # path space -> rescale into design units
        s = w / parsed.width
        geom = CustomGeometry(w, hh, [GeomPart(p.path.scaled(s), p.fill, p.stroke) for p in parsed.parts])
        rasterize_geometry(geom, RES, h, frame=(res.width, res.height), offset=(x, y), into=mask)
        ops |= {c[0] for p in local.parts for c in p.path.commands}
    return mask, ops, res.findings


def test_corpus_has_fifty_shapes_covering_every_construct():
    assert len(CORPUS) == 50
    text = " ".join(p.read_text(encoding="utf-8") for p in CORPUS)
    for construct in ("<rect", "<circle", "<ellipse", "<polygon", "<polyline", " A", " C", " Q", " S", " T", " H",
                      " V", "rotate(", "scale(", "skewX(", "matrix(", "evenodd", "viewBox=\"-1"):
        assert construct in text, construct


@pytest.mark.parametrize("svg_path", CORPUS, ids=[p.stem for p in CORPUS])
def test_svg_to_custgeom_iou(svg_path):
    svg = svg_path.read_text(encoding="utf-8")
    got, ops, findings = xml_round_trip_mask(svg)
    ref = render_svg_mask(svg, got.shape[1], got.shape[0])
    score = iou(got, ref)
    assert score >= 0.99, f"{svg_path.name}: IoU {score:.4f} ops={sorted(ops)} findings={findings}"


def test_drawingml_verbs_are_used_natively():
    ops = set()
    for p in CORPUS:
        ops |= xml_round_trip_mask(p.read_text(encoding="utf-8"))[1]
    assert {"M", "L", "C", "Q", "A", "Z"} <= ops


def test_negative_control_iou_gate_can_fail():
    """Without the non-zero fix the self-intersecting star loses its centre: the gate must catch it."""
    svg = (Path(__file__).resolve().parent / "corpus" / "32_nonzero_star_self_intersect.svg").read_text(encoding="utf-8")
    raw = GPath().move_to(100, 10).line_to(155, 190).line_to(10, 75).line_to(190, 75).line_to(45, 190).close()
    naive = CustomGeometry(200, 200, [GeomPart(raw)])
    got = rasterize_geometry(naive, 512, 512)
    assert iou(got, render_svg_mask(svg, 512, 512)) < 0.9
    # and a wrong arc sweep (parametric/visual confusion or sign flip) is also caught
    moon = (Path(__file__).resolve().parent / "corpus" / "40_moon.svg").read_text(encoding="utf-8")
    res = svg_to_shapes(moon)
    flipped = CustomGeometry(res.width, res.height)
    for s in res.shapes:
        for p in s.geometry.parts:
            flipped.parts.append(GeomPart(GPath([c if c[0] != "A" else ("A", c[1], c[2], c[3], -c[4])
                                                 for c in p.path.commands])))
    assert iou(rasterize_geometry(flipped, 512), render_svg_mask(moon, 512, 512)) < 0.99
