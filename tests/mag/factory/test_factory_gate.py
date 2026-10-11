"""Phase 3 gate: a brand-new story becomes every variant, each passing the operator's own rules."""
from __future__ import annotations

import json
import math
import zipfile
from pathlib import Path

import pytest

from mxstudio.factory.demo_story import moon_star_story
from mxstudio.factory.forge import build_master, scale_spec, variant_filename
from mxstudio.factory.publish import build_pack, verify_pack
from mxstudio.factory.service import build_and_validate
from mxstudio.factory.story import NAME_TOKEN, Page, Story, apply_tashkeel

FIXTURE_FONTS = Path(__file__).resolve().parents[1] / "fixtures" / "fonts"


@pytest.fixture(scope="session")
def demo_result(tmp_path_factory, fixture_registry, fixture_fontconfig, soffice, render_deck):
    import os
    os.environ["FONTCONFIG_FILE"] = str(fixture_fontconfig)
    os.environ["MODULEX_SOFFICE"] = soffice
    out = tmp_path_factory.mktemp("factory")
    return build_and_validate(moon_star_story(), out, registry=fixture_registry, engines=["soffice"])


def test_story_rules_have_negative_controls():
    story = moon_star_story()
    assert story.validate() == []
    same = moon_star_story()
    for page in same.pages:
        if "ar_girl" in page.texts:
            page.texts["ar_girl"] = page.texts["ar_boy"]
    assert any("identical" in p for p in same.validate())
    broken = Story(key="Bad Key", title={"ar": "x", "en": "y"},
                   pages=[Page(kind="dedication", texts={v: "بدون اسم" for v in story.variants})])
    problems = broken.validate()
    assert any("ascii" in p for p in problems) and any("does not name" in p for p in problems)
    assert any("at least one scene" in p for p in problems)


def test_tashkeel_is_accepted_word_by_word_and_never_touches_the_name():
    text = f"ذهب {NAME_TOKEN} إلى البحر"
    proposals = {"ذهب": "ذَهَبَ", "البحر": "البَحْرِ", NAME_TOKEN: "إِيَاد"}
    assert apply_tashkeel(text, proposals, {"ذهب"}) == f"ذَهَبَ {NAME_TOKEN} إلى البحر"
    assert NAME_TOKEN in apply_tashkeel(text, proposals, set(proposals))


def test_iso216_scaling_is_exact_and_full_bleed_stays_full_bleed():
    master = build_master(moon_star_story(), "A4")
    a5 = scale_spec(master, "A5")
    factor = 1 / math.sqrt(2)
    assert a5["page"]["canvas_mm"] == [154.0, 216.0]
    for m_slide, s_slide in zip(master["slides"], a5["slides"]):
        for m_obj, s_obj in zip(m_slide["objects"], s_slide["objects"]):
            mx, my, mw, mh = m_obj["box_mm"]
            sx, sy, sw, sh = s_obj["box_mm"]
            if m_obj["kind"] == "picture_placeholder":
                assert sx == 0 and sw == pytest.approx(154.0, abs=0.01)
            elif m_obj["kind"] == "textbox":
                assert sx == pytest.approx(3 + (mx - 3) * factor, abs=0.01)
                assert sw == pytest.approx(mw * factor, abs=0.01)
                assert s_obj["style"]["font_size_pt"] == math.floor(m_obj["style"]["font_size_pt"] * factor * 2) / 2


def test_every_variant_passes_every_validator(demo_result):
    validation = demo_result["validation"]
    assert set(validation["variants"]) == {f"{v}_{s}" for v in ("ar_boy", "ar_girl", "en_boy", "en_girl")
                                          for s in ("A4", "A5")}
    for key, result in validation["variants"].items():
        assert result["ok"], (key, result["findings"])
        facts = result["facts"]
        assert facts["replacements"] == {"expected": 5, "step1": 5}
        assert facts["slots"]["measured"] == {1: 1, 2: 1, 3: 1, 4: 1, 6: 2}
        assert facts["export"]["has_text"] and facts["export"]["pages"] == 6
        assert facts["text_proof"]["ok"]
        assert facts["powerpoint_proof"].startswith("pending on device")
    assert Path(demo_result["contact_sheet"]).is_file()


