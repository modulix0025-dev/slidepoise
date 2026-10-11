"""Typography grid: role × page × age × script defaults; vowelized body only in certified fonts."""
from __future__ import annotations

import pytest

from mxstudio.fonts.typography import AGES, PAGES, ROLES, defaults, font_allowed, line_spacing, table


def test_grid_is_complete_and_matches_the_brief():
    grid = table()
    assert len(grid) == len(ROLES) * len(PAGES) * len(AGES) * 2 == 96
    for age in AGES:
        assert 13 <= defaults("body", "A5", age, "ar").default_pt <= 16
        assert 16 <= defaults("body", "A4", age, "ar").default_pt <= 22
        assert 11 <= defaults("body", "A5", age, "en").default_pt <= 13
        for page in PAGES:
            title = defaults("title", page, age, "ar")
            assert 24 <= title.min_pt <= title.default_pt <= title.max_pt <= 56
    assert defaults("body", "A4", "6-8", "en").source.startswith("derived")


def test_younger_readers_get_larger_type_and_vowels():
    sizes = [defaults("body", "A5", age, "ar").default_pt for age in ("9-12", "6-8", "3-5")]
    assert sizes == sorted(sizes) and sizes[0] < sizes[-1]
    assert defaults("body", "A5", "3-5", "ar").vowelized and not defaults("body", "A5", "9-12", "ar").vowelized
    assert defaults("child-name", "A5", "6-8", "ar").customer_styleable
    assert not defaults("body", "A5", "6-8", "ar").customer_styleable


def test_unknown_cell_is_an_error():
    with pytest.raises(ValueError):
        defaults("poster", "A5", "6-8", "ar")


def test_vowelized_body_limited_to_certified_fonts(committed):
    qa = committed["qa_status"]
    assert font_allowed("Noto Naskh Arabic", "body", "ar", qa, vowelized=True) == (True, [])
    assert font_allowed("Amiri", "body", "ar", qa, vowelized=False) == (True, [])
    ok, reasons = font_allowed("Amiri", "body", "ar", qa, vowelized=True)
    assert not ok and reasons == ["font_not_certified_for_vowelized_body"]


def test_negative_controls_for_font_eligibility(committed):
    qa = committed["qa_status"]
    assert font_allowed("Blaka", "handwriting-dedication", "ar", qa)[1] == ["font_has_no_tatweel"]
    assert "role_not_allowed_for_font" in font_allowed("Thabit", "body", "ar", qa)[1]
    assert "font_screen_only" in font_allowed("Nabla", "title", "en", qa)[1]
    assert "font_script_mismatch" in font_allowed("Chewy", "title", "ar", qa)[1]
    assert font_allowed("Blaka Hollow", "child-name", "ar", qa, lam_prefix=True)[1] == ["font_has_no_tatweel"]
    assert font_allowed("Not A Font", "title", "ar", qa) == (False, ["font_not_in_qa"])


def test_line_spacing_never_below_measured_minimum(committed):
    qa = committed["qa_status"]
    spec = defaults("title", "A5", "6-8", "ar")
    katibeh = next(f for f in qa["families"] if f["family"] == "Katibeh")["min_safe_line_spacing"]
    assert katibeh > 1.3 and line_spacing("Katibeh", spec, qa) == katibeh
    assert line_spacing("Baloo Bhaijaan 2", defaults("body", "A5", "6-8", "ar"), qa) == 1.2
