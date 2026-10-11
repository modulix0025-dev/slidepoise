"""Known answers for OKLab/OKLCH conversions and OKLCH harmonies (coloraide is the reference)."""
from __future__ import annotations

import numpy as np
import pytest
from coloraide import Color

from mxstudio.colour.harmony import SCHEMES, harmony, harmony_hex
from mxstudio.colour.oklch import (delta_e_ok, from_oklch, hue_distance, oklab_array_to_srgb, parse_rgb,
                                   srgb_array_to_lab_d50, srgb_array_to_oklab, to_hex, to_oklab, to_oklch)

# Reference values printed by coloraide 8.13 (and, for the primaries, Ottosson's OKLab post).
OKLCH_REF = {
    "#ff0000": (0.62796, 0.25768, 29.234),
    "#00ff00": (0.86644, 0.29483, 142.495),
    "#0000ff": (0.45201, 0.31321, 264.052),
    "#ffffff": (1.0, 0.0, None),
    "#808080": (0.59987, 0.0, None),
    "#e0ac69": (0.778, 0.104, 72.305),
}


@pytest.mark.parametrize("hx, ref", OKLCH_REF.items())
def test_oklch_known_answers(hx, ref):
    L, C, h = to_oklch(hx)
    assert L == pytest.approx(ref[0], abs=6e-4)
    assert C == pytest.approx(ref[1], abs=6e-4)
    if ref[2] is not None:
        assert h == pytest.approx(ref[2], abs=0.02)


def test_oklab_red_matches_ottosson():
    L, a, b = to_oklab("#ff0000")
    assert (L, a, b) == pytest.approx((0.627955, 0.224863, 0.125846), abs=2e-4)


def test_array_paths_match_coloraide():
    rng = np.random.default_rng(3)
    px = rng.integers(0, 256, (200, 3), dtype=np.uint8)
    ok = srgb_array_to_oklab(px)
    lab = srgb_array_to_lab_d50(px)
    for i in range(0, 200, 7):
        c = Color("srgb", [v / 255 for v in px[i]])
        assert ok[i] == pytest.approx(c.convert("oklab").coords(), abs=2e-4)
        assert lab[i] == pytest.approx(c.convert("lab").coords(), abs=0.02)
    back = np.round(oklab_array_to_srgb(ok) * 255).astype(int)
    assert np.abs(back - px.astype(int)).max() <= 1


def test_from_oklch_roundtrip_and_gamut_flag():
    hx, ok = from_oklch(*to_oklch("#2a9d8f"))
    assert ok and hx == "#2a9d8f"
    hx, ok = from_oklch(0.7, 0.35, 150.0)          # far outside sRGB
    assert not ok
    L, C, h = to_oklch(hx)
    assert L == pytest.approx(0.7, abs=0.01) and hue_distance(h, 150.0) < 2.0 and C < 0.35


def test_parse_rgb_and_negative_control():
    assert parse_rgb("#abc") == (0xAA, 0xBB, 0xCC) and to_hex((1, 2, 3)) == "#010203"
    for bad in ("#12", "red", (0, 0, 256), (1, 2)):
        with pytest.raises(ValueError):
            parse_rgb(bad)


@pytest.mark.parametrize("scheme, coloraide_name", [("complementary", "complement"), ("triadic", "triad"),
                                                     ("split_complementary", "split"), ("analogous", "analogous"),
                                                     ("square", "square")])
def test_harmony_hues_match_coloraide(scheme, coloraide_name):
    base = "#e63946"
    mine = sorted(round(m.h % 360, 1) for m in harmony(base, scheme))
    ref = sorted(round((c.convert("oklch")["hue"]) % 360, 1)
                 for c in Color(base).harmony(coloraide_name, space="oklch"))
    assert all(abs(a - b) < 0.2 for a, b in zip(mine, ref)) and len(mine) == len(ref)


def test_harmony_offsets_and_controlled_lightness_chroma():
    base_h = to_oklch("#3a86ff")[2]
    for scheme, offsets in SCHEMES.items():
        members = harmony("#3a86ff", scheme, lightness=0.72, chroma=0.10)
        assert [round(hue_distance(m.h, base_h + o), 3) for m, o in zip(members, offsets)] == [0.0] * len(offsets)
        for m in members:
            L, C, _h = to_oklch(m.hex)
            assert m.in_gamut
            assert L == pytest.approx(0.72, abs=0.004) and C == pytest.approx(0.10, abs=0.004)
    # members of a scheme are equally light: OKLab distance is mostly hue
    a, b = harmony_hex("#3a86ff", "complementary", lightness=0.72, chroma=0.10)
    assert delta_e_ok(a, b) == pytest.approx(0.20, abs=0.01)


def test_harmony_out_of_gamut_is_reported_not_hidden():
    members = harmony("#ff0000", "triadic", lightness=0.6, chroma=0.3)
    assert not all(m.in_gamut for m in members)
    assert all(to_oklch(m.hex)[1] <= 0.3 for m in members)


def test_harmony_negative_controls():
    with pytest.raises(ValueError):
        harmony("#ff0000", "pentadic")
    with pytest.raises(ValueError):
        harmony("#ff0000", "triadic", lightness=1.5)
    comp = harmony("#ff0000", "complementary")
    assert hue_distance(comp[0].h, comp[1].h) == pytest.approx(180.0, abs=0.01)
    assert hue_distance(comp[0].h, comp[1].h) != pytest.approx(120.0, abs=1.0)
