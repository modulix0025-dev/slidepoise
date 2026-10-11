"""Gate B: procedural generators are deterministic (same seed => same XML) and honour their facts."""
from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

import numpy as np
import pytest

from mxstudio.shapes.boolean import area
from mxstudio.shapes.custgeom import validate_custgeom_xml
from mxstudio.shapes.generators import REGISTRY, generate, list_generators, validate_params
from mxstudio.shapes.generators.bubbles import anchor_from_semantic_map
from mxstudio.shapes.raster import rasterize_geometry

ROOT = Path(__file__).resolve().parents[3]
STOCHASTIC = {"cloud_frame", "torn_paper", "blob", "rough_outline", "thought_bubble", "confetti_scatter"}
VARIANTS = {"page_border": [{"theme": t} for t in ("sea_waves", "vines", "stars", "candy")],
            "pattern_fill": [{"kind": k} for k in ("dots", "stripes", "checks", "hearts")],
            "speech_bubble": [{}, {"kind": "roundrect", "anchor": [100, 1800]}, {"kind": "rect", "anchor": [1400, 300]}],
            "rough_outline": [{}, {"base": "ellipse"}, {"base": "polygon", "sides": 7}],
            "drop_cap_ornament": [{}, {"shape": "circle"}]}


def cases():
    for name in REGISTRY:
        for params in VARIANTS.get(name, [{}]):
            yield name, params


def _params(name, params):
    if name == "sticker_outline":
        return {"source": generate("blob", 5).layers[0].geometry.to_json(), **params}
    return params


@pytest.mark.parametrize("name,params", list(cases()), ids=lambda v: v if isinstance(v, str) else json.dumps(v))
def test_same_seed_same_xml_and_valid(name, params):
    p = _params(name, params)
    a = generate(name, 42, p)
    b = generate(name, 42, p)
    assert a.to_xml() == b.to_xml()
    for layer in a.layers:
        assert validate_custgeom_xml(layer.geometry.to_xml()) == [], (name, layer.role)
    mask = rasterize_geometry(a.merged(), 256)
    assert mask.sum() > 0 or all(pt.fill == "none" for pt in a.merged().parts)


@pytest.mark.parametrize("name", sorted(STOCHASTIC))
def test_different_seed_changes_stochastic_shapes(name):
    assert generate(name, 1).to_xml() != generate(name, 2).to_xml()


def test_determinism_across_processes_and_hash_seeds():
    """A fresh interpreter with a different PYTHONHASHSEED reproduces the exact bytes."""
    from mxstudio.proc import run_hidden

    code = ("import hashlib,sys;sys.path.insert(0,'.');from mxstudio.shapes.generators import REGISTRY,generate;"
            "print(hashlib.sha256(''.join(generate(n,7).to_xml() for n in sorted(REGISTRY) "
            "if n!='sticker_outline').encode()).hexdigest())")
    local = __import__("hashlib").sha256("".join(generate(n, 7).to_xml() for n in sorted(REGISTRY)
                                                 if n != "sticker_outline").encode()).hexdigest()
    for seed in ("0", "12345"):
        out = run_hidden([sys.executable, "-c", code], env={"PYTHONHASHSEED": seed}, cwd=ROOT, timeout=120)
        assert out.returncode == 0, out.stderr.decode("utf-8", "replace")
        assert out.stdout.decode().strip() == local


def test_params_are_validated_and_clamped():
    with pytest.raises(ValueError):
        validate_params("blob", {"no_such_param": 1})
    with pytest.raises(KeyError):
        validate_params("no_such_generator", {})
    with pytest.raises(ValueError):
        validate_params("page_border", {"theme": "lava"})
    v = validate_params("cloud_frame", {"bumps": 10_000, "w": -5})
    assert v["bumps"] == 60 and v["w"] == 10.0
    specs = list_generators()
    assert len(specs) == len(REGISTRY) >= 18
    assert all(s["label_ar"] and s["label_en"] for s in specs)


