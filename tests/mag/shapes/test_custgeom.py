"""Path model <-> a:custGeom <-> SVG: round trips, arc semantics, structural validation."""
from __future__ import annotations

import math
import re

import pytest

from mxstudio.shapes.custgeom import (CustomGeometry, GeomPart, Path, arc_geometry, path_to_svg_d,
                                      validate_custgeom_xml)
from mxstudio.shapes.raster import iou, rasterize_geometry, render_svg_mask


def sample() -> CustomGeometry:
    p = Path().move_to(100, 100).line_to(400, 100).cubic_to(500, 100, 500, 300, 400, 300)
    p.quad_to(250, 420, 100, 300).arc_to(60, 100, 90, 90).close()
    hole = Path().move_to(200, 180).line_to(300, 180).line_to(300, 240).line_to(200, 240).close()
    outline = Path().move_to(50, 50).line_to(550, 50)
    return CustomGeometry(600, 450, [GeomPart(p.extend(hole)), GeomPart(outline, "none", True)])


def test_xml_round_trip_is_byte_stable():
    g = sample()
    xml = g.to_xml()
    assert validate_custgeom_xml(xml) == []
    again = CustomGeometry.from_xml(xml).to_xml()
    assert again == xml
    assert '<a:path w="100000" h="75000">' in xml and 'fill="none"' in xml
    assert "<a:arcTo" in xml and "<a:quadBezTo>" in xml and "<a:cubicBezTo>" in xml


def test_json_round_trip_and_bad_input():
    g = sample()
    assert CustomGeometry.from_json(g.to_json()).to_xml() == g.to_xml()
    with pytest.raises(ValueError):
        Path.from_json([["L", 1, 2]])
    with pytest.raises(ValueError):
        Path.from_json([["M", 1]])
    with pytest.raises(ValueError):
        Path.from_json([["M", float("nan"), 0]])
    with pytest.raises(ValueError):
        Path.from_json([["X", 1, 2]])


def test_arc_to_uses_visual_angles():
    # an arcTo on an ellipse starting at the visual 45-degree point lands on the ray at 135 degrees
    w_r, h_r = 200.0, 100.0
    t = math.atan2(w_r * math.sin(math.radians(45)), h_r * math.cos(math.radians(45)))
    start = (w_r * math.cos(t), h_r * math.sin(t))
    (cx, cy), _, _, end = arc_geometry(start, w_r, h_r, 45, 90)
    assert abs(cx) < 1e-9 and abs(cy) < 1e-9
    assert math.isclose(math.degrees(math.atan2(end[1], end[0])), 135.0, abs_tol=1e-9)
    assert math.isclose((end[0] / w_r) ** 2 + (end[1] / h_r) ** 2, 1.0, abs_tol=1e-12)


def test_svg_export_matches_raster_of_model():
    g = sample()
    svg = g.to_svg()
    a = rasterize_geometry(g, 600, 450)
    b = render_svg_mask(svg, 600, 450)
    assert iou(a, b) > 0.995
    full = Path().move_to(300, 200).arc_to(100, 100, 0, 360).close()
    assert path_to_svg_d(full).count("A") == 2  # a 360-degree sweep is split


def test_validator_negative_controls():
    ok = sample().to_xml()
    assert validate_custgeom_xml(ok.replace("<a:avLst/><a:gdLst/>", "<a:gdLst/><a:avLst/>")) == ["custGeom_child_order"]
    bad_start = re.sub(r"<a:moveTo>(.*?)</a:moveTo>", r"<a:lnTo>\1</a:lnTo>", ok, count=1)
    assert "path_must_start_with_moveTo" in validate_custgeom_xml(bad_start)
    assert any(f.startswith("unknown_path_element")
               for f in validate_custgeom_xml(ok.replace("<a:close/>", "<a:spline/>", 1)))
    assert "lnTo_coordinate_not_long" in validate_custgeom_xml(ok.replace('<a:lnTo><a:pt x="', '<a:lnTo><a:pt x="1.5', 1))
    assert validate_custgeom_xml("<notxml")[0].startswith("xml_syntax")
    assert validate_custgeom_xml(ok.replace('w="100000"', 'w="0"', 1)) == ["path_w_not_positive_long"]


def test_mlcz_and_scene_freeform_adapter():
    from mxstudio.shapes.pptx_out import scene_freeform

    g = sample()
    ops = {c[0] for p in g.parts for c in p.path.only_mlcz().commands}
    assert ops <= {"M", "L", "C", "Z"}
    obj = scene_freeform(g, [10, 20, 300, 225], "shape-1")
    assert obj["kind"] == "freeform" and {c["op"] for c in obj["path_commands_px"]} <= {"M", "L", "C", "Z"}
    first = obj["path_commands_px"][0]["point"]
    assert first == [10 + 100 * 0.5, 20 + 100 * 0.5]
    # mlcz conversion preserves the filled area
    mlcz = CustomGeometry(600, 450, [GeomPart(p.path.only_mlcz(), p.fill, p.stroke) for p in g.parts])
    assert iou(rasterize_geometry(g, 600), rasterize_geometry(mlcz, 600)) > 0.999
