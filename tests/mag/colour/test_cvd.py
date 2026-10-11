"""Machado 2009 colour-vision simulation and the "meaning never by colour alone" check."""
from __future__ import annotations

import numpy as np
import pytest
from coloraide import Color

from mxstudio.colour.cvd import (check_colour_meanings, machado_matrix, simulate, simulate_colour, simulate_image,
                                 simulate_linear)

# Machado et al. 2009, supplementary table, severity 1.0.
SEVERE = {
    "protan": [[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216], [-0.003882, -0.048116, 1.051998]],
    "deutan": [[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413], [-0.011820, 0.042940, 0.968881]],
    "tritan": [[1.255528, -0.076749, -0.178779], [-0.078411, 0.930809, 0.147602], [0.004733, 0.691367, 0.303900]],
}


@pytest.mark.parametrize("kind", SEVERE)
def test_severity_one_matrices_are_the_published_ones(kind):
    assert np.allclose(machado_matrix(kind, 1.0), SEVERE[kind], atol=1e-9)
    assert np.allclose(machado_matrix(kind, 0.0), np.eye(3))


def test_pure_red_under_protanopia_fixture():
    lin = simulate_linear(np.array([255, 0, 0], np.uint8), "protan", 1.0)
    assert lin == pytest.approx([0.152286, 0.114503, -0.003882], abs=1e-6)  # first matrix column
    assert simulate_colour("#ff0000", "protanopia") == "#6d5f00"          # dark olive, clipped to sRGB
    assert simulate_colour("#ff0000", "deutan") == "#a39000"


@pytest.mark.parametrize("kind", ["protan", "deutan", "tritan"])
@pytest.mark.parametrize("severity", [1.0, 0.55, 0.3])
def test_matches_coloraide_machado(kind, severity):
    for hx in ("#ff0000", "#00ff00", "#3366cc", "#a1b2c3", "#e0ac69"):
        mine = simulate_linear(np.array(Color(hx).convert("srgb").coords()), kind, severity)
        ref = Color(hx).filter(kind, severity, method="machado").convert("srgb-linear").coords()
        assert mine == pytest.approx(ref, abs=1e-6)


def test_image_simulation_keeps_alpha_and_shape():
    rgba = np.zeros((4, 5, 4), np.uint8)
    rgba[..., 0] = 255
    rgba[..., 3] = 128
    out = np.asarray(simulate_image(rgba, "deutan"))
    assert out.shape == (4, 5, 4) and (out[..., 3] == 128).all()
    assert tuple(out[0, 0, :3]) == tuple(simulate(np.array([255, 0, 0], np.uint8), "deutan"))


def test_red_green_meaning_collapses_for_deuteranopes_and_blocks():
    report = check_colour_meanings({"correct": "#2ca02c", "wrong": "#d62728"})
    assert report["blocking"] and report["finding"] == "meaning_by_colour_alone"
    visions = {p["vision"] for p in report["collapsed_pairs"]}
    assert "deutan" in visions and "normal" not in visions
    assert report["ar"] and report["en"]


def test_redundant_cue_lifts_the_block_but_keeps_the_fact():
    report = check_colour_meanings({"correct": "#2ca02c", "wrong": "#d62728"}, cues={"correct": ["icon"]})
    assert not report["blocking"] and report["collapsed_pairs"]
    assert all(p["other_cue"] for p in report["collapsed_pairs"])


def test_negative_control_blue_orange_stays_distinct():
    report = check_colour_meanings({"correct": "#1f77b4", "wrong": "#ff7f0e"})
    assert not report["blocking"] and report["collapsed_pairs"] == []


def test_bad_inputs_are_refused():
    with pytest.raises(ValueError):
        machado_matrix("achromat")
    with pytest.raises(ValueError):
        machado_matrix("protan", 1.2)
    # a cue that is not a real non-colour cue does not count
    report = check_colour_meanings({"a": "#2ca02c", "b": "#d62728"}, cues={"a": ["different shade"]})
    assert report["blocking"]
