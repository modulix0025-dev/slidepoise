"""Palette extraction from accepted art: area-weighted k-means in OKLab.

Rule: frames, shapes and text colours should come *from* the illustration. This module
measures which colours cover how much of the accepted art. Pixels are split first into
three groups that must not compete with each other:

* near-neutrals (OKLCH C below a threshold: paper white, greys, ink black);
* skin (a host-supplied mask when given — e.g. the character layer — otherwise an
  OKLCH range heuristic, reported as such because sand, wood and caramel overlap it);
* chromatic colours (everything else) — the candidates for deck roles.

Each group is clustered separately with deterministic, area-weighted k-means in OKLab
(k-means++ seeding from a fixed seed). Each cluster reports its centroid *and* its
medoid — the most frequent real colour in the cluster — so a role colour can be a colour
that actually appears in the art.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .oklch import oklab_array_to_srgb, oklab_to_oklch_array, srgb_array_to_oklab, to_hex

NEUTRAL_CHROMA = 0.035
SKIN_RANGE = {"h_min": 20.0, "h_max": 80.0, "c_min": 0.03, "c_max": 0.13, "l_min": 0.28, "l_max": 0.94}


def load_rgba(source: Any) -> np.ndarray:
    """Path / PIL image / numpy array (RGB or RGBA, *RGB order*) → uint8 RGBA array."""
    if isinstance(source, (str, Path)):
        with Image.open(Path(source)) as im:
            return np.asarray(im.convert("RGBA")).copy()
    if isinstance(source, Image.Image):
        return np.asarray(source.convert("RGBA")).copy()
    arr = np.asarray(source)
    if arr.ndim == 2:
        arr = np.stack([arr] * 3, axis=-1)
    if arr.dtype != np.uint8:
        arr = (np.clip(arr.astype(np.float64), 0, 1) * 255 + 0.5).astype(np.uint8)
    if arr.shape[-1] == 3:
        arr = np.concatenate([arr, np.full(arr.shape[:-1] + (1,), 255, np.uint8)], axis=-1)
    return arr


def _weighted_kmeans(points: np.ndarray, weights: np.ndarray, k: int, seed: int,
                     iterations: int = 40) -> tuple[np.ndarray, np.ndarray]:
    """Lloyd's algorithm with k-means++ seeding; deterministic for a given seed."""
    rng = np.random.default_rng(seed)
    k = max(1, min(k, len(points)))
    w = weights / weights.sum()
    centres = [points[int(np.argmax(weights))]]
    for _ in range(1, k):
        d2 = np.min(((points[:, None, :] - np.array(centres)[None, :, :]) ** 2).sum(-1), axis=1)
        p = d2 * w
        if p.sum() <= 0:
            break
        centres.append(points[rng.choice(len(points), p=p / p.sum())])
    centres = np.array(centres)
    labels = np.zeros(len(points), dtype=int)
    for _ in range(iterations):
        d2 = ((points[:, None, :] - centres[None, :, :]) ** 2).sum(-1)
        new_labels = np.argmin(d2, axis=1)
        new_centres = np.array([
            np.average(points[new_labels == j], axis=0, weights=weights[new_labels == j])
            if np.any(new_labels == j) else centres[j] for j in range(len(centres))])
        if np.array_equal(new_labels, labels) and np.allclose(new_centres, centres):
            break
        labels, centres = new_labels, new_centres
    return centres, labels


def _bins(lab: np.ndarray, step: float = 0.008) -> tuple[np.ndarray, np.ndarray]:
    """Collapse pixels to an OKLab grid: unique bin centres + pixel counts (the area weights)."""
    keys = np.round(lab / step).astype(np.int64)
    uniq, inverse, counts = np.unique(keys, axis=0, return_inverse=True, return_counts=True)
    sums = np.zeros((len(uniq), 3))
    np.add.at(sums, inverse.reshape(-1), lab)
    return sums / counts[:, None], counts.astype(np.float64)


