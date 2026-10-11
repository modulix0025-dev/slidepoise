"""Preset text warps (``a:prstTxWarp``, WordArt transforms).

Rule: the canonical list is ECMA-376 Part 1 ``ST_TextShapeType`` (20.1.10.76, 41 values),
embedded as data. Adjust defaults are the ``avLst`` of presetTextWarpDefinitions.xml
(``cd2`` = 10800000), checked on 2026-10-11 against LibreOffice/core
``oox/source/export/presetTextWarpDefinitions.xml`` (sha256 3948968d...c391, read from GitHub;
not shipped). Rendering of every warp in PowerPoint is pending on-device proof
(docs/mag/phase-5/PHASE_5_NOTES.md).
"""
from __future__ import annotations

from dataclasses import dataclass
from xml.sax.saxutils import escape

from .custgeom import A_NS

ECMA_TEXT_WARPS: tuple[str, ...] = (
    "textNoShape", "textPlain", "textStop", "textTriangle", "textTriangleInverted", "textChevron",
    "textChevronInverted", "textRingInside", "textRingOutside", "textArchUp", "textArchDown",
    "textCircle", "textButton", "textArchUpPour", "textArchDownPour", "textCirclePour",
    "textButtonPour", "textCurveUp", "textCurveDown", "textCanUp", "textCanDown", "textWave1",
    "textWave2", "textDoubleWave1", "textWave4", "textInflate", "textDeflate", "textInflateBottom",
    "textDeflateBottom", "textInflateTop", "textDeflateTop", "textDeflateInflate",
    "textDeflateInflateDeflate", "textFadeRight", "textFadeLeft", "textFadeUp", "textFadeDown",
    "textSlantUp", "textSlantDown", "textCascadeUp", "textCascadeDown",
)

_DEFAULTS: dict[str, tuple[tuple[str, int], ...]] = {
    "textNoShape": (),
    "textPlain": (("adj", 50000),),
    "textStop": (("adj", 25000),),
    "textTriangle": (("adj", 50000),),
    "textTriangleInverted": (("adj", 50000),),
    "textChevron": (("adj", 25000),),
    "textChevronInverted": (("adj", 75000),),
    "textRingInside": (("adj", 60000),),
    "textRingOutside": (("adj", 60000),),
    "textArchUp": (("adj", 10800000),),
    "textArchDown": (("adj", 0),),
    "textCircle": (("adj", 10800000),),
    "textButton": (("adj", 10800000),),
    "textArchUpPour": (("adj1", 10800000), ("adj2", 50000)),
    "textArchDownPour": (("adj1", 0), ("adj2", 25000)),
    "textCirclePour": (("adj1", 10800000), ("adj2", 50000)),
    "textButtonPour": (("adj1", 10800000), ("adj2", 50000)),
    "textCurveUp": (("adj", 45977),),
    "textCurveDown": (("adj", 45977),),
    "textCanUp": (("adj", 85714),),
    "textCanDown": (("adj", 14286),),
    "textWave1": (("adj1", 12500), ("adj2", 0)),
    "textWave2": (("adj1", 12500), ("adj2", 0)),
    "textDoubleWave1": (("adj1", 6250), ("adj2", 0)),
    "textWave4": (("adj1", 6250), ("adj2", 0)),
    "textInflate": (("adj", 18750),),
    "textDeflate": (("adj", 18750),),
    "textInflateBottom": (("adj", 60000),),
    "textDeflateBottom": (("adj", 50000),),
    "textInflateTop": (("adj", 40000),),
    "textDeflateTop": (("adj", 50000),),
    "textDeflateInflate": (("adj", 35000),),
    "textDeflateInflateDeflate": (("adj", 25000),),
    "textFadeRight": (("adj", 33333),),
    "textFadeLeft": (("adj", 33333),),
    "textFadeUp": (("adj", 33333),),
    "textFadeDown": (("adj", 33333),),
    "textSlantUp": (("adj", 55555),),
    "textSlantDown": (("adj", 44445),),
    "textCascadeUp": (("adj", 44444),),
    "textCascadeDown": (("adj", 44444),),
}

_ANGLE = {("textArchUp", "adj"), ("textArchDown", "adj"), ("textCircle", "adj"), ("textButton", "adj"),
          ("textArchUpPour", "adj1"), ("textArchDownPour", "adj1"), ("textCirclePour", "adj1"),
          ("textButtonPour", "adj1")}

GROUPS = {
    "arch": ("أقواس ودوائر", "Arches and circles"),
    "wave": ("أمواج", "Waves"),
    "inflate": ("انتفاخ وانكماش", "Inflate and deflate"),
    "perspective": ("منظور وميل", "Perspective and slant"),
    "basic": ("أساسي", "Basic"),
}


def group_of(name: str) -> str:
    if any(k in name for k in ("Arch", "Circle", "Button", "Ring", "Curve", "Can")):
        return "arch"
    if "Wave" in name:
        return "wave"
    if "flate" in name:
        return "inflate"
    if any(k in name for k in ("Fade", "Slant", "Cascade")):
        return "perspective"
    return "basic"


@dataclass(frozen=True)
class TextWarp:
    prst: str
    handles: tuple[tuple[str, int, int, int, str], ...]  # name, default, min, max, kind

    def to_json(self) -> dict:
        ar, en = GROUPS[group_of(self.prst)]
        return {"prst": self.prst, "group": group_of(self.prst), "group_ar": ar, "group_en": en,
                "handles": [{"name": n, "default": d, "min": lo, "max": hi, "kind": k}
                            for n, d, lo, hi, k in self.handles]}


def all_warps() -> tuple[TextWarp, ...]:
    out = []
    for prst in ECMA_TEXT_WARPS:
        hs = []
        for name, default in _DEFAULTS[prst]:
            if (prst, name) in _ANGLE:
                hs.append((name, default, 0, 21599999, "angle"))
            else:
                hs.append((name, default, -100000 if name == "adj2" and "Wave" in prst else 0,
                           max(100000, default), "ratio"))
        out.append(TextWarp(prst, tuple(hs)))
    return tuple(out)


def get_warp(prst: str) -> TextWarp:
    for w in all_warps():
        if w.prst == prst:
            return w
    raise KeyError(f"unknown text warp {prst!r}")


def resolve(prst: str, values: dict | None = None) -> list[tuple[str, int]]:
    warp = get_warp(prst)
    values = values or {}
    names = [h[0] for h in warp.handles]
    unknown = set(values) - set(names)
    if unknown:
        raise ValueError(f"{prst} has no adjust handle(s) {sorted(unknown)}")
    return [(n, int(round(float(values.get(n, d))))) for n, d, *_ in warp.handles]


def prst_tx_warp_xml(prst: str, values: dict | None = None, with_ns: bool = False) -> str:
    gds = "".join(f'<a:gd name="{n}" fmla="val {v}"/>' for n, v in resolve(prst, values))
    ns = f' xmlns:a="{A_NS}"' if with_ns else ""
    return f'<a:prstTxWarp prst="{escape(prst)}"{ns}><a:avLst>{gds}</a:avLst></a:prstTxWarp>'


def catalog() -> dict:
    return {"source": "ECMA-376 Part 1 ST_TextShapeType; avLst per presetTextWarpDefinitions.xml",
            "count": len(ECMA_TEXT_WARPS), "warps": [w.to_json() for w in all_warps()]}
