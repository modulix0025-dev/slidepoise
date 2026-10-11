"""OOXML text and shape effects PowerPoint renders natively, applied to a rendered deck by object id.

Hints live on spec objects as ``fx``:
* ``rotate``      degrees (clockwise), written as ``a:xfrm/@rot``;
* ``shadow``      a soft outer shadow on every run (readability over art);
* ``name_style``  gold | ice | pink — the child's name art: gradient fill on the runs, a glow, and a white outline
                  (gold, pink), as in designs/lulu_world/src/textfx.py;
* ``rtl``         ``rtl="1"`` on every paragraph that holds Arabic;
* ``gradient``    {color, toward: right|left|bottom, from_alpha, to_alpha} — the overlay's alpha gradient fill.
LibreOffice previews may draw some of these flatter (a single colour, no glow); PowerPoint shows them all.
"""
from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

from lxml import etree

NS = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main",
      "p": "http://schemas.openxmlformats.org/presentationml/2006/main"}
A = "{%s}" % NS["a"]
SLIDE_RE = re.compile(r"^ppt/slides/slide\d+\.xml$")
GRADIENTS = {"gold": ("FFF07A", "FF7A00"), "ice": ("FFFFFF", "6FD6FF"), "pink": ("FFC2E8", "B05CFF")}
GLOWS = {"gold": ("FFB300", 45000, 63500), "ice": ("7FE0FF", 70000, 139700), "pink": ("FF6FD0", 50000, 101600)}
OUTLINED = {"gold", "pink"}
ANGLES = {"right": 0, "left": 10800000, "bottom": 5400000, "top": 16200000}
# children of a:rPr that must come AFTER ln / fill / effects (CT_TextCharacterProperties order)
RPR_TAIL = {A + n for n in ("highlight", "uLnTx", "uLn", "uFillTx", "uFill", "latin", "ea", "cs", "sym", "hlinkClick",
                            "hlinkMouseOver", "rtl", "extLst")}
FILLS = {A + n for n in ("noFill", "solidFill", "gradFill", "blipFill", "pattFill", "grpFill")}
ARABIC = re.compile("[؀-ۿ]")


def _el(tag: str, **attrs) -> etree._Element:
    return etree.Element(A + tag, **{k: str(v) for k, v in attrs.items()})


def _sub(parent, tag: str, **attrs):
    return etree.SubElement(parent, A + tag, **{k: str(v) for k, v in attrs.items()})


def _grad(stops: list[tuple[int, str, int | None]], angle: int) -> etree._Element:
    fill = _el("gradFill", flip="none", rotWithShape="1")
    lst = _sub(fill, "gsLst")
    for pos, colour, alpha in stops:
        gs = _sub(lst, "gs", pos=pos)
        clr = _sub(gs, "srgbClr", val=colour)
        if alpha is not None:
            _sub(clr, "alpha", val=alpha)
    _sub(fill, "lin", ang=angle, scaled="1")
    return fill


def _set_run_props(rpr: etree._Element, *, ln=None, fill=None, effects=None) -> None:
    for child in list(rpr):
        if (fill is not None and child.tag in FILLS) or (ln is not None and child.tag == A + "ln") or \
                (effects is not None and child.tag in (A + "effectLst", A + "effectDag")):
            rpr.remove(child)
    tail = next((i for i, child in enumerate(rpr) if child.tag in RPR_TAIL), len(rpr))
    for element in [e for e in (ln, fill, effects) if e is not None][::-1]:
        rpr.insert(tail, element)
    # ln must be first of the three
    if ln is not None:
        rpr.remove(ln)
        rpr.insert(next((i for i, c in enumerate(rpr) if c.tag in FILLS | {A + "effectLst"} | RPR_TAIL), len(rpr)), ln)


def _shadow() -> etree._Element:
    effects = _el("effectLst")
    shadow = _sub(effects, "outerShdw", blurRad=76200, dist=19050, dir=5400000, algn="t", rotWithShape="0")
    _sub(_sub(shadow, "srgbClr", val="1A1030"), "alpha", val=75000)
    return effects


