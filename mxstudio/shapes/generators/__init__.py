"""Procedural shape generators (deterministic, seeded; output = editable ``a:custGeom``).

Rule: ``generate(name, seed, params)`` is a pure function - same inputs, byte-identical XML -
and refuses unknown parameters instead of silently ignoring them. Numeric parameters are
clamped to the ranges declared here (the UI reads the same table).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from . import bubbles, decor, frames, organic, patterns, scatter, sticker
from ._util import GeneratedShape, Layer, make_rng


@dataclass(frozen=True)
class GeneratorSpec:
    name: str
    fn: Callable
    label_ar: str
    label_en: str
    ranges: dict[str, tuple[float, float]] = field(default_factory=dict)
    choices: dict[str, tuple[str, ...]] = field(default_factory=dict)
    tags: tuple[str, ...] = ()

    def defaults(self) -> dict[str, Any]:
        import inspect

        sig = inspect.signature(self.fn)
        return {k: v.default for k, v in list(sig.parameters.items())[1:] if v.default is not inspect.Parameter.empty}

    def to_json(self) -> dict:
        d = self.defaults()
        return {"name": self.name, "label_ar": self.label_ar, "label_en": self.label_en, "tags": list(self.tags),
                "params": {k: {"default": _jsonable(v), "range": list(self.ranges[k]) if k in self.ranges else None,
                               "choices": list(self.choices[k]) if k in self.choices else None} for k, v in d.items()}}


def _jsonable(v):
    if isinstance(v, tuple):
        return list(v)
    return v


SIZE = (10.0, 20000.0)
REGISTRY: dict[str, GeneratorSpec] = {s.name: s for s in [
    GeneratorSpec("scalloped_frame", frames.scalloped_frame, "إطار مموّج بأقواس", "Scalloped frame",
                  {"w": SIZE, "h": SIZE, "scallop": (10, 1000), "band": (0, 2000)}, tags=("frame",)),
    GeneratorSpec("stamp_frame", frames.stamp_frame, "إطار طابع بريد", "Postage-stamp frame",
                  {"w": SIZE, "h": SIZE, "perforation": (10, 500), "notch": (0.1, 0.9), "band": (0, 2000)},
                  tags=("frame",)),
    GeneratorSpec("cloud_frame", frames.cloud_frame, "إطار سحابة", "Cloud frame",
                  {"w": SIZE, "h": SIZE, "bumps": (5, 60), "variance": (0, 1), "puff": (0, 1),
                   "hole_inset": (0.05, 0.6)}, tags=("frame",)),
    GeneratorSpec("torn_paper", frames.torn_paper, "ورق مقطوع", "Torn paper",
                  {"w": SIZE, "h": SIZE, "roughness": (0.0, 0.2), "detail": (2, 10)}, tags=("paper",)),
    GeneratorSpec("page_border", frames.page_border, "برواز صفحة بثيم", "Themed page border",
                  {"w": SIZE, "h": SIZE, "band": (10, 1000), "density": (0.2, 4)},
                  {"theme": ("sea_waves", "vines", "stars", "candy")}, tags=("border",)),
    GeneratorSpec("drop_cap_ornament", frames.drop_cap_ornament, "زخرفة الحرف الأول", "Drop-cap ornament",
                  {"w": SIZE, "h": SIZE, "flourish": (0, 1), "frame": (0.03, 0.2)},
                  {"shape": ("square", "circle")}, tags=("ornament",)),
    GeneratorSpec("mandala_frame", frames.mandala_frame, "إطار ماندالا", "Mandala frame",
                  {"w": SIZE, "h": SIZE, "symmetry": (3, 48), "rings": (1, 6), "petal": (0, 1), "hole": (0.15, 0.8)},
                  tags=("frame", "radial")),
    GeneratorSpec("blob", organic.blob, "شكل عضوي", "Organic blob",
                  {"w": SIZE, "h": SIZE, "m": (0, 20), "n1": (0.2, 20), "n2": (0.2, 20), "n3": (0.2, 20),
                   "noise": (0, 0.5), "points": (8, 200), "wobble_knots": (2, 24)}, tags=("organic",)),
    GeneratorSpec("rough_outline", organic.rough_outline, "خط مرسوم باليد", "Hand-drawn outline",
                  {"w": SIZE, "h": SIZE, "sides": (3, 24), "roughness": (0, 4), "bowing": (0, 6), "strokes": (1, 4),
                   "curve_steps": (6, 40)}, {"base": ("rect", "ellipse", "polygon")}, tags=("hand-drawn",)),
    GeneratorSpec("speech_bubble", bubbles.speech_bubble, "فقاعة كلام", "Speech bubble",
                  {"page_w": SIZE, "page_h": SIZE, "tail_width": (0.05, 0.6), "gap": (0, 1000), "curve": (-0.5, 0.5),
                   "corner": (0, 0.5)}, {"kind": ("ellipse", "roundrect", "rect")}, tags=("bubble",)),
    GeneratorSpec("thought_bubble", bubbles.thought_bubble, "فقاعة تفكير", "Thought bubble",
                  {"page_w": SIZE, "page_h": SIZE, "bumps": (5, 40), "trail": (1, 6), "gap": (0, 1000)},
                  tags=("bubble",)),
    GeneratorSpec("ribbon_banner", decor.ribbon_banner, "شريط لافتة", "Ribbon banner",
                  {"w": SIZE, "h": SIZE, "tail": (0.05, 0.3), "notch": (0, 0.9), "fold": (0, 0.15), "band": (0.4, 0.9),
                   "arch": (-0.5, 0.5)}, tags=("banner",)),
    GeneratorSpec("rosette_badge", decor.rosette_badge, "وسام", "Rosette badge",
                  {"w": SIZE, "points": (8, 80), "ring": (0.05, 0.5)}, tags=("badge",)),
    GeneratorSpec("rainbow", decor.rainbow, "قوس قزح", "Rainbow",
                  {"w": SIZE, "bands": (1, 12), "inner": (0.05, 0.9), "gap": (0, 0.8)}, tags=("rainbow",)),
    GeneratorSpec("wave_divider", decor.wave_divider, "فاصل أمواج", "Wave divider",
                  {"w": SIZE, "h": SIZE, "waves": (0.5, 30), "amplitude": (0, 1), "layers": (1, 5),
                   "phase_shift": (0, 1)}, tags=("divider",)),
    GeneratorSpec("confetti_scatter", scatter.confetti_scatter, "قصاصات ونجوم متناثرة", "Confetti / star scatter",
                  {"w": SIZE, "h": SIZE, "radius": (10, 2000), "size": (4, 500), "colors": (1, 8), "margin": (0, 500)},
                  tags=("scatter",)),
    GeneratorSpec("pattern_fill", patterns.pattern_fill, "نقشة تعبئة", "Pattern fill",
                  {"w": SIZE, "h": SIZE, "spacing": (8, 2000), "size": (0.05, 0.8), "angle": (-180, 180)},
                  {"kind": ("dots", "stripes", "checks", "hearts")}, tags=("pattern",)),
    GeneratorSpec("sticker_outline", sticker.sticker_outline, "حدّ قص الملصق", "Die-cut sticker outline",
                  {"w": SIZE, "h": SIZE, "offset_by": (1, 500)}, tags=("sticker",)),
]}

_OPAQUE = {"source", "mask", "keepouts", "semantic_map", "region", "body", "anchor", "edges"}


def list_generators() -> list[dict]:
    return [s.to_json() for s in REGISTRY.values()]


def validate_params(name: str, params: dict | None) -> dict:
    spec = REGISTRY.get(name)
    if spec is None:
        raise KeyError(f"unknown generator {name!r}")
    defaults = spec.defaults()
    params = dict(params or {})
    unknown = set(params) - set(defaults)
    if unknown:
        raise ValueError(f"{name}: unknown parameter(s) {sorted(unknown)}")
    out = dict(defaults)
    for k, v in params.items():
        d = defaults[k]
        if k in spec.choices:
            if v not in spec.choices[k]:
                raise ValueError(f"{name}.{k} must be one of {spec.choices[k]}")
            out[k] = v
        elif k in _OPAQUE:
            out[k] = v
        elif isinstance(d, bool):
            out[k] = bool(v)
        elif isinstance(d, int) and not isinstance(d, bool):
            lo, hi = spec.ranges.get(k, (-1e9, 1e9))
            out[k] = int(max(lo, min(hi, int(round(float(v))))))
        elif isinstance(d, float):
            lo, hi = spec.ranges.get(k, (-1e9, 1e9))
            fv = float(v)
            if fv != fv:
                raise ValueError(f"{name}.{k} is NaN")
            out[k] = max(lo, min(hi, fv))
        else:
            out[k] = v
    return out


def generate(name: str, seed: int = 0, params: dict | None = None) -> GeneratedShape:
    """Run generator ``name`` with ``seed``; returns layers + facts (``meta``)."""
    values = validate_params(name, params)
    rng = make_rng(name, int(seed))
    layers, meta = REGISTRY[name].fn(rng, **values)
    shown = {k: _jsonable(v) for k, v in values.items() if k not in ("mask",)}
    return GeneratedShape(name, int(seed), shown, layers, meta)


__all__ = ["GeneratedShape", "GeneratorSpec", "Layer", "REGISTRY", "generate", "list_generators", "validate_params"]
