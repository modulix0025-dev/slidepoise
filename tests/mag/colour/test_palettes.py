"""Curated kids' palettes: ≥ 80, tagged, each re-validated live for contrast and CMYK safety."""
from __future__ import annotations

import copy
import json
import re

import pytest

from mxstudio.colour import palettes as P
from mxstudio.colour.palettes import (AGES, REQUIRED_THEMES, build_palette, fit_to_press, get_palette, list_palettes,
                                      load_catalog, nearest_palettes, validate_palette)
from mxstudio.colour.roles import ROLES

ARABIC = re.compile(r"[؀-ۿ]")


@pytest.fixture(scope="module")
def catalog():
    return load_catalog()


def test_catalogue_size_tags_and_names(catalog):
    pals = catalog["palettes"]
    assert len(pals) >= 80
    ids = [p["id"] for p in pals]
    assert len(ids) == len(set(ids))
    themes = {t for p in pals for t in p["themes"]}
    assert set(REQUIRED_THEMES) <= themes
    for p in pals:
        assert ARABIC.search(p["name_ar"]) and p["name_en"].strip()
        assert p["ages"] and set(p["ages"]) <= set(AGES) and p["moods"] and p["themes"]
        assert tuple(p["roles"]) == ROLES and p["mode"] in ("light", "dark")
    for theme in REQUIRED_THEMES:
        assert len([p for p in pals if theme in p["themes"]]) >= 6, theme
    assert {a for p in pals for a in p["ages"]} == set(AGES)


def test_every_palette_passes_contrast_and_cmyk_safety_live(catalog):
    failures = {}
    for p in catalog["palettes"]:
        res = validate_palette(p)
        if not res["ok"]:
            failures[p["id"]] = res["failures"]
        assert res["text_wcag"] >= 4.5 and abs(res["text_apca_lc"]) >= 75
        for prof in res["print"].values():
            assert prof["max_delta_e2000"] <= 6.0 and prof["max_tac"] <= 300.5
    assert failures == {}


def test_stored_checks_agree_with_live_checks(catalog):
    for p in catalog["palettes"][::9]:
        live = validate_palette(p)
        assert p["checks"]["text_wcag"] == live["text_wcag"]
        assert p["checks"]["ok"] is True


def test_negative_controls_unreadable_and_unprintable_palettes_fail(catalog):
    p = copy.deepcopy(catalog["palettes"][0])
    p["roles"]["text"] = p["roles"]["background"]
    assert {"text_wcag", "text_apca"} <= set(validate_palette(p)["failures"])
    q = copy.deepcopy(catalog["palettes"][0])
    q["roles"]["accent"] = "#39ff14"          # neon green prints dull on both profiles
    assert {"print_delta_e:FOGRA39", "print_delta_e:GRACoL"} <= set(validate_palette(q)["failures"])
    r = copy.deepcopy(catalog["palettes"][0])
    r["roles"]["secondary"] = r["roles"]["primary"]
    assert "roles_not_distinct" in validate_palette(r)["failures"]
    s = copy.deepcopy(catalog["palettes"][0])
    s["ages"] = ["13-99"]
    assert "bad_ages" in validate_palette(s)["failures"]


def test_builder_pulls_neon_into_press_gamut():
    hx, changed = fit_to_press("#39ff14")
    assert changed
    from mxstudio.colour.print_safety import check_colour
    assert check_colour(hx)["delta_e2000"] <= 5.0
    assert fit_to_press("#2a9d8f") == ("#2a9d8f", False)
    pal = build_palette({"id": "t", "name_en": "T", "name_ar": "تجربة", "themes": ["sea"], "moods": ["calm"],
                         "ages": ["3-5"], "mode": "light", "primary": "#39ff14", "secondary": "#1d3557",
                         "accent": "#e63946"})
    assert "primary" in pal["print_fitted_roles"] and validate_palette(pal)["ok"]


def test_seeds_match_catalogue(catalog):
    seeds = json.loads(P.SEEDS.read_text(encoding="utf-8"))["palettes"]
    assert [s["id"] for s in seeds] == [p["id"] for p in catalog["palettes"]]
    for s, p in zip(seeds, catalog["palettes"]):
        assert p["seed"] == {r: s[r] for r in ("primary", "secondary", "accent")}


def test_filters_and_lookup():
    space_kids = list_palettes(theme="space", age="3-5")
    assert space_kids and all("space" in p["themes"] and "3-5" in p["ages"] for p in space_kids)
    assert all(p["mode"] == "dark" for p in list_palettes(theme="night", mode="dark"))
    assert get_palette("nile_morning")["name_ar"] == "صباح النيل"
    with pytest.raises(KeyError):
        get_palette("no_such_palette")
    near = nearest_palettes(["#2e86ab", "#6aa84f", "#f6ae2d"], k=3)
    assert near[0][0] == "nile_morning" and near[0][1] < 0.01
