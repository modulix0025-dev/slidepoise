"""Palette extraction (area-weighted OKLab k-means, skin/neutral separation) and deck roles."""
from __future__ import annotations

import numpy as np
import pytest

from mxstudio.colour.contrast import wcag_contrast
from mxstudio.colour.extract import extract_palette
from mxstudio.colour.oklch import delta_e_ok
from mxstudio.colour.roles import ROLES, DeckPalette, check_roles, consistency_report, derive_roles, nearest_role

SKY, GRASS, SKIN = (90, 170, 230), (70, 150, 60), (224, 172, 105)  # same as conftest.scene_art


def _hex(rgb):
    return "#%02x%02x%02x" % rgb


def test_area_weighted_palette_on_known_scene(scene_art):
    img, _mask = scene_art
    pal = extract_palette(img, k=4)
    cols = pal["colours"]
    assert delta_e_ok(cols[0]["hex"], _hex(SKY)) < 0.01 and cols[0]["area"] == pytest.approx(0.6125, abs=0.01)
    assert delta_e_ok(cols[1]["hex"], _hex(GRASS)) < 0.01 and cols[1]["area"] == pytest.approx(0.25, abs=0.01)
    assert pal["skin_source"] == "heuristic"
    assert pal["skin"] and delta_e_ok(pal["skin"][0]["hex"], _hex(SKIN)) < 0.01
    assert pal["fractions"]["skin"] == pytest.approx(0.10, abs=0.01)
    assert pal["fractions"]["neutral"] == pytest.approx(0.0375, abs=0.01)
    # skin and the white cloud never leak into the chromatic (role-candidate) colours
    assert all(delta_e_ok(c["hex"], _hex(SKIN)) > 0.05 for c in cols)
    assert all(c["oklch"][1] >= 0.035 for c in cols)


def test_host_mask_wins_and_is_reported(scene_art):
    img, mask = scene_art
    pal = extract_palette(img, k=4, skin_mask=mask)
    assert pal["skin_source"] == "mask" and pal["fractions"]["skin"] == pytest.approx(0.10, abs=0.01)
    off = extract_palette(img, k=4, detect_skin=False)
    assert off["skin_source"] == "off" and off["skin"] == []
    assert any(delta_e_ok(c["hex"], _hex(SKIN)) < 0.01 for c in off["colours"])  # negative control: no separation
    with pytest.raises(ValueError):
        extract_palette(img, skin_mask=np.zeros((3, 3), bool))


def test_extraction_is_deterministic_and_ignores_transparency(scene_art):
    img, _ = scene_art
    assert extract_palette(img) == extract_palette(img)
    rgba = np.concatenate([img, np.full(img.shape[:2] + (1,), 255, np.uint8)], axis=-1)
    rgba[:225, :, 3] = 0       # hide everything but the grass
    pal = extract_palette(rgba)
    assert len(pal["colours"]) >= 1 and delta_e_ok(pal["colours"][0]["hex"], _hex(GRASS)) < 0.01
    assert pal["colours"][0]["area"] == pytest.approx(1.0, abs=0.01)
    empty = rgba.copy()
    empty[..., 3] = 0
    assert extract_palette(empty)["pixels"] == 0


def test_roles_from_extracted_palette(scene_art):
    img, mask = scene_art
    deck = derive_roles(extract_palette(img, skin_mask=mask))
    roles = deck.roles()
    assert tuple(roles) == ROLES and deck.mode == "light"
    assert delta_e_ok(roles["primary"], _hex(SKY)) < 0.01           # frames come from the art
    assert delta_e_ok(roles["secondary"], _hex(GRASS)) < 0.01
    assert wcag_contrast(roles["text"], roles["background"]) >= 7.0
    assert wcag_contrast(roles["outline"], roles["background"]) >= 3.0
    assert check_roles(deck) == []


def test_dark_art_gives_dark_mode():
    night = np.zeros((100, 100, 3), np.uint8)
    night[:] = (20, 30, 70)
    night[40:60, 40:60] = (250, 210, 90)
    deck = derive_roles(extract_palette(night))
    assert deck.mode == "dark"
    assert wcag_contrast(deck.text, deck.background) >= 7.0


def test_single_hue_art_synthesises_and_notes():
    deck = derive_roles(["#2a9d8f"])
    assert len({deck.primary, deck.secondary, deck.accent}) == 3 and len(deck.notes) == 2


def test_role_check_negative_control():
    bad = DeckPalette(background="#ffffff", primary="#2a9d8f", secondary="#e9c46a", accent="#e76f51",
                      text="#aaaaaa", outline="#eeeeee")
    names = {f["finding"]: f["blocking"] for f in check_roles(bad)}
    assert names == {"role_text_contrast_below_minimum": True, "role_outline_contrast_low": False}


def test_cross_page_consistency_reports_drift_only_as_advice():
    deck = derive_roles(["#2a9d8f", "#e9c46a", "#e76f51"])
    pages = [{"page_id": "p1", "colours": {"primary": deck.primary, "frame": deck.secondary}},
             {"page_id": "p2", "colours": {"primary": deck.primary, "text": deck.text}}]
    ok = consistency_report(deck, pages)
    assert ok["consistent"] and ok["checked"] == 4 and not ok["blocking"]
    drift = consistency_report(deck, pages + [{"page_id": "p3", "colours": {"primary": "#1d3557"}}])
    assert not drift["consistent"] and drift["finding"] == "palette_role_drift" and not drift["blocking"]
    assert drift["drifts"][0]["page_id"] == "p3"
    assert nearest_role(deck, deck.accent) == ("accent", 0.0)
