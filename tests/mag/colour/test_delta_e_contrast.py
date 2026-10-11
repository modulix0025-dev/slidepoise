"""ΔE2000 against Sharma, Wu & Dalal (2005) and contrast against WCAG/APCA reference values."""
from __future__ import annotations

import numpy as np
import pytest
from coloraide import Color

from mxstudio.colour.contrast import (APCA_98G, apca_lc, apca_threshold, contrast_report, wcag_contrast,
                                      wcag_threshold)
from mxstudio.colour.delta_e import ciede2000, delta_e_2000

# Sharma, Wu, Dalal, "The CIEDE2000 color-difference formula: implementation notes,
# supplementary test data, and mathematical observations", Color Res. Appl. 30(1), 2005, Table 1.
SHARMA = [
    ((50.0000, 2.6772, -79.7751), (50.0000, 0.0000, -82.7485), 2.0425),
    ((50.0000, 3.1571, -77.2803), (50.0000, 0.0000, -82.7485), 2.8615),
    ((50.0000, 2.8361, -74.0200), (50.0000, 0.0000, -82.7485), 3.4412),
    ((50.0000, -1.3802, -84.2814), (50.0000, 0.0000, -82.7485), 1.0000),
    ((50.0000, -1.1848, -84.8006), (50.0000, 0.0000, -82.7485), 1.0000),
    ((50.0000, -0.9009, -85.5211), (50.0000, 0.0000, -82.7485), 1.0000),
    ((50.0000, 0.0000, 0.0000), (50.0000, -1.0000, 2.0000), 2.3669),
    ((50.0000, -1.0000, 2.0000), (50.0000, 0.0000, 0.0000), 2.3669),
    ((50.0000, 2.4900, -0.0010), (50.0000, -2.4900, 0.0009), 7.1792),
    ((50.0000, 2.4900, -0.0010), (50.0000, -2.4900, 0.0010), 7.1792),
    ((50.0000, 2.4900, -0.0010), (50.0000, -2.4900, 0.0011), 7.2195),
    ((50.0000, 2.4900, -0.0010), (50.0000, -2.4900, 0.0012), 7.2195),
    ((50.0000, -0.0010, 2.4900), (50.0000, 0.0009, -2.4900), 4.8045),
    ((50.0000, -0.0010, 2.4900), (50.0000, 0.0010, -2.4900), 4.8045),
    ((50.0000, -0.0010, 2.4900), (50.0000, 0.0011, -2.4900), 4.7461),
    ((50.0000, 2.5000, 0.0000), (50.0000, 0.0000, -2.5000), 4.3065),
    ((50.0000, 2.5000, 0.0000), (73.0000, 25.0000, -18.0000), 27.1492),
    ((50.0000, 2.5000, 0.0000), (61.0000, -5.0000, 29.0000), 22.8977),
    ((50.0000, 2.5000, 0.0000), (56.0000, -27.0000, -3.0000), 31.9030),
    ((50.0000, 2.5000, 0.0000), (58.0000, 24.0000, 15.0000), 19.4535),
    ((50.0000, 2.5000, 0.0000), (50.0000, 3.1736, 0.5854), 1.0000),
    ((50.0000, 2.5000, 0.0000), (50.0000, 3.2972, 0.0000), 1.0000),
    ((50.0000, 2.5000, 0.0000), (50.0000, 1.8634, 0.5757), 1.0000),
    ((50.0000, 2.5000, 0.0000), (50.0000, 3.2592, 0.3350), 1.0000),
    ((60.2574, -34.0099, 36.2677), (60.4626, -34.1751, 39.4387), 1.2644),
    ((63.0109, -31.0961, -5.8663), (62.8187, -29.7946, -4.0864), 1.2630),
    ((61.2901, 3.7196, -5.3901), (61.4292, 2.2480, -4.9620), 1.8731),
    ((35.0831, -44.1164, 3.7933), (35.0232, -40.0716, 1.5901), 1.8645),
    ((22.7233, 20.0904, -46.6940), (23.0331, 14.9730, -42.5619), 2.0373),
    ((36.4612, 47.8580, 18.3852), (36.2715, 50.5065, 21.2231), 1.4146),
    ((90.8027, -2.0831, 1.4410), (91.1528, -1.6435, 0.0447), 1.4441),
    ((90.9257, -0.5406, -0.9208), (88.6381, -0.8985, -0.7239), 1.5381),
    ((6.7747, -0.2908, -2.4247), (5.8714, -0.0985, -2.2286), 0.6377),
    ((2.0776, 0.0795, -1.1350), (0.9033, -0.0636, -0.5514), 0.9082),
]


@pytest.mark.parametrize("lab1, lab2, expected", SHARMA)
def test_ciede2000_sharma_pairs(lab1, lab2, expected):
    assert delta_e_2000(lab1, lab2) == pytest.approx(expected, abs=1e-4)
    assert delta_e_2000(lab2, lab1) == pytest.approx(expected, abs=1e-4)  # symmetric


