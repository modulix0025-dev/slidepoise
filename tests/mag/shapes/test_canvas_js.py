"""Gate C (front-end): the dependency-free canvas geometry (pen, freehand, snapping, symmetry)
produces paths the server accepts and turns into valid custGeom."""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from mxstudio.proc import run_hidden
from mxstudio.shapes.custgeom import validate_custgeom_xml
from mxstudio.shapes.service import ShapeService

UI = Path(__file__).resolve().parents[3] / "mxstudio" / "ui" / "canvas"

NODE_SCRIPT = r"""
const vm = require('vm'), fs = require('fs');
const sb = { self: {} };
vm.runInNewContext(fs.readFileSync(process.env.MX_GEOM_JS, 'utf8'), sb);
const G = sb.self.MXGeom;
const pts = []; for (let i = 0; i < 60; i++) pts.push([100 + i * 6, 300 + Math.sin(i / 7) * 60, 0.5]);
const outline = G.getStroke(pts, { size: 18, thinning: 0.5, smoothing: 0.5, streamline: 0.5 });
const freehand = G.outlineToCommands(outline);
const anchors = [{x: 100, y: 100, hin: null, hout: null}, G.smoothHandles({x: 300, y: 80, hin: null, hout: null}, [360, 80]),
                 {x: 300, y: 260, hin: null, hout: null}];
const pen = G.penToCommands(anchors, true);
const openPen = G.penToCommands(anchors, false);
const snaps = [G.snapPoint([103, 98], {grid: 10}), G.snapPoint([103, 98], {anchors: [[100, 100]], grid: 10}),
               G.snapPoint([150, 128], {angleFrom: [100, 100], angleStep: 15})];
const sym = G.symmetryCopies(pen, {mirror: true, radial: 4, cx: 500, cy: 350});
const mirror = G.mirrorCommands([["M", 10, 20], ["L", 30, 40], ["Z"]], 500);
process.stdout.write(JSON.stringify({outline: outline.length, freehand, pen, openPen, snaps, sym: sym.length,
  mirror, dash: G.dashArray("dash", 2), prst: G.PRST_DASH}));
"""


@pytest.fixture(scope="module")
def js():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required for the canvas geometry checks")
    out = run_hidden([node, "--input-type=commonjs", "-e", NODE_SCRIPT], env={"MX_GEOM_JS": str(UI / "geometry.js")},
                     timeout=60)
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")
    return json.loads(out.stdout.decode("utf-8"))


def test_freehand_outline_is_a_closed_smooth_path(js, tmp_path):
    cmds = js["freehand"]
    assert js["outline"] > 40 and cmds[0][0] == "M" and cmds[-1] == ["Z"]
    assert {c[0] for c in cmds} == {"M", "Q", "Z"}
    svc = ShapeService.at(tmp_path / "l.sqlite3")
    res = svc.canvas_commit({"paths": [{"commands": cmds, "fill": True}]})
    svc.library.close()
    assert validate_custgeom_xml(res["custgeom"]) == [] and "<a:quadBezTo>" in res["custgeom"]
    x, y, w, h = res["bbox"]
    assert 380 > w > 340 and 80 < h < 200  # stroke width ~18 around a 354-wide sine


def test_pen_snapping_and_symmetry(js):
    assert js["pen"][0] == ["M", 100, 100] and js["pen"][-1] == ["Z"]
    assert any(c[0] == "C" for c in js["pen"]) and js["openPen"][-1][0] != "Z"
    assert js["snaps"][0] == {"point": [100, 100], "kind": "grid"}
    assert js["snaps"][1]["kind"] == "anchor"
    angle = js["snaps"][2]
    assert angle["kind"] == "angle"
    dx, dy = angle["point"][0] - 100, angle["point"][1] - 100
    import math

    assert math.isclose(math.degrees(math.atan2(dy, dx)) % 15, 0, abs_tol=1e-3) or \
        math.isclose(math.degrees(math.atan2(dy, dx)) % 15, 15, abs_tol=1e-3)
    assert js["sym"] == 8  # mirror x2, radial x4
    assert js["mirror"] == [["M", 990, 20], ["L", 970, 40], ["Z"]]
    assert js["dash"] == "8 4" and js["prst"]["dot"] == "sysDot"


EXTERNAL = re.compile(r"""(?:src|href)\s*=\s*["'](?:https?:)?//|import\s+.*\s+from\s|require\(\s*['"][^'"./]""")


def test_canvas_ui_is_dependency_free():
    for name in ("index.html", "canvas.js", "geometry.js"):
        text = (UI / name).read_text(encoding="utf-8")
        assert not EXTERNAL.search(text), name
        assert "js_api" not in text
    html = (UI / "index.html").read_text(encoding="utf-8")
    assert 'src="/ui/canvas/geometry.js"' in html and 'src="/ui/canvas/canvas.js"' in html
    js_text = (UI / "canvas.js").read_text(encoding="utf-8")
    for endpoint in ("/api/shapes/boolean", "/api/shapes/canvas/commit", "/api/shapes/presets", "/api/session"):
        assert endpoint in js_text
    assert "X-MXS-CSRF" in js_text


def test_negative_control_dependency_check_flags_a_cdn():
    assert EXTERNAL.search('<script src="https://cdn.example/lib.js"></script>')
    assert EXTERNAL.search("import x from 'perfect-freehand'")