def _name_effects(style: str) -> tuple:
    a, b = GRADIENTS[style]
    fill = _grad([(0, a, None), (100000, b, None)], 5400000)
    glow_colour, alpha, radius = GLOWS[style]
    effects = _el("effectLst")
    _sub(_sub(_sub(effects, "glow", rad=radius), "srgbClr", val=glow_colour), "alpha", val=alpha)
    ln = None
    if style in OUTLINED:
        ln = _el("ln", w=38100)
        _sub(_sub(ln, "solidFill"), "srgbClr", val="FFFFFF")
    return ln, fill, effects


def _runs(shape) -> list:
    return shape.findall(".//a:r/a:rPr", NS) + shape.findall(".//a:endParaRPr", NS)


def apply_to_shape(shape, fx: dict) -> list[str]:
    done = []
    sppr = shape.find("p:spPr", NS)
    xfrm = sppr.find("a:xfrm", NS) if sppr is not None else None
    if fx.get("rotate") and xfrm is not None:
        xfrm.set("rot", str(int(round(float(fx["rotate"]) * 60000)) % 21600000))
        done.append("rotate")
    if fx.get("gradient") and sppr is not None:
        g = fx["gradient"]
        colour = str(g.get("color", "#0B1020")).lstrip("#").upper()
        a0, a1 = int(g.get("from_alpha", 0)) * 1000, int(g.get("to_alpha", 78)) * 1000
        if g.get("toward") == "full":
            a0 = a1
        # clear at the art edge, full strength 40 % in, flat under the words
        fill = _grad([(0, colour, a0), (40000, colour, a1), (100000, colour, a1)],
                     ANGLES.get(g.get("toward", "right"), 0))
        old = next((c for c in sppr if c.tag in FILLS), None)
        if old is not None:
            sppr.replace(old, fill)
        else:
            geometry = sppr.find("a:prstGeom", NS)
            sppr.insert(sppr.index(geometry) + 1 if geometry is not None else len(sppr), fill)
        done.append("gradient")
    if fx.get("name_style"):
        for rpr in shape.findall(".//a:r/a:rPr", NS):
            ln, fill, effects = _name_effects(fx["name_style"])
            _set_run_props(rpr, ln=ln, fill=fill, effects=effects)
        done.append("name_style")
    elif fx.get("shadow"):
        for rpr in shape.findall(".//a:r/a:rPr", NS):
            _set_run_props(rpr, effects=_shadow())
        done.append("shadow")
    if fx.get("rtl"):
        for paragraph in shape.findall(".//a:p", NS):
            text = "".join(t.text or "" for t in paragraph.findall(".//a:t", NS))
            if ARABIC.search(text):
                ppr = paragraph.find("a:pPr", NS)
                if ppr is None:
                    ppr = _el("pPr")
                    paragraph.insert(0, ppr)
                ppr.set("rtl", "1")
        done.append("rtl")
    return done


def apply(pptx: Path, spec: dict) -> dict:
    """Apply every object's ``fx`` to the rendered deck, in place. Returns {object id: [effects applied]}."""
    by_slide = {}
    for number, slide in enumerate(spec["slides"], 1):
        wanted = {obj["id"]: obj["fx"] for obj in slide["objects"] if obj.get("fx")}
        if wanted:
            by_slide[f"ppt/slides/slide{number}.xml"] = wanted
    if not by_slide:
        return {}
    applied: dict[str, list[str]] = {}
    source = zipfile.ZipFile(pptx)
    buffer = io.BytesIO()
    with source, zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as out:
        for info in source.infolist():
            data = source.read(info.filename)
            wanted = by_slide.get(info.filename)
            if wanted:
                root = etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True))
                for shape in root.iter("{%s}sp" % NS["p"]):
                    cnv = shape.find("p:nvSpPr/p:cNvPr", NS)
                    name = cnv.get("name") if cnv is not None else None
                    if name in wanted:
                        applied[name] = apply_to_shape(shape, wanted[name])
                data = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
            out.writestr(info, data)
    Path(pptx).write_bytes(buffer.getvalue())
    missing = {oid for wanted in by_slide.values() for oid in wanted} - set(applied)
    if missing:
        raise ValueError(f"effects target objects missing from the deck: {sorted(missing)}")
    return applied
