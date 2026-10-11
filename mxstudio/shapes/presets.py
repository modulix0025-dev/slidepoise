"""OOXML preset geometries (``a:prstGeom``) with their adjust handles.

Rule: the canonical list is ECMA-376 Part 1 ``ST_ShapeType`` (20.1.10.56), embedded below as
data and cross-checked in tests against python-pptx's enumeration and (when installed)
LibreOffice's ``oox-drawingml-adj-names``. Adjust-handle defaults come from python-pptx's
``autoshape_types`` table (MIT; values from presetShapeDefinitions.xml); the ten
line/connector presets python-pptx does not model, and its two defective rows
(``upDownArrow``, ``foldedCorner``), are supplied here.

The slider ranges are *UI hints*: Office pins each adjust value through the preset's own
guide formulas, so out-of-range values are clamped by the renderer, not rejected here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

# ECMA-376 Part 1, ST_ShapeType - 187 values, specification order.
ECMA_PRESET_SHAPES: tuple[str, ...] = (
    "line", "lineInv", "triangle", "rtTriangle", "rect", "diamond", "parallelogram", "trapezoid",
    "nonIsoscelesTrapezoid", "pentagon", "hexagon", "heptagon", "octagon", "decagon", "dodecagon",
    "star4", "star5", "star6", "star7", "star8", "star10", "star12", "star16", "star24", "star32",
    "roundRect", "round1Rect", "round2SameRect", "round2DiagRect", "snipRoundRect", "snip1Rect",
    "snip2SameRect", "snip2DiagRect", "plaque", "ellipse", "teardrop", "homePlate", "chevron",
    "pieWedge", "pie", "blockArc", "donut", "noSmoking", "rightArrow", "leftArrow", "upArrow",
    "downArrow", "stripedRightArrow", "notchedRightArrow", "bentUpArrow", "leftRightArrow",
    "upDownArrow", "leftUpArrow", "leftRightUpArrow", "quadArrow", "leftArrowCallout",
    "rightArrowCallout", "upArrowCallout", "downArrowCallout", "leftRightArrowCallout",
    "upDownArrowCallout", "quadArrowCallout", "bentArrow", "uturnArrow", "circularArrow",
    "leftCircularArrow", "leftRightCircularArrow", "curvedRightArrow", "curvedLeftArrow",
    "curvedUpArrow", "curvedDownArrow", "swooshArrow", "cube", "can", "lightningBolt", "heart",
    "sun", "moon", "smileyFace", "irregularSeal1", "irregularSeal2", "foldedCorner", "bevel",
    "frame", "halfFrame", "corner", "diagStripe", "chord", "arc", "leftBracket", "rightBracket",
    "leftBrace", "rightBrace", "bracketPair", "bracePair", "straightConnector1", "bentConnector2",
    "bentConnector3", "bentConnector4", "bentConnector5", "curvedConnector2", "curvedConnector3",
    "curvedConnector4", "curvedConnector5", "callout1", "callout2", "callout3", "accentCallout1",
    "accentCallout2", "accentCallout3", "borderCallout1", "borderCallout2", "borderCallout3",
    "accentBorderCallout1", "accentBorderCallout2", "accentBorderCallout3", "wedgeRectCallout",
    "wedgeRoundRectCallout", "wedgeEllipseCallout", "cloudCallout", "cloud", "ribbon", "ribbon2",
    "ellipseRibbon", "ellipseRibbon2", "leftRightRibbon", "verticalScroll", "horizontalScroll",
    "wave", "doubleWave", "plus", "flowChartProcess", "flowChartDecision", "flowChartInputOutput",
    "flowChartPredefinedProcess", "flowChartInternalStorage", "flowChartDocument",
    "flowChartMultidocument", "flowChartTerminator", "flowChartPreparation", "flowChartManualInput",
    "flowChartManualOperation", "flowChartConnector", "flowChartPunchedCard", "flowChartPunchedTape",
    "flowChartSummingJunction", "flowChartOr", "flowChartCollate", "flowChartSort",
    "flowChartExtract", "flowChartMerge", "flowChartOfflineStorage", "flowChartOnlineStorage",
    "flowChartMagneticTape", "flowChartMagneticDisk", "flowChartMagneticDrum", "flowChartDisplay",
    "flowChartDelay", "flowChartAlternateProcess", "flowChartOffpageConnector", "actionButtonBlank",
    "actionButtonHome", "actionButtonHelp", "actionButtonInformation", "actionButtonForwardNext",
    "actionButtonBackPrevious", "actionButtonEnd", "actionButtonBeginning", "actionButtonReturn",
    "actionButtonDocument", "actionButtonSound", "actionButtonMovie", "gear6", "gear9", "funnel",
    "mathPlus", "mathMinus", "mathMultiply", "mathDivide", "mathEqual", "mathNotEqual", "cornerTabs",
    "squareTabs", "plaqueTabs", "chartX", "chartStar", "chartPlus",
)

# presetShapeDefinitions.xml avLst for the line/connector presets python-pptx omits.
_SUPPLEMENT_ADJ: dict[str, tuple[tuple[str, int], ...]] = {
    "line": (), "straightConnector1": (), "bentConnector2": (), "curvedConnector2": (),
    "bentConnector3": (("adj1", 50000),),
    "bentConnector4": (("adj1", 50000), ("adj2", 50000)),
    "bentConnector5": (("adj1", 50000), ("adj2", 50000), ("adj3", 50000)),
    "curvedConnector3": (("adj1", 50000),),
    "curvedConnector4": (("adj1", 50000), ("adj2", 50000)),
    "curvedConnector5": (("adj1", 50000), ("adj2", 50000), ("adj3", 50000)),
    # python-pptx table defects (checked against presetShapeDefinitions via LibreOffice's copy):
    "upDownArrow": (("adj1", 50000), ("adj2", 50000)),  # python-pptx lists adj1, adj1, adj2, adj2
    "foldedCorner": (("adj", 16667),),  # python-pptx lists no handle
}

# Adjust values that are angles (60000ths of a degree) rather than proportions.
_ANGLE_ADJ: dict[str, set[str]] = {
    "arc": {"adj1", "adj2"}, "blockArc": {"adj1", "adj2"}, "pie": {"adj1", "adj2"}, "chord": {"adj1", "adj2"},
    "circularArrow": {"adj2", "adj3", "adj4"}, "leftCircularArrow": {"adj2", "adj3", "adj4"},
    "leftRightCircularArrow": {"adj2", "adj3", "adj4"},
}

CATEGORIES: dict[str, tuple[str, str]] = {
    "basic": ("أشكال أساسية", "Basic shapes"),
    "stars": ("نجوم وأختام", "Stars and seals"),
    "rects": ("مستطيلات", "Rectangles"),
    "arrows": ("أسهم", "Arrows"),
    "callouts": ("فقاعات كلام", "Callouts"),
    "banners": ("شرائط ولفائف", "Ribbons and scrolls"),
    "flowchart": ("مخطط انسيابي", "Flowchart"),
    "action": ("أزرار إجراء", "Action buttons"),
    "math": ("رموز رياضية", "Math"),
    "lines": ("خطوط وموصلات", "Lines and connectors"),
    "fun": ("أشكال مرحة", "Fun shapes"),
}

_FUN = {"cloud", "heart", "sun", "moon", "lightningBolt", "smileyFace", "teardrop", "wave", "doubleWave",
        "noSmoking", "gear6", "gear9", "funnel", "can", "cube", "plaque", "donut"}


def category_of(prst: str) -> str:
    if prst.startswith("flowChart"):
        return "flowchart"
    if prst.startswith("actionButton"):
        return "action"
    if prst.startswith("math"):
        return "math"
    if prst.startswith(("star", "irregularSeal")):
        return "stars"
    if "Callout" in prst or prst.startswith(("callout", "accentCallout", "borderCallout", "accentBorderCallout")):
        return "callouts"
    if "Ribbon" in prst or prst.startswith(("ribbon", "ellipseRibbon")) or prst.endswith("Scroll"):
        return "banners"
    if "Arrow" in prst or prst in ("chevron", "homePlate"):
        return "arrows"
    if "Connector" in prst or prst in ("line", "lineInv"):
        return "lines"
    if "Rect" in prst or prst in ("rect", "plaqueTabs", "squareTabs", "cornerTabs"):
        return "rects"
    if prst in _FUN:
        return "fun"
    return "basic"


@dataclass(frozen=True)
class AdjustHandle:
    name: str
    default: int
    minimum: int
    maximum: int
    kind: str  # "ratio" (1/100000) | "angle" (1/60000 deg)

    def to_json(self) -> dict:
        return {"name": self.name, "default": self.default, "min": self.minimum, "max": self.maximum,
                "kind": self.kind}


@dataclass(frozen=True)
class PresetShape:
    prst: str
    label_en: str
    category: str
    handles: tuple[AdjustHandle, ...] = field(default_factory=tuple)

    def to_json(self) -> dict:
        ar, en = CATEGORIES[self.category]
        return {"prst": self.prst, "label_en": self.label_en, "category": self.category,
                "category_ar": ar, "category_en": en, "handles": [h.to_json() for h in self.handles]}


def _handle(prst: str, name: str, default: int) -> AdjustHandle:
    if name in _ANGLE_ADJ.get(prst, set()) or abs(default) > 200000:
        return AdjustHandle(name, int(default), 0, 21599999, "angle")
    if category_of(prst) == "callouts" or default < 0:
        return AdjustHandle(name, int(default), -200000, 200000, "ratio")
    return AdjustHandle(name, int(default), 0, max(100000, int(default)), "ratio")


def _camel_words(prst: str) -> str:
    out = []
    for ch in prst:
        if ch.isupper() and out:
            out.append(" ")
        out.append(ch)
    return "".join(out).capitalize()


@lru_cache(maxsize=1)
def _pptx_table() -> tuple[dict[str, tuple[tuple[str, int], ...]], dict[str, str]]:
    from pptx import spec
    from pptx.enum.shapes import MSO_AUTO_SHAPE_TYPE

    adj: dict[str, tuple[tuple[str, int], ...]] = {}
    labels: dict[str, str] = {}
    for member, info in spec.autoshape_types.items():
        try:
            prst = MSO_AUTO_SHAPE_TYPE.to_xml(member)
        except (KeyError, ValueError, AttributeError):
            continue
        adj.setdefault(prst, tuple((n, int(v)) for n, v in info["avLst"]))
        labels.setdefault(prst, info["basename"])
    return adj, labels


def pptx_adjustments() -> dict[str, tuple[tuple[str, int], ...]]:
    """prst -> avLst defaults from python-pptx (``pptx.spec.autoshape_types``)."""
    return dict(_pptx_table()[0])


def pptx_labels() -> dict[str, str]:
    return dict(_pptx_table()[1])


@lru_cache(maxsize=1)
def all_presets() -> tuple[PresetShape, ...]:
    adj = pptx_adjustments()
    labels = pptx_labels()
    out = []
    for prst in ECMA_PRESET_SHAPES:
        av = _SUPPLEMENT_ADJ[prst] if prst in _SUPPLEMENT_ADJ else adj.get(prst, ())
        handles = tuple(_handle(prst, n, v) for n, v in av)
        out.append(PresetShape(prst, labels.get(prst, _camel_words(prst)), category_of(prst), handles))
    return tuple(out)


def get_preset(prst: str) -> PresetShape:
    for p in all_presets():
        if p.prst == prst:
            return p
    raise KeyError(f"unknown preset geometry {prst!r}")


def resolve_adjustments(prst: str, values: dict[str, int | float] | None = None) -> list[tuple[str, int]]:
    """Defaults overlaid with operator values; unknown handle names are refused."""
    preset = get_preset(prst)
    known = {h.name: h for h in preset.handles}
    values = values or {}
    unknown = set(values) - set(known)
    if unknown:
        raise ValueError(f"{prst} has no adjust handle(s) {sorted(unknown)}")
    out = []
    for h in preset.handles:
        v = int(round(float(values.get(h.name, h.default))))
        out.append((h.name, max(-2_147_483_647, min(2_147_483_647, v))))
    return out


def prst_geom_xml(prst: str, values: dict[str, int | float] | None = None, with_ns: bool = False) -> str:
    from .custgeom import A_NS

    gds = "".join(f'<a:gd name="{n}" fmla="val {v}"/>' for n, v in resolve_adjustments(prst, values))
    ns = f' xmlns:a="{A_NS}"' if with_ns else ""
    return f'<a:prstGeom prst="{prst}"{ns}><a:avLst>{gds}</a:avLst></a:prstGeom>'


def catalog() -> dict:
    return {"source": "ECMA-376 Part 1 ST_ShapeType; avLst defaults via python-pptx autoshape_types",
            "count": len(ECMA_PRESET_SHAPES), "presets": [p.to_json() for p in all_presets()]}
