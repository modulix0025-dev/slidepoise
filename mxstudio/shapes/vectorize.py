"""Raster -> vector -> ``a:custGeom`` with vtracer (MIT; potrace is GPL and is not used).

Rule: the image is first reduced to a silhouette (alpha, else dark-on-light), traced as splines,
sanitised like any outside SVG, then simplified: speckles below ``min_area_ratio`` of the frame
are dropped and the node count is capped (re-traced with stronger filtering when over the cap).
The output is a *candidate*; it enters the library only after operator approval.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from .boolean import area
from .custgeom import CustomGeometry, GeomPart
from .raster import iou, mask_from_png, rasterize_geometry
from .sanitize import SvgRejected
from .svg_convert import svg_to_shapes


@dataclass
class VectorResult:
    geometry: CustomGeometry
    svg: str
    node_count: int
    iou_vs_input: float
    findings: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return {"geometry": self.geometry.to_json(), "custgeom": self.geometry.to_xml(), "node_count": self.node_count,
                "iou_vs_input": round(self.iou_vs_input, 4), "findings": self.findings}


def silhouette_png(image: bytes, threshold: int = 128, max_side: int = 1024) -> tuple[bytes, np.ndarray]:
    mask = mask_from_png(image, threshold)
    h, w = mask.shape
    s = min(1.0, max_side / max(h, w))
    if s < 1.0:
        mask = (cv2.resize(mask * 255, (max(1, round(w * s)), max(1, round(h * s))),
                           interpolation=cv2.INTER_AREA) >= 128).astype(np.uint8)
    img = np.where(mask[..., None] > 0, 0, 255).astype(np.uint8).repeat(3, axis=2)
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise ValueError("could not encode silhouette")
    return buf.tobytes(), mask


def _trace(png: bytes, speckle: int, corner: int, length: float) -> str:
    import vtracer

    return vtracer.convert_raw_image_to_svg(png, img_format="png", colormode="binary", mode="spline",
                                            filter_speckle=int(speckle), corner_threshold=int(corner),
                                            length_threshold=float(length), splice_threshold=45, path_precision=3)


def vectorize_image(image: bytes, *, max_nodes: int = 1500, min_area_ratio: float = 0.0004,
                    threshold: int = 128) -> VectorResult:
    """Trace ``image`` (PNG/JPEG bytes) into one single-colour custGeom silhouette."""
    png, mask = silhouette_png(image, threshold)
    if mask.sum() == 0:
        raise ValueError("the image has no foreground to trace")
    findings: list[str] = []
    speckle, corner, length = 4, 60, 4.0
    best: tuple[CustomGeometry, str] | None = None
    for attempt in range(5):
        svg = _trace(png, speckle, corner, length)
        try:
            conv = svg_to_shapes(svg)
        except SvgRejected:
            findings.append(f"retrace_{attempt + 1}_empty")
            break
        frame = conv.width * conv.height
        parts = []
        for shape in conv.shapes:
            if shape.fill is None:
                continue
            for part in shape.geometry.parts:
                if area(part.path, tol=0.5) >= min_area_ratio * frame:
                    parts.append(GeomPart(part.path))
                else:
                    findings.append("speckle_dropped")
        if not parts:
            findings.append(f"retrace_{attempt + 1}_empty")
            break
        best = (CustomGeometry(conv.width, conv.height, parts), svg)
        nodes = best[0].node_count()
        if nodes <= max_nodes:
            break
        findings.append(f"retrace_{attempt + 1}_nodes_{nodes}")
        speckle, corner, length = speckle * 2, min(180, corner + 30), length * 2
    if best is None:
        raise ValueError("tracing produced no geometry")
    geom, svg = best
    if geom.node_count() > max_nodes:
        findings.append("node_cap_exceeded")
    got = rasterize_geometry(geom, mask.shape[1], mask.shape[0])
    score = iou(got, mask)
    return VectorResult(geom, svg, geom.node_count(), score, sorted(set(findings)))
