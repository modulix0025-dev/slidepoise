"""Phase 7 gate: every new page kind passes the factory validators."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from PIL import Image

from mxstudio.factory.demo_story import moon_star_story
from mxstudio.factory.forge import forge
from mxstudio.factory.products import PAGE_KIND_PRODUCTS, Theme, class_magazine_plan, m3_candidate, make_qr_png
from mxstudio.factory.story import Page
from mxstudio.factory.validate import validate_set
from mxstudio.validators.operator_ports import replay_generate_story


def kinds_story():
    story = moon_star_story()
    story.key = "moon_star_kinds"
    t = {"ar_boy": "أنا {NAME}، بحب النجوم والرسم.", "ar_girl": "أنا {NAME}، بحب النجوم والرسم.",
         "en_boy": "I am {NAME}. I love stars and drawing.", "en_girl": "I am {NAME}. I love stars and drawing."}
    story.pages = [
        Page(kind="cover", texts={v: "{NAME} ونجمة القمر" if v.startswith("ar") else "{NAME} and the Moon Star"
                                  for v in t}),
        Page(kind="scene", texts=story.pages[1].texts, scene=story.pages[1].scene),
        Page(kind="about_me", texts=t, figure=False),
        Page(kind="certificate", title={"ar": "شهادة تقدير", "en": "Certificate"},
             texts={"ar_boy": "تُمنح لـ{NAME} لأنه ساعد النجمة ترجع للقمر.", "ar_girl": "تُمنح لـ{NAME} لأنها ساعدت النجمة ترجع للقمر.",
                    "en_boy": "Awarded to {NAME} for helping the star find the Moon.",
                    "en_girl": "Awarded to {NAME} for helping the star find the Moon."}),
        Page(kind="coloring", texts={v: ("لوّن {NAME} والنجمة" if v.startswith("ar") else "Color {NAME} and the star")
                                     for v in t}),
        Page(kind="bilingual", texts={"ar_boy": "طار {NAME} فوق النيل.", "ar_girl": "طارت {NAME} فوق النيل.",
                                      "en_boy": "{NAME} flew over the Nile.", "en_girl": "{NAME} flew over the Nile."}),
        Page(kind="class_page", texts={v: ("فصلنا الجميل" if v.startswith("ar") else "Our lovely class") for v in t}),
        Page(kind="qr_back", texts={v: ("امسح الكود وشوف فيلم {NAME}" if v.startswith("ar") else "Scan to watch {NAME}'s film")
                                    for v in t}),
    ]
    return story


@pytest.fixture(scope="module")
def kinds_result(tmp_path_factory, fixture_registry, fixture_fontconfig, soffice, render_deck):
    os.environ["FONTCONFIG_FILE"] = str(fixture_fontconfig)
    out = tmp_path_factory.mktemp("kinds")
    story = kinds_story()
    assert story.validate() == []
    built = forge(story, out, sizes=("A5",), registry=fixture_registry)
    return built, validate_set(built, out, registry=fixture_registry, engines=["soffice"])


def test_every_page_kind_validates_in_every_variant(kinds_result):
    built, validation = kinds_result
    for key, result in validation["variants"].items():
        assert result["ok"], (key, result["findings"])
        assert result["facts"]["slots"]["measured"] == {1: 1, 2: 1, 3: 1, 5: 1, 6: 1, 7: 1, 8: 1}
        assert result["facts"]["text_proof"]["ok"]


def test_bilingual_page_uses_one_name_and_both_directions(kinds_result, tmp_path):
    built, _ = kinds_result
    entry = built["variants"]["ar_girl_A5"]
    bilingual = entry["spec"]["slides"][5]["objects"]
    boxes = {o["id"]: o for o in bilingual if o["kind"] == "textbox"}
    ar, en = boxes["p6_body_ar"], boxes["p6_body_en"]
    assert ar["style"]["direction"] == "rtl" and en["style"]["direction"] == "ltr"
    assert any(r.get("text") == "جيداء" for r in en["runs"])  # the variant's own name in both languages
    out = replay_generate_story(Path(entry["path"]), "جيداء", "ليلى")
    assert "ليلى flew over the Nile." in out["paragraph_texts"]


def test_about_me_frame_is_offered_by_the_editor(kinds_result):
    built, _ = kinds_result
    photo = next(o for o in built["variants"]["ar_boy_A5"]["spec"]["slides"][2]["objects"]
                 if o["kind"] == "picture_placeholder")
    assert photo["label"] == "customer_photo"
    assert min(photo["box_mm"][2:]) / 10 >= 1.5  # MIN_FRAME_CM: smaller frames are decorations, not offered


def test_certificate_needs_titles_negative_control():
    story = kinds_story()
    story.pages[3].title = {"ar": "شهادة تقدير"}
    assert any("certificate needs a title in en" in p for p in story.validate())


def test_qr_class_plan_and_store_candidates(tmp_path):
    png = make_qr_png("https://modulex.example/v/abc123", tmp_path / "qr.png")
    assert Image.open(png).size[0] >= 200
    with pytest.raises(ValueError):
        make_qr_png("javascript:alert(1)", tmp_path / "bad.png")
    plan = class_magazine_plan("moon_star", [{"name": "محمد", "gender": "male"}, {"name": "سلمى", "gender": "female"},
                                              {"name": "", "gender": "male"}], "KG2-A")
    assert len(plan["orders"]) == 2 and plan["problems"] == ["row 3: needs a name and gender male/female"]
    assert "existing institution" in plan["engine"]
    theme = Theme("sea", "بحر وصيف", "Sea & summer", {"title": "Tajawal", "body": "Tajawal", "name": "Tajawal"},
                  {"text": "#123", "panel": "#fff", "outline": "#123"})
    assert m3_candidate("theme", "moon_star", theme)["theme"]["key"] == "sea"
    for kind in PAGE_KIND_PRODUCTS:
        assert m3_candidate(kind, "moon_star")["suggested_price_tokens"] >= 0
    with pytest.raises(ValueError):
        m3_candidate("nonsense")
