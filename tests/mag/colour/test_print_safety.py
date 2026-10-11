"""ICC CMYK conversion, ΔE2000 print warnings, ink limit and rich-black guidance."""
from __future__ import annotations

import hashlib
import json
import shutil

import pytest
from PIL import ImageCms

from mxstudio.colour import print_safety as ps
from mxstudio.colour.print_safety import (PrintSettings, check_cmyk, check_colour, check_image, check_palette,
                                          profile_info, rich_black_guidance, soft_proof, srgb_to_cmyk)

PINNED = {"FOGRA39": "3ff7ca2a650ad47a8d2a929eb23ef162ccf979d013ade56e441c1f55156a261f",
          "GRACoL": "6c5ad2c4536cb1e0ff9f61ae4c090ff0034c3886d12783ca628bf4d13dcac860"}


def test_bundled_profiles_are_pinned_cc0_and_self_contained():
    prov = json.loads((ps.DEFAULT_ICC_DIR / "PROVENANCE.json").read_text(encoding="utf-8"))
    for key, digest in PINNED.items():
        entry = prov["profiles"][key]
        path = ps.DEFAULT_ICC_DIR / entry["file"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest == entry["sha256"]
        assert entry["licence"] == "CC0-1.0" and "colord" in entry["source_url"] and entry["retrieved_at"]
        assert "/usr/share" not in str(path)
        info = profile_info(PrintSettings(profile=key))
        assert info["sha256"] == digest and info["licence"] == "CC0-1.0"


def test_known_cmyk_values_fogra39():
    c, m, y, k = srgb_to_cmyk("#ff0000")
    assert (round(c), round(m), round(y), round(k)) == (0, 95, 100, 0)
    black = check_colour("#000000")
    assert [round(v) for v in black["cmyk"]] == [83, 72, 45, 100]
    assert black["tac"] == pytest.approx(300.0, abs=0.5) and not black["blocking"]


def test_neon_green_warns_and_round_trips_dull():
    r = check_colour("#39ff14")
    assert r["warn_dull"] and r["delta_e2000"] > 12
    assert r["findings"][0]["finding"] == "colour_shifts_in_print" and r["findings"][0]["blocking"] is False
    printed = tuple(int(r["printed_hex"][i:i + 2], 16) for i in (1, 3, 5))
    assert all(abs(a - b) <= 2 for a, b in zip(printed, (116, 183, 60)))
    assert r["findings"][0]["ar"] and r["findings"][0]["en"]


def test_negative_control_in_gamut_colours_do_not_warn():
    for hx in ("#2a9d8f", "#264653", "#e9c46a", "#808080", "#ffffff"):
        r = check_colour(hx)
        assert not r["warn_dull"] and r["delta_e2000"] < 3, hx


def test_gracol_is_operator_selectable_and_differs():
    f = check_colour("#000000", PrintSettings(profile="FOGRA39"))
    g = check_colour("#000000", PrintSettings(profile="GRACoL"))
    assert [round(v) for v in g["cmyk"]] == [80, 64, 56, 100] and f["cmyk"] != g["cmyk"]
    assert check_colour("#39ff14", PrintSettings(profile="GRACoL"))["warn_dull"]


def test_operator_supplied_profile_path_and_non_cmyk_refused(tmp_path):
    own = tmp_path / "printer.icc"
    shutil.copy(ps.DEFAULT_ICC_DIR / "GRACoL_TR006_coated.icc", own)
    assert check_colour("#ff0000", PrintSettings(profile=str(own)))["cmyk"][1] > 90
    rgb_icc = tmp_path / "srgb.icc"
    rgb_icc.write_bytes(ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes())
    with pytest.raises(ValueError):
        check_colour("#ff0000", PrintSettings(profile=str(rgb_icc)))
    with pytest.raises(FileNotFoundError):
        check_colour("#ff0000", PrintSettings(profile="NoSuchPrinter"))


def test_tampered_bundled_profile_is_refused(tmp_path, monkeypatch):
    icc = tmp_path / "icc"
    shutil.copytree(ps.DEFAULT_ICC_DIR, icc)
    data = bytearray((icc / "FOGRA39L_coated.icc").read_bytes())
    data[-1] ^= 0xFF
    (icc / "FOGRA39L_coated.icc").write_bytes(bytes(data))
    monkeypatch.setenv("MXS_ICC_DIR", str(icc))
    ps.provenance.cache_clear()
    try:
        with pytest.raises(RuntimeError):
            check_colour("#ff0000")
    finally:
        monkeypatch.delenv("MXS_ICC_DIR")
        ps.provenance.cache_clear()


def test_ink_limit_is_blocking_and_operator_selectable():
    assert check_cmyk([100, 100, 100, 100])["blocking"]                      # 400 % registration black
    assert check_cmyk([100, 100, 100, 100])["findings"][0]["finding"] == "ink_coverage_over_limit"
    assert not check_cmyk([60, 40, 40, 100])["blocking"]                     # 240 % rich black
    strict = PrintSettings(tac_limit=280)
    assert check_colour("#000000", strict)["blocking"]                       # 300 % on a 280 % press
    assert not check_colour("#000000")["blocking"]
    with pytest.raises(ValueError):
        check_cmyk([120, 0, 0, 0])


def test_dark_background_image_tac(muted_art):
    import numpy as np
    dark = np.zeros((120, 120, 3), np.uint8)
    dark[:] = (5, 5, 8)
    rep = check_image(dark, PrintSettings(tac_limit=260))
    assert rep["blocking"] and rep["dark_area"] > 0.99
    f = [x for x in rep["findings"] if x["finding"] == "ink_coverage_over_limit"][0]
    assert f["dark_area_over"] > 0.99
    assert not check_image(muted_art)["blocking"]


def test_image_neon_warning_and_negative_control(neon_art, muted_art):
    rep = check_image(neon_art)
    assert rep["warn"] and not rep["blocking"]
    f = rep["findings"][0]
    assert f["finding"] == "colour_shifts_in_print" and f["area"] == pytest.approx(0.30, abs=0.01)
    assert f["worst"][0]["hex"] == "#39ff14"
    calm = check_image(muted_art)
    assert not calm["warn"] and calm["findings"] == []


def test_palette_and_soft_proof(neon_art):
    pal = check_palette(["#39ff14", "#2a9d8f"])
    assert pal["warn"] and pal["max_delta_e2000"] > 12 and pal["lcms"]
    proof = soft_proof(neon_art)
    assert proof.size == (200, 200) and proof.getpixel((10, 10))[:3] != (57, 255, 20)


def test_rich_black_guidance():
    small = rich_black_guidance("text", font_size_pt=12)
    assert small["cmyk"] == [0, 0, 0, 100] and small["ar"] and small["en"]
    bg = rich_black_guidance("background")
    assert bg["tac"] == 240 and bg["within_limit"] and bg["printed_L"] < bg["k_only_L"]
    assert rich_black_guidance("line")["cmyk"] == [0, 0, 0, 100]
    with pytest.raises(ValueError):
        rich_black_guidance("poster")
