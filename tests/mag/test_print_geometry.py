"""Trim, bleed, safe zone, ISO-216 scaling and mirrored folios."""
from __future__ import annotations

import math

import pytest

from slidepoise.print_geometry import PageSpec, folio_box_mm, iso216_scale, scale_box


def test_presets_and_canvas():
    a5 = PageSpec.preset("A5")
    assert a5.trim_mm == (148.0, 210.0) and a5.canvas_mm == (154.0, 216.0)
    assert a5.canvas_emu == (5_544_000, 7_776_000)
    assert a5.canvas_px == (1819, 2551)
    assert PageSpec.preset("a4", bleed_mm=0).canvas_mm == (210.0, 297.0)
    with pytest.raises(ValueError):
        PageSpec.preset("Letter")
    with pytest.raises(ValueError):
        PageSpec((100.0, 100.0), safe_mm=60)


def test_full_bleed_box_reaches_the_canvas_edge_in_pixels():
    a5 = PageSpec.preset("A5")
    x, y, w, h = a5.box_px((0, 0, *a5.canvas_mm))
    assert (x, y) == (0, 0) and math.isclose(w, 1819) and math.isclose(h, 2551)


def test_safe_zone_and_bleed_facts():
    a5 = PageSpec.preset("A5")
    assert a5.safe_box_mm() == (8.0, 8.0, 138.0, 200.0)
    assert a5.inside_safe((10, 10, 100, 50))
    assert not a5.inside_safe((5, 10, 100, 50))  # crosses into the outer 5 mm band
    assert a5.reaches_bleed((0, 0, 154, 216)) == {"left": True, "top": True, "right": True, "bottom": True}
    assert a5.reaches_bleed((3, 3, 148, 210)) == {"left": False, "top": False, "right": False, "bottom": False}


def test_iso216_factor_applies_to_geometry_and_type():
    factor = iso216_scale("A4", "A5")
    assert math.isclose(factor, 1 / math.sqrt(2)) and math.isclose(factor, 0.70710678, rel_tol=1e-8)
    assert math.isclose(iso216_scale("A5", "A4"), math.sqrt(2))
    a4_box = (20.0, 30.0, 170.0, 100.0)
    assert scale_box(a4_box, factor) == pytest.approx((14.142, 21.213, 120.208, 70.711), abs=1e-3)
    assert 22 * factor == pytest.approx(15.556, abs=1e-3)  # A4 22 pt body becomes ~15.5 pt on A5


def test_folios_mirror_with_reading_direction():
    a5 = PageSpec.preset("A5")
    sx, _, sw, _ = a5.safe_box_mm()
    left = folio_box_mm(a5, 1, "rtl")
    right = folio_box_mm(a5, 2, "rtl")
    assert left[0] == sx and right[0] == sx + sw - right[2]
    assert folio_box_mm(a5, 1, "ltr")[0] == right[0]
    for page in (1, 2):
        assert a5.inside_safe(folio_box_mm(a5, page))