def _cluster_group(lab: np.ndarray, k: int, total: int, seed: int) -> list[dict]:
    if len(lab) == 0:
        return []
    points, weights = _bins(lab)
    centres, labels = _weighted_kmeans(points, weights, k, seed)
    out = []
    for j, centre in enumerate(centres):
        sel = labels == j
        if not np.any(sel):
            continue
        area = float(weights[sel].sum())
        medoid = points[sel][int(np.argmax(weights[sel]))]
        mean_rgb = oklab_array_to_srgb(centre[None, :])[0]
        med_rgb = oklab_array_to_srgb(medoid[None, :])[0]
        L, C, h = oklab_to_oklch_array(medoid[None, :])[0]
        out.append({
            "hex": to_hex(tuple(int(round(v * 255)) for v in med_rgb)),
            "mean_hex": to_hex(tuple(int(round(v * 255)) for v in mean_rgb)),
            "oklch": [round(float(L), 4), round(float(C), 4), round(float(h), 2)],
            "area": round(area / total, 5),
        })
    return sorted(out, key=lambda c: -c["area"])


def skin_heuristic(oklch: np.ndarray, rng: dict | None = None) -> np.ndarray:
    r = rng or SKIN_RANGE
    L, C, h = oklch[..., 0], oklch[..., 1], oklch[..., 2]
    return ((h >= r["h_min"]) & (h <= r["h_max"]) & (C >= r["c_min"]) & (C <= r["c_max"])
            & (L >= r["l_min"]) & (L <= r["l_max"]))


def extract_palette(image: Any, k: int = 6, skin_mask: np.ndarray | None = None, detect_skin: bool = True,
                    neutral_chroma: float = NEUTRAL_CHROMA, max_pixels: int = 160_000, seed: int = 7,
                    alpha_min: int = 128) -> dict:
    """Area-weighted palette of ``image``.

    ``skin_mask``: optional boolean array (H, W) supplied by the host (e.g. the character
    cut-out); it wins over the heuristic. Fully transparent pixels are ignored.
    """
    rgba = load_rgba(image)
    h, w = rgba.shape[:2]
    opaque = rgba[..., 3] >= alpha_min
    skin_src = "off"
    skin_px = np.zeros((h, w), bool)
    if skin_mask is not None:
        skin_mask = np.asarray(skin_mask, bool)
        if skin_mask.shape != (h, w):
            raise ValueError("skin_mask must have the image's (height, width)")
        skin_px, skin_src = skin_mask, "mask"
    stride = max(1, int(np.ceil(np.sqrt(h * w / max_pixels))))
    sub = (slice(None, None, stride), slice(None, None, stride))
    rgb = rgba[sub][..., :3].reshape(-1, 3)
    keep = opaque[sub].reshape(-1)
    skin_flat = skin_px[sub].reshape(-1)
    rgb, skin_flat = rgb[keep], skin_flat[keep]
    total = len(rgb)
    if total == 0:
        return {"colours": [], "skin": [], "neutrals": [], "pixels": 0, "skin_source": skin_src,
                "fractions": {"chromatic": 0.0, "skin": 0.0, "neutral": 0.0}}
    lab = srgb_array_to_oklab(rgb)
    lch = oklab_to_oklch_array(lab)
    neutral = lch[:, 1] < neutral_chroma
    if skin_src == "off" and detect_skin:
        skin_flat, skin_src = skin_heuristic(lch), "heuristic"
    skin = skin_flat & ~neutral
    chroma = ~neutral & ~skin
    return {
        "colours": _cluster_group(lab[chroma], k, total, seed),
        "skin": _cluster_group(lab[skin], 2, total, seed),
        "neutrals": _cluster_group(lab[neutral], 3, total, seed),
        "pixels": int(total),
        "sample_stride": stride,
        "skin_source": skin_src,
        "fractions": {"chromatic": round(float(chroma.mean()), 5), "skin": round(float(skin.mean()), 5),
                      "neutral": round(float(neutral.mean()), 5)},
        "method": "area-weighted k-means in OKLab, k-means++ seed=%d" % seed,
    }