def test_filenames_and_m1_m2_candidates(demo_result):
    assert variant_filename("moon_star", "ar_girl", "A5") == "moon_star_ar_girl_A5.pptx"
    m1, m2 = demo_result["m1"], demo_result["m2"]
    entry = m1["registry_entry"]
    assert entry["_v2"] and entry["variants"]["A5"]["ar"]["female"] == {"file": "moon_star_ar_girl_A5.pptx",
                                                                       "base_name": "جيداء"}
    assert entry["variants"]["A4"]["en"]["male"]["base_name"] == "Eyad"
    assert len(m1["files"]) == 8 and all(len(h) == 64 for h in m1["files"].values())
    assert m2["story_decks_entry"]["variants"]["girl_a4"] == "moon_star_ar_girl_A4.pptx"
    assert m2["slot_maps"]["boy_a5"] == {"1": 1, "2": 1, "3": 1, "4": 1, "6": 2}
    assert "never writes" in m2["approval"]


def test_signed_pack_verifies_and_tampering_is_caught(demo_result, tmp_path):
    story = moon_star_story()
    out = build_pack(tmp_path / "moon.magpack.zip", story, demo_result["built"], demo_result["validation"], "s3cret")
    assert verify_pack(Path(out["pack"]), "s3cret")["ok"]
    assert not verify_pack(Path(out["pack"]), "wrong")["ok"]
    tampered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(out["pack"]) as src, zipfile.ZipFile(tampered, "w") as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename.endswith("moon_star_ar_boy_A5.pptx"):
                data = data + b"x"
            dst.writestr(item, data)
    result = verify_pack(tampered, "s3cret")
    assert not result["ok"] and result["file_errors"] == ["moon_star_ar_boy_A5.pptx"]


def test_overflow_and_longest_name_are_named_findings(fixture_registry, tmp_path, render_deck):
    story = moon_star_story()
    long_text = "كان يا ما كان " * 60 + "{NAME}"
    story.pages[1].texts["ar_boy"] = long_text
    from mxstudio.factory.forge import forge
    from mxstudio.factory.validate import validate_set
    built = forge(story, tmp_path, sizes=("A5",), registry=fixture_registry)
    result = validate_set(built, tmp_path, registry=fixture_registry, export=False)
    codes = [f["code"] for f in result["variants"]["ar_boy_A5"]["findings"]]
    assert "fit" in codes and not result["ok"]
    assert result["variants"]["ar_girl_A5"]["ok"]


def test_api_build_approve_and_publish_flow(tmp_path, monkeypatch, fixture_fontconfig, soffice):
    import warnings
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    from starlette.testclient import TestClient

    from mxstudio.app.server import create_app
    from mxstudio.app.state import AppState
    monkeypatch.setenv("SLIDEPOISE_FONT_DIRS", str(FIXTURE_FONTS))
    monkeypatch.setenv("FONTCONFIG_FILE", str(fixture_fontconfig))
    monkeypatch.setenv("MXS_WORKSPACE", str(tmp_path / "المشروع" / "data"))
    state = AppState.create(tmp_path / "home")
    client = TestClient(create_app(state), client=("127.0.0.1", 5000))
    client.get("/")
    headers = {"X-MXS-CSRF": client.get("/api/session").json()["csrf"]}
    built = client.post("/api/tools/factory.build", json={"args": {"demo": True, "export": False}}, headers=headers).json()
    assert built["ok"] and built["result"]["ok"], built
    publish = {"story_key": "moon_star"}
    assert client.post("/api/tools/factory.publish_pack", json={"args": publish}, headers=headers).json()["code"] == \
        "CONFIRMATION_REQUIRED"
    approve = {"kind": "template_set", "key": "moon_star", "version": 1, "approved_by": "ModuleX operator"}
    token = client.post("/api/confirm", json={"tool": "workspace.approve", "args": approve}, headers=headers).json()["token"]
    assert client.post("/api/tools/workspace.approve", json={"args": approve, "confirmation_token": token},
                       headers=headers).json()["ok"]
    token = client.post("/api/confirm", json={"tool": "factory.publish_pack", "args": publish}, headers=headers).json()
    missing = client.post("/api/tools/factory.publish_pack", json={"args": publish, "confirmation_token": token["token"]},
                          headers=headers).json()
    assert missing["code"] == "HMAC_SECRET_MISSING"
    client.post("/api/secrets/modulex.hmac", json={"value": "shared-secret"}, headers=headers)
    token = client.post("/api/confirm", json={"tool": "factory.publish_pack", "args": publish}, headers=headers).json()
    done = client.post("/api/tools/factory.publish_pack", json={"args": publish, "confirmation_token": token["token"]},
                       headers=headers).json()
    assert done["ok"], done
    assert verify_pack(Path(done["result"]["pack"]), "shared-secret")["ok"]
    summary = client.get("/api/factory/summary").json()
    assert summary["facts"]["template_sets"][0]["approved"] is True
    assert json.dumps(summary)