def test_speech_bubble_tail_aims_at_semantic_anchor():
    smap = {"characters": [{"id": "rabbit", "face": [1000, 1300, 200, 200]}, {"id": "fox", "mouth": [150, 1700]}]}
    for cid in ("rabbit", "fox"):
        anchor = anchor_from_semantic_map(smap, cid)
        for kind in ("ellipse", "roundrect"):
            g = generate("speech_bubble", 1, {"anchor": list(anchor), "kind": kind, "gap": 50})
            tip = g.meta["tip"]
            body = (200 + 350, 200 + 190)
            to_anchor = (anchor[0] - body[0], anchor[1] - body[1])
            to_tip = (tip[0] - body[0], tip[1] - body[1])
            cos = (to_anchor[0] * to_tip[0] + to_anchor[1] * to_tip[1]) / (math.hypot(*to_anchor) * math.hypot(*to_tip))
            assert cos > 0.9, (cid, kind, cos)
            assert math.hypot(anchor[0] - tip[0], anchor[1] - tip[1]) <= 50.5 + 1e-6
    assert anchor_from_semantic_map(smap, "rabbit") == (1100.0, 1400.0)
    with pytest.raises(KeyError):
        anchor_from_semantic_map(smap, "bear")
    # negative control: moving the speaker to the other side flips the tail
    left = generate("speech_bubble", 1, {"anchor": [0, 300]}).meta["tip"]
    right = generate("speech_bubble", 1, {"anchor": [1480, 300]}).meta["tip"]
    assert left[0] < 200 < 900 < right[0]


def violations(pieces, keepouts, margin):
    return [p for p in pieces for x, y, w, h in keepouts
            if x - margin <= p["x"] <= x + w + margin and y - margin <= p["y"] <= y + h + margin]


def test_confetti_avoids_text_and_faces_with_poisson_spacing():
    smap = {"text_boxes": [[100, 100, 1280, 400]], "characters": [{"id": "kid", "face": [500, 900, 400, 400]}]}
    g = generate("confetti_scatter", 3, {"semantic_map": smap, "size": 30, "radius": 90, "margin": 10})
    pieces = g.meta["pieces"]
    assert len(pieces) > 40
    keep = [[100, 100, 1280, 400], [500, 900, 400, 400]]
    assert violations(pieces, keep, 10 + 30 * 0.7 - 1e-6) == []
    pts = np.array([[p["x"], p["y"]] for p in pieces])
    d = np.sqrt(((pts[:, None, :] - pts[None, :, :]) ** 2).sum(-1)) + np.eye(len(pts)) * 1e9
    assert d.min() >= g.meta["min_distance"] - 1e-6
    # negative control: the checker flags a planted piece inside the face box
    assert violations(pieces + [{"x": 700, "y": 1100}], keep, 0)
    for layer in g.layers:  # pieces never overlap, so even-odd == non-zero area
        path = layer.geometry.parts[0].path
        assert area(path, tol=0.5, fill_rule="evenodd") == pytest.approx(area(path, tol=0.5, fill_rule="nonzero"),
                                                                         rel=1e-3)


@pytest.mark.parametrize("kind", ["dots", "stripes", "checks", "hearts"])
def test_pattern_fill_stays_inside_region_and_never_self_overlaps(kind):
    g = generate("pattern_fill", 0, {"kind": kind, "region": "ellipse", "angle": 20})
    path = g.layers[0].geometry.parts[0].path
    a_eo, a_nz = area(path, tol=0.5, fill_rule="evenodd"), area(path, tol=0.5, fill_rule="nonzero")
    assert a_eo == pytest.approx(a_nz, rel=2e-3)
    x0, y0, x1, y1 = path.bbox()
    assert x0 >= -1 and y0 >= -1 and x1 <= 1001 and y1 <= 1001
    if kind == "dots":
        assert g.meta["kept_whole"] > 20  # whole motifs keep their curves


def test_sticker_outline_contains_art_with_offset():
    art = generate("blob", 9).layers[0].geometry
    g = generate("sticker_outline", 0, {"source": art.to_json(), "offset_by": 40, "include_art": True})
    cut, placed = g.layers[0].geometry, g.layers[1].geometry
    m_cut = rasterize_geometry(cut, 400)
    m_art = rasterize_geometry(placed, 400)
    assert (m_art & ~m_cut.astype(bool)).sum() == 0  # art fully inside the cut line
    grow = (m_cut.sum() - m_art.sum()) / m_art.sum()
    assert grow > 0.1
    assert len(cut.parts[0].path.subpaths()) == 1  # one piece, no holes


def test_layered_outputs_and_text_boxes():
    assert len(generate("rainbow", 0, {"bands": 7}).layers) == 7
    assert [l.role for l in generate("rosette_badge", 0).layers] == ["secondary", "primary", "accent"]
    banner = generate("ribbon_banner", 0, {"arch": 0.2})
    assert [p.fill for p in banner.layers[0].geometry.parts] == ["darkenLess", "darken", "norm"]
    dc = generate("drop_cap_ornament", 0)
    x, y, w, h = dc.meta["text_box"]
    assert 0 < x < x + w < dc.width and 0 < y < y + h < dc.height
    mandala = generate("mandala_frame", 0, {"symmetry": 8})
    m = rasterize_geometry(mandala.merged(), 200)
    assert m[100, 100] == 0 and m.sum() > 0  # the window stays open
    assert os.environ.get("PYTHONHASHSEED", "") is not None
