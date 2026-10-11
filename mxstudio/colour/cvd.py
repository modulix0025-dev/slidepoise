"""Colour-vision-deficiency simulation (Machado, Oliveira & Fernandes 2009).

Rule: meaning is never carried by colour alone. This module simulates protan, deutan and
tritan vision with the published Machado 2009 matrices (applied to linear sRGB, severity
0..1 by linear interpolation between the published 0.1 steps) and checks a set of
colour-coded meanings: if two meanings become indistinguishable for any simulated viewer
*and* the page declares no other cue (shape, icon, label, pattern, position), that is an
objective, blocking finding. Previews of whole images are offered for the operator.

Source of the matrices: G. M. Machado, M. M. Oliveira, L. A. F. Fernandes, "A
Physiologically-based Model for Simulation of Color Vision Deficiency", IEEE TVCG 15(6),
2009 — supplementary table at inf.ufrgs.br/~oliveira/pubs_files/CVD_Simulation.
"""
from __future__ import annotations

from itertools import combinations
from typing import Iterable, Mapping

import numpy as np

from .oklch import ColourLike, as_float_rgb, linear_to_srgb, parse_rgb, srgb_array_to_oklab, srgb_to_linear, to_hex

_I = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]

MACHADO = {
    "protan": [
        _I,
        [[0.856167, 0.182038, -0.038205], [0.029342, 0.955115, 0.015544], [-0.002880, -0.001563, 1.004443]],
        [[0.734766, 0.334872, -0.069637], [0.051840, 0.919198, 0.028963], [-0.004928, -0.004209, 1.009137]],
        [[0.630323, 0.465641, -0.095964], [0.069181, 0.890046, 0.040773], [-0.006308, -0.007724, 1.014032]],
        [[0.539009, 0.579343, -0.118352], [0.082546, 0.866121, 0.051332], [-0.007136, -0.011959, 1.019095]],
        [[0.458064, 0.679578, -0.137642], [0.092785, 0.846313, 0.060902], [-0.007494, -0.016807, 1.024301]],
        [[0.385450, 0.769005, -0.154455], [0.100526, 0.829802, 0.069673], [-0.007442, -0.022190, 1.029632]],
        [[0.319627, 0.849633, -0.169261], [0.106241, 0.815969, 0.077790], [-0.007025, -0.028051, 1.035076]],
        [[0.259411, 0.923008, -0.182420], [0.110296, 0.804340, 0.085364], [-0.006276, -0.034346, 1.040622]],
        [[0.203876, 0.990338, -0.194214], [0.112975, 0.794542, 0.092483], [-0.005222, -0.041043, 1.046265]],
        [[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216], [-0.003882, -0.048116, 1.051998]],
    ],
    "deutan": [
        _I,
        [[0.866435, 0.177704, -0.044139], [0.049567, 0.939063, 0.011370], [-0.003453, 0.007233, 0.996220]],
        [[0.760729, 0.319078, -0.079807], [0.090568, 0.889315, 0.020117], [-0.006027, 0.013325, 0.992702]],
        [[0.675425, 0.433850, -0.109275], [0.125303, 0.847755, 0.026942], [-0.007950, 0.018572, 0.989378]],
        [[0.605511, 0.528560, -0.134071], [0.155318, 0.812366, 0.032316], [-0.009376, 0.023176, 0.986200]],
        [[0.547494, 0.607765, -0.155259], [0.181692, 0.781742, 0.036566], [-0.010410, 0.027275, 0.983136]],
        [[0.498864, 0.674741, -0.173604], [0.205199, 0.754872, 0.039929], [-0.011131, 0.030969, 0.980162]],
        [[0.457771, 0.731899, -0.189670], [0.226409, 0.731012, 0.042579], [-0.011595, 0.034333, 0.977261]],
        [[0.422823, 0.781057, -0.203881], [0.245752, 0.709602, 0.044646], [-0.011843, 0.037423, 0.974421]],
        [[0.392952, 0.823610, -0.216562], [0.263559, 0.690210, 0.046232], [-0.011910, 0.040281, 0.971630]],
        [[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413], [-0.011820, 0.042940, 0.968881]],
    ],
    "tritan": [
        _I,
        [[0.926670, 0.092514, -0.019184], [0.021191, 0.964503, 0.014306], [0.008437, 0.054813, 0.936750]],
        [[0.895720, 0.133330, -0.029050], [0.029997, 0.945400, 0.024603], [0.013027, 0.104707, 0.882266]],
        [[0.905871, 0.127791, -0.033662], [0.026856, 0.941251, 0.031893], [0.013410, 0.148296, 0.838294]],
        [[0.948035, 0.089490, -0.037526], [0.014364, 0.946792, 0.038844], [0.010853, 0.193991, 0.795156]],
        [[1.017277, 0.027029, -0.044306], [-0.006113, 0.958479, 0.047634], [0.006379, 0.248708, 0.744913]],
        [[1.104996, -0.046633, -0.058363], [-0.032137, 0.971635, 0.060503], [0.001336, 0.317922, 0.680742]],
        [[1.193214, -0.109812, -0.083402], [-0.058496, 0.979410, 0.079086], [-0.002346, 0.403492, 0.598854]],
        [[1.257728, -0.139648, -0.118081], [-0.078003, 0.975409, 0.102594], [-0.003316, 0.501214, 0.502102]],
        [[1.278864, -0.125333, -0.153531], [-0.084748, 0.957674, 0.127074], [-0.000989, 0.601151, 0.399838]],
        [[1.255528, -0.076749, -0.178779], [-0.078411, 0.930809, 0.147602], [0.004733, 0.691367, 0.303900]],
    ],
}
KINDS = tuple(MACHADO)
ALIASES = {"protanopia": "protan", "deuteranopia": "deutan", "tritanopia": "tritan"}
DISTINCT_MIN_OK = 0.06  # OKLab ΔE between meanings after simulation (≈ 3 JND)
OTHER_CUES = {"shape", "icon", "label", "pattern", "position", "text", "size", "outline"}