def test_ciede2000_vectorised_and_matches_coloraide():
    a = np.array([p[0] for p in SHARMA])
    b = np.array([p[1] for p in SHARMA])
    out = ciede2000(a, b)
    assert out.shape == (34,)
    assert out == pytest.approx([p[2] for p in SHARMA], abs=1e-4)
    for (l1, l2, _e), mine in zip(SHARMA[::5], out[::5]):
        ref = Color("lab-d65", list(l1)).delta_e(Color("lab-d65", list(l2)), method="2000")
        assert mine == pytest.approx(ref, abs=1e-6)


def test_negative_control_cie76_fails_the_sharma_pairs():
    """Plain Euclidean ΔE*ab would not pass the table: the pairs really discriminate."""
    wrong = [float(np.linalg.norm(np.subtract(a, b))) for a, b, _ in SHARMA]
    misses = sum(abs(w - e) > 1e-3 for w, (_a, _b, e) in zip(wrong, SHARMA))
    assert misses >= 30


# ---------------------------------------------------------------- WCAG 2.x

def test_wcag_reference_pairs():
    assert round(wcag_contrast("#777777", "#ffffff"), 2) == 4.48
    assert wcag_contrast("#000", "#fff") == pytest.approx(21.0)
    assert wcag_contrast("#fff", "#fff") == pytest.approx(1.0)
    for fg, bg in (("#777", "#fff"), ("#e63946", "#1d3557"), ("#2a9d8f", "#f4a261")):
        assert wcag_contrast(fg, bg) == pytest.approx(Color(fg).contrast(bg, method="wcag21"), abs=1e-3)


def test_wcag_thresholds_and_large_text():
    assert wcag_threshold(12) == 4.5 and wcag_threshold(18) == 3.0 and wcag_threshold(14, bold=True) == 3.0
    rep = contrast_report("#777", "#fff", font_size_pt=12)
    assert rep["passes_wcag"] is False  # 4.48 < 4.5: the famous near miss is a fail
    assert contrast_report("#767676", "#fff", font_size_pt=12)["passes_wcag"] is True


# ---------------------------------------------------------------- APCA 0.0.98G-4g

APCA_REF = [  # apca-w3 0.0.98G-4g published examples
    ("#000000", "#ffffff", 106.04067321268862),
    ("#ffffff", "#000000", -107.88473318309848),
    ("#888888", "#ffffff", 63.056469930209424),
    ("#ffffff", "#888888", -68.54146436644962),
    ("#000000", "#aaaaaa", 58.146262578561334),
    ("#aaaaaa", "#000000", -56.24113336839742),
    ("#112233", "#ddeeff", 91.66830811481631),
    ("#ddeeff", "#112233", -93.06770049484274),
    ("#112233", "#444444", 8.32326136957393),
    ("#444444", "#112233", -7.526878460278154),
]


@pytest.mark.parametrize("text, bg, lc", APCA_REF)
def test_apca_reference_pairs(text, bg, lc):
    assert apca_lc(text, bg) == pytest.approx(lc, abs=1e-6)


def test_apca_constants_are_the_published_ones():
    k = APCA_98G
    assert (k.main_trc, k.norm_bg, k.norm_txt, k.rev_txt, k.rev_bg) == (2.4, 0.56, 0.57, 0.62, 0.65)
    assert (k.blk_thrs, k.blk_clmp, k.scale_bow, k.lo_bow_offset, k.lo_clip, k.delta_y_min) == \
        (0.022, 1.414, 1.14, 0.027, 0.1, 0.0005)
    assert (k.s_r, k.s_g, k.s_b) == (0.2126729, 0.7151522, 0.0721750)


def test_apca_negative_controls():
    assert apca_lc("#123456", "#123456") == 0.0           # identical → no contrast
    assert apca_lc("#fefefe", "#ffffff") == 0.0           # under the low clip
    assert apca_lc("#000", "#fff") != pytest.approx(-apca_lc("#fff", "#000"), abs=0.5)  # polarity-aware
    # a wrong exponent (e.g. the WCAG piecewise curve) would not reproduce the reference
    from dataclasses import replace

    from mxstudio.colour.contrast import apca_lc_from_y, apca_y
    bad = replace(APCA_98G, norm_txt=0.5)
    y_t, y_b = apca_y(np.array([136, 136, 136], np.uint8)), apca_y(np.array([255, 255, 255], np.uint8))
    assert float(apca_lc_from_y(y_t, y_b, bad)) != pytest.approx(63.056, abs=0.5)
    assert apca_threshold(12) == 75.0 and apca_threshold(20) == 60.0 and apca_threshold(36) == 45.0
