"""Gendered / bilingual payloads on one semantic map, and the no-Arabic-in-art evidence."""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont, features

from mxstudio.factory.payloads import coverage_findings, name_token_findings, resolve_spec
from mxstudio.validators.art_text import FINDING, inspect_slot, inspect_target

FONT = Path(__file__).resolve().parent / "fixtures" / "fonts" / "tajawal" / "Tajawal-Regular.ttf"
BASE = {"ar_boy": "إياد", "ar_girl": "جيداء", "en_boy": "Eyad", "en_girl": "Gaidaa"}


def _spec():
    return {"slides": [{"id": "p1", "dimensions_px": [100, 140], "objects": [
        {"id": "body", "kind": "textbox", "bbox_px": [5, 80, 90, 50], "style": {"alignment": "right", "font_size_pt": 16},
         "payloads": {
             "ar_boy": {"runs": [{"text": "ذهب "}, {"text": "إياد", "role": "child_name"}, {"text": " إلى البحر."}]},
             "ar_girl": {"runs": [{"text": "ذهبت "}, {"text": "جيداء", "role": "child_name"}, {"text": " إلى البحر."}]},
             "en_boy": {"runs": [{"text": "Eyad", "role": "child_name"}, {"text": " went to the sea."}]},
             "en_girl": {"runs": [{"text": "Gaidaa", "role": "child_name"}, {"text": " went to the sea."}],
                         "style": {"font_size_pt": 13}},
         }},
        {"id": "scene", "kind": "picture_placeholder", "bbox_px": [0, 0, 100, 75]},
    ]}]}


def test_variants_resolve_direction_language_and_alignment():
    spec = _spec()
    girl = resolve_spec(spec, "ar_girl", BASE)["slides"][0]["objects"][0]
    assert girl["runs"][0]["text"] == "ذهبت " and girl["style"]["direction"] == "rtl"
    assert girl["style"]["lang"] == "ar-EG" and girl["style"]["alignment"] == "right"
    english = resolve_spec(spec, "en_girl", BASE)
    body = english["slides"][0]["objects"][0]
    assert english["language"] == "en-US" and body["style"]["direction"] == "ltr"
    assert body["style"]["alignment"] == "left" and body["style"]["font_size_pt"] == 13
    assert english["slides"][0]["objects"][1]["kind"] == "picture_placeholder"
    assert "payloads" not in body
    assert coverage_findings(spec) == []


def test_payload_negative_controls():
    spec = _spec()
    del spec["slides"][0]["objects"][0]["payloads"]["en_boy"]
    assert coverage_findings(spec) == ["body: missing en_boy"]
    with pytest.raises(ValueError, match="no payload for en_boy"):
        resolve_spec(spec, "en_boy")
    wrong = _spec()
    wrong["slides"][0]["objects"][0]["payloads"]["ar_girl"]["runs"][1]["text"] = "إياد"
    with pytest.raises(ValueError, match="child_name run"):
        resolve_spec(wrong, "ar_girl", BASE)
    assert name_token_findings(resolve_spec(_spec(), "ar_boy"), "إياد") == []


def _scene(draw_text: bool):
    image = Image.new("RGB", (900, 600), (120, 180, 230))
    draw = ImageDraw.Draw(image)
    draw.ellipse((40, 330, 860, 580), fill=(250, 250, 245))
    if draw_text:
        font = ImageFont.truetype(str(FONT), 44)
        rtl = "rtl" if features.check("raqm") else None  # Windows Pillow wheels have no libraqm; glyphs still land
        draw.text((820, 380), "كان يا ما كان ولد اسمه إياد", font=font, fill=(30, 30, 30), direction=rtl, anchor="ra")
        draw.text((820, 450), "يحب البحر كثيرا ويحلم بسمكة", font=font, fill=(30, 30, 30), direction=rtl, anchor="ra")
    return np.ascontiguousarray(np.array(image)[:, :, ::-1])


SLOT = (100, 360, 700, 180)


def test_empty_treatment_is_clean():
    evidence = inspect_slot(_scene(False), SLOT, "body")
    assert not evidence.blocking and evidence.as_dict()["finding"] is None


def test_glyphs_in_a_text_slot_are_a_named_blocking_finding(tmp_path):
    path = tmp_path / "target.png"
    cv2.imwrite(str(path), _scene(True))
    [finding] = inspect_target(path, {"body": SLOT})
    assert finding["blocking"] and finding["finding"] == FINDING
    assert finding["components"] >= 8


def test_texture_without_baselines_is_not_called_text():
    image = _scene(False)
    rng = np.random.default_rng(1)
    for _ in range(60):
        center = (int(rng.integers(60, 840)), int(rng.integers(340, 570)))
        cv2.circle(image, center, int(rng.integers(3, 25)), (int(rng.integers(0, 255)),) * 3, -1)
    assert not inspect_slot(image, SLOT).blocking
