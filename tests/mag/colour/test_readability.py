"""Readability over real art: pixels under the box, busy-ness, treatment proposals."""
from __future__ import annotations

import cv2
import numpy as np
import pytest

from mxstudio.colour.readability import (assess, box_mm_to_px, busyness, check_page, check_text_box,
                                         region_under_box)

H, W = 300, 400
BOX = (50, 50, 300, 200)


def _flat(rgb=(245, 240, 225)):
    img = np.zeros((H, W, 3), np.uint8)
    img[:] = rgb
    return img


def _gradient():
    return np.repeat(np.linspace(0, 255, W, dtype=np.uint8)[None, :, None], H, 0).repeat(3, 2)


def _busy():
    rng = np.random.default_rng(1)
    img = _flat((60, 140, 70))
    for _ in range(400):
        c = tuple(int(v) for v in rng.integers(0, 255, 3))
        cv2.circle(img, (int(rng.integers(0, W)), int(rng.integers(0, H))), int(rng.integers(4, 18)), c, -1)
    return img


def _spotted():
    """Light paper with a few dark stones: median fine, worst patches fail."""
    img = _flat((240, 236, 228))
    img[60:90, 60:200] = (25, 25, 30)
    return img


def test_samples_the_actual_pixels_under_the_box():
    img = _flat()
    img[60:70, 60:70] = (0, 0, 255)
    crop = region_under_box(img, (55, 55, 20, 20))
    assert crop.shape == (20, 20, 3) and (crop == (0, 0, 255)).all(axis=-1).sum() == 100
    rgba = np.concatenate([img, np.zeros((H, W, 1), np.uint8)], axis=-1)      # transparent → paper white
    assert (region_under_box(rgba, BOX) == 255).all()
    with pytest.raises(ValueError):
        region_under_box(img, (500, 500, 10, 10))
    assert box_mm_to_px((10, 20, 50, 30), (154, 216), (1540, 2160)) == (100, 200, 500, 300)


def test_busyness_facts_separate_flat_gradient_and_busy():
    assert busyness(_flat()[:100, :100])["level"] == "flat"
    assert busyness(_gradient())["level"] == "flat"          # smooth tone change is not texture
    rng = np.random.default_rng(2)
    noise = rng.integers(0, 256, (120, 120, 3), dtype=np.uint8)
    assert busyness(noise)["level"] == "busy" and busyness(_busy())["level"] == "busy"


def test_readable_text_needs_no_treatment():
    r = check_text_box(_flat(), BOX, "#222222", 16)
    assert r["proposal"]["treatment"] == "none" and not r["blocking"] and r["findings"] == []
    assert r["facts"]["wcag_p"] > 10 and r["facts"]["apca_abs_p"] > 75


def test_gradient_gets_a_verified_soft_scrim():
    r = check_text_box(_gradient(), BOX, "#222222", 16)
    assert r["blocking"] and r["findings"][0]["finding"] == "text_contrast_below_minimum"
    p = r["proposal"]
    assert p["treatment"] == "soft_scrim" and p["verified"] and 0 < p["alpha"] <= 0.9
    assert p["predicted"]["wcag_p"] >= 4.5 and p["reason_ar"] and p["reason_en"]


def test_busy_art_gets_a_cloud_bubble():
    r = check_text_box(_busy(), BOX, "#222222", 16, roles={"background": "#fdf6e3", "outline": "#3a2b59"})
    p = r["proposal"]
    assert p["treatment"] == "cloud_bubble" and p["verified"] and p["fill"] == "#fdf6e3"
    assert p["outline_colour"] == "#3a2b59"


def test_few_bad_patches_get_an_outline():
    r = check_text_box(_spotted(), BOX, "#222222", 16)
    assert r["blocking"]
    p = r["proposal"]
    assert p["treatment"] == "outline_shadow" and p["verified"] and p["outline_width_pt"] >= 0.6


def test_art_is_never_modified_and_alternative_colour_offered():
    img = _flat((40, 40, 60))
    before = img.copy()
    r = check_text_box(img, BOX, "#222222", 16, roles={"text": "#1b1b2f", "background": "#fdfdf8"})
    assert np.array_equal(img, before)
    assert r["blocking"] and r["alternative_text_colour"] == "#fdfdf8"


def test_large_text_uses_the_large_floor():
    img = _flat((150, 150, 150))
    small = assess(img, BOX, "#ffffff", 12)
    large = assess(img, BOX, "#ffffff", 30, bold=True)
    assert small["wcag_min"] == 4.5 and large["wcag_min"] == 3.0
    assert small["passes"] is False


def test_page_check_negative_control():
    img = _flat()
    page = check_page(img, [{"id": "title", "box_px": BOX, "text_colour": "#222222", "font_size_pt": 28},
                            {"id": "ghost", "box_px": BOX, "text_colour": "#f5f0e1", "font_size_pt": 14}])
    assert page["blocking"] and [f["box_id"] for f in page["findings"]] == ["ghost"]


def test_apca_shortfall_alone_is_advisory():
    r = check_text_box(_flat((255, 255, 255)), BOX, "#767676", 12)   # WCAG 4.54 passes, APCA |Lc| ≈ 71 < 75
    assert r["facts"]["passes_wcag"] and not r["facts"]["passes_apca"]
    assert [(f["finding"], f["blocking"]) for f in r["findings"]] == [("text_contrast_apca_low", False)]
    assert not r["blocking"] and r["proposal"]["treatment"] != "none"
