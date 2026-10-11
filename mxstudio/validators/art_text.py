"""Evidence that generated art drew letters inside a text slot.

Rule (brief §6.1.8): image models draw Arabic badly, so generated targets must
leave text zones as empty treatments and every word is rebuilt as native text.
This check measures each text slot with OpenCV and reports facts — edge density,
small connected components, and how many of them sit on shared baselines. When
those facts look like a line of glyphs it raises a *named blocking finding* so
the target goes back for regeneration. It never judges beauty; the host Agent's
visual review still looks at every target.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import cv2
import numpy as np

FINDING = "glyph_like_marks_in_text_slot"


@dataclass
class SlotEvidence:
    slot_id: str
    box_px: tuple[int, int, int, int]
    edge_density: float
    components: int
    baseline_aligned: float
    blocking: bool

    def as_dict(self) -> dict:
        return {**asdict(self), "finding": FINDING if self.blocking else None}


def _components(binary: np.ndarray, slot_area: int) -> list[tuple[float, float, int, int]]:
    count, _labels, stats, centroids = cv2.connectedComponentsWithStats(binary, connectivity=8)
    out = []
    for index in range(1, count):
        x, y, w, h, area = stats[index]
        if not (slot_area * 0.00005 <= area <= slot_area * 0.03):
            continue
        if w > binary.shape[1] * 0.5 or h > binary.shape[0] * 0.6:
            continue
        out.append((float(centroids[index][0]), float(centroids[index][1]), int(w), int(h)))
    return out


def _baseline_share(components: list[tuple[float, float, int, int]], height: int) -> float:
    if len(components) < 3:
        return 0.0
    bins = max(4, height // 12)
    histogram, _ = np.histogram([c[1] for c in components], bins=bins, range=(0, height))
    top = np.sort(histogram)[::-1][:3].sum()
    return float(top) / len(components)


def inspect_slot(image: np.ndarray, box_px: tuple[int, int, int, int], slot_id: str = "slot",
                 min_components: int = 8, min_edge_density: float = 0.03, min_alignment: float = 0.5) -> SlotEvidence:
    x, y, w, h = (int(round(v)) for v in box_px)
    crop = image[max(0, y):y + h, max(0, x):x + w]
    if crop.size == 0:
        raise ValueError(f"slot {slot_id} lies outside the image")
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    edges = cv2.Canny(cv2.GaussianBlur(gray, (3, 3), 0), 60, 160)
    edge_density = float(np.count_nonzero(edges)) / edges.size
    _, dark = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    _, light = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    area = gray.shape[0] * gray.shape[1]
    contrast = float(gray.max()) - float(gray.min())
    candidates = []
    if contrast >= 40:  # a flat or softly graded treatment has no glyph contrast to binarise
        candidates = max((_components(dark, area), _components(light, area)), key=len)
    alignment = _baseline_share(candidates, gray.shape[0])
    blocking = (len(candidates) >= min_components and edge_density >= min_edge_density
                and alignment >= min_alignment)
    return SlotEvidence(slot_id, (x, y, w, h), round(edge_density, 4), len(candidates), round(alignment, 3), blocking)


def inspect_target(path_or_image, slots: dict[str, tuple[int, int, int, int]]) -> list[dict]:
    image = cv2.imread(str(path_or_image), cv2.IMREAD_COLOR) if not isinstance(path_or_image, np.ndarray) \
        else path_or_image
    if image is None:
        raise FileNotFoundError(path_or_image)
    return [inspect_slot(image, box, slot_id).as_dict() for slot_id, box in slots.items()]
