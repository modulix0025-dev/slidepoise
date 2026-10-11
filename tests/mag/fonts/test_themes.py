"""Type themes: ≥30 AR↔EN pairings, every font in the catalog and certified; quarantined fonts fail."""
from __future__ import annotations

import copy

from mxstudio.fonts.themes import validate_themes

SEEDS = {"مرح كلاسيكي", "مدرسة وكراسة", "ألف ليلة", "فضاء وروبوتات", "بحر وصيف", "قراصنة", "أميرات وسحر", "كوميكس",
         "تراث مصري", "حلويات", "ديناصورات", "كراسة تلوين"}


def test_committed_themes_validate(committed, catalog):
    themes = committed["type_themes"]
    errors, warnings = validate_themes(themes, catalog, committed["qa_status"])
    assert errors == []
    assert all(w["finding"].startswith("theme_font_") for w in warnings)
    assert len(themes["themes"]) >= 30
    assert SEEDS <= {t["name_ar"] for t in themes["themes"]}
    by = {t["id"]: t for t in themes["themes"]}
    assert (by["classic_fun"]["ar_title"], by["classic_fun"]["en_title"]) == ("Baloo Bhaijaan 2", "Baloo 2")
    assert (by["school_notebook"]["ar_title"], by["school_notebook"]["en_title"]) == ("Playpen Sans Arabic",
                                                                                      "Playpen Sans")
    assert (by["easy_reading"]["ar_body"], by["easy_reading"]["en_body"]) == ("Readex Pro", "Lexend")
    assert by["princesses_magic"]["ar_name"] == "Reem Kufi"
    assert "no_lam_tatweel_prefix" in by["coloring_book"]["constraints"]


def _broken(themes, **changes):
    data = copy.deepcopy(themes)
    data["themes"][0].update(changes)
    return data


def test_negative_control_quarantined_font_fails(committed, catalog):
    data = _broken(committed["type_themes"], ar_name="Reem Kufi Fun")
    errors, _ = validate_themes(data, catalog, committed["qa_status"])
    assert [(e["finding"], e["font"]) for e in errors] == [("theme_font_quarantined", "Reem Kufi Fun")]


def test_negative_control_each_rule_can_fail(committed, catalog):
    qa = committed["qa_status"]
    cases = {
        "theme_font_not_in_catalog": {"en_title": "Comic Sans MS"},
        "theme_dedication_without_tatweel": {"ar_dedication": "Blaka"},
        "theme_vowelized_body_not_certified": {"ar_body_vowelized": "Amiri"},
        "theme_name_font_needs_no_lam_prefix_constraint": {"ar_name": "Blaka Hollow"},
        "theme_font_script_mismatch": {"ar_body": "Nunito"},
        "theme_monospace_outside_titles": {"ar_body": "Thabit"},
    }
    for finding, change in cases.items():
        errors, _ = validate_themes(_broken(committed["type_themes"], **change), catalog, qa)
        assert finding in {e["finding"] for e in errors}, finding
    few = copy.deepcopy(committed["type_themes"])
    few["themes"] = few["themes"][:29]
    assert validate_themes(few, catalog, qa)[0][0]["finding"] == "theme_count_below_minimum"