def machado_matrix(kind: str, severity: float = 1.0) -> np.ndarray:
    kind = ALIASES.get(kind, kind)
    if kind not in MACHADO:
        raise ValueError(f"unknown deficiency {kind!r}; use one of {KINDS}")
    if not 0.0 <= severity <= 1.0:
        raise ValueError("severity must be within 0..1")
    s = severity * 10.0
    lo = int(np.floor(s))
    m_lo = np.array(MACHADO[kind][lo])
    if lo >= 10 or s == lo:
        return m_lo
    m_hi = np.array(MACHADO[kind][lo + 1])
    return m_lo + (m_hi - m_lo) * (s - lo)


def simulate_linear(pixels, kind: str, severity: float = 1.0) -> np.ndarray:
    """Linear-sRGB result, *unclipped* (useful for known-answer comparisons)."""
    lin = srgb_to_linear(as_float_rgb(np.asarray(pixels)))
    return lin @ machado_matrix(kind, severity).T


def simulate(pixels, kind: str, severity: float = 1.0) -> np.ndarray:
    """sRGB uint8 in → simulated sRGB uint8 out (gamut-clipped). Works on any (…, 3) array."""
    arr = np.asarray(pixels)
    out = linear_to_srgb(simulate_linear(arr, kind, severity))
    return (out * 255.0 + 0.5).astype(np.uint8)


def simulate_colour(colour: ColourLike, kind: str, severity: float = 1.0) -> str:
    return to_hex(tuple(int(v) for v in simulate(np.array(parse_rgb(colour), dtype=np.uint8), kind, severity)))


def simulate_image(path_or_array, kind: str, severity: float = 1.0):
    """Preview for the operator: returns a PIL image."""
    from PIL import Image

    from .extract import load_rgba

    rgba = load_rgba(path_or_array)
    rgb = simulate(rgba[..., :3], kind, severity)
    return Image.fromarray(np.concatenate([rgb, rgba[..., 3:]], axis=-1), "RGBA")


def check_colour_meanings(meanings: Mapping[str, ColourLike], cues: Mapping[str, Iterable[str]] | None = None,
                          kinds: Iterable[str] = KINDS, severity: float = 1.0,
                          min_delta: float = DISTINCT_MIN_OK) -> dict:
    """Do colour-coded meanings stay distinct for every simulated viewer?

    ``meanings``: {"correct answer": "#2a9d8f", "wrong answer": "#e63946", …}.
    ``cues``: non-colour cues per meaning ({"correct answer": ["icon"]}). A pair that
    collapses is blocking only when *neither* meaning carries a cue from ``OTHER_CUES``.
    """
    cues = {k: {c for c in v if c in OTHER_CUES} for k, v in (cues or {}).items()}
    names = list(meanings)
    rgb = np.array([parse_rgb(meanings[n]) for n in names], dtype=np.uint8)
    pairs = []
    for kind in ("normal", *kinds):
        sim = rgb if kind == "normal" else simulate(rgb, kind, severity)
        lab = srgb_array_to_oklab(sim)
        for i, j in combinations(range(len(names)), 2):
            d = float(np.linalg.norm(lab[i] - lab[j]))
            if d < min_delta:
                covered = bool(cues.get(names[i]) or cues.get(names[j]))
                pairs.append({"vision": kind, "a": names[i], "b": names[j], "delta_e_ok": round(d, 4),
                              "other_cue": covered, "blocking": not covered})
    blocking = [p for p in pairs if p["blocking"]]
    return {
        "finding": "meaning_by_colour_alone" if blocking else None,
        "blocking": bool(blocking),
        "collapsed_pairs": pairs,
        "min_delta_e_ok": min_delta,
        "severity": severity,
        "ar": "فيه معنيين بيتفرّقوا باللون بس ومش هيبانوا لطفل عنده عمى ألوان — زوّد شكل أو أيقونة أو كلمة."
        if blocking else "",
        "en": "Two meanings are told apart by colour alone and collapse for a colour-blind reader — add a shape, "
              "icon or label." if blocking else "",
    }
