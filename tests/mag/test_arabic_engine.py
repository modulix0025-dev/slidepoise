"""Arabic measurement: exact family names, HarfBuzz shaping, harakat-aware fit, whitespace-only breaks."""
from __future__ import annotations

import pytest

from slidepoise.arabic import (directional_runs, fit_text, has_harakat, has_rtl, normalize_family, shape,
                               to_arabic_indic_digits, to_western_digits, wrap)
from slidepoise.arabic.fit import line_height_pt

BODY = "كان يا ما كان، ولد اسمه إياد يحب البحر كثيرًا، ويحلم كل ليلة بسمكة ذهبية تكلّمه."
NAMES = ["إياد", "جيداء", "عبد الرحمن", "فاطمة الزهراء", "يُوسُف", "مَرْيَم"]


def test_family_names_keep_internal_whitespace(fixture_registry):
    assert normalize_family("  Blabeloo  MagdySoliman ") == "blabeloo  magdysoliman"
    assert normalize_family("Blabeloo  MagdySoliman") != normalize_family("Blabeloo MagdySoliman")
    assert fixture_registry.has("Tajawal") and fixture_registry.has("tajawal")
    assert fixture_registry.resolve("Blabeloo  MagdySoliman") is None  # never substituted silently
    assert fixture_registry.resolve("Taja wal") is None


def test_weight_selection(fixture_registry):
    assert fixture_registry.resolve("Tajawal").weight == 400
    assert fixture_registry.resolve("Tajawal", bold=True).weight == 700


@pytest.mark.parametrize("family", ["Tajawal", "Amiri"])
def test_names_shape_without_notdef(fixture_registry, family):
    face = fixture_registry.resolve(family)
    for name in NAMES:
        assert shape(face.path, face.index, name).notdef == 0, name


def test_negative_control_latin_only_font_reports_notdef(fixture_registry, tmp_path):
    """A font with no Arabic glyphs must be detectable — the check can fail."""
    from fontTools.subset import Options, Subsetter
    from fontTools.ttLib import TTFont

    source = fixture_registry.resolve("Tajawal")
    font = TTFont(source.path)
    subsetter = Subsetter(Options())
    subsetter.populate(text="Eyad abc")
    subsetter.subset(font)
    latin = tmp_path / "LatinOnly.ttf"
    font.save(latin)
    assert shape(str(latin), 0, "إياد").notdef == 4


def test_directional_runs_and_detection():
    runs = directional_runs("كان إياد يحب Lego كثيرًا 2026.")
    assert [rtl for _, rtl in runs] == [True, False, True]
    assert "".join(text for text, _ in runs) == "كان إياد يحب Lego كثيرًا 2026."
    assert has_rtl("إياد") and not has_rtl("Eyad")
    assert has_harakat("مَرْيَم") and not has_harakat("مريم")


def test_digit_settings_round_trip():
    assert to_arabic_indic_digits("صفحة 12") == "صفحة ١٢"
    assert to_western_digits("صفحة ١٢") == "صفحة 12"


def test_arabic_words_are_never_split(fixture_registry):
    face = fixture_registry.resolve("Tajawal")
    lines, too_wide = wrap(face, BODY, 16, 150)
    words = BODY.split()
    assert " ".join(lines).split() == words
    assert too_wide == []
    _, too_wide = wrap(face, "عبدالرحمن", 40, 30)
    assert too_wide == ["عبدالرحمن"]  # reported, never broken mid-word


def test_harakat_raise_the_line_box(fixture_registry):
    face = fixture_registry.resolve("Amiri")
    plain = line_height_pt(face, ["محمد يحب البحر"], 20, 0.5)
    vowelised = line_height_pt(face, ["مُحَمَّدٌ يُحِبُّ البَحْرَ"], 20, 0.5)
    assert vowelised > plain


def test_fit_shrinks_then_reports_overflow(fixture_registry):
    roomy = fit_text(BODY, 300, 120, "Tajawal", registry=fixture_registry, max_size_pt=20, min_size_pt=10)
    assert roomy.fits and roomy.size_pt == 20 and roomy.rtl and roomy.notdef == 0
    tight = fit_text(BODY, 300, 60, "Tajawal", registry=fixture_registry, max_size_pt=20, min_size_pt=10)
    assert tight.fits and tight.size_pt < 20
    impossible = fit_text(BODY * 4, 150, 40, "Tajawal", registry=fixture_registry, max_size_pt=20, min_size_pt=12)
    assert not impossible.fits and impossible.size_pt == 12 and impossible.overflow_height_pt > 0


def test_fit_with_a_labelled_substitute(fixture_registry):
    result = fit_text("إياد", 200, 60, "Blabeloo  MagdySoliman", registry=fixture_registry,
                      fallback_family="Tajawal")
    assert result.substitute_for == "Blabeloo  MagdySoliman" and result.font_family == "Tajawal"
    with pytest.raises(LookupError):
        fit_text("إياد", 200, 60, "Blabeloo  MagdySoliman", registry=fixture_registry)


def test_upstream_fitter_uses_harfbuzz_for_rtl(fixture_registry, monkeypatch):
    from slidepoise.arabic import fonts
    from slidepoise.reconstruction import text_fit

    monkeypatch.setattr(fonts, "default_registry", lambda: fixture_registry)
    entity = {"id": "t1", "text": BODY, "measurement": {"layout_bbox": {"px": [0, 0, 600, 200]}}}
    style = {"family": "Tajawal", "bold": False, "italic": False, "line_spacing": 1.1, "role_policy": {}}
    result = text_fit._fits(entity, style, 24)
    assert result is not None and result["shaping"] == "harfbuzz"
    latin = text_fit._fits({**entity, "text": "Plain English copy"}, {**style, "family": "Arial"}, 24)
    assert latin is not None and "shaping" not in latin
