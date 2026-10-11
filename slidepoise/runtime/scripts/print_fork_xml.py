"""ModuleX print fork: DrawingML finishing that PptxGenJS cannot emit.

* right-to-left paragraphs: ``a:pPr rtl="1"`` (+ ``algn="r"`` unless authored),
  ``lang`` on every run, a complex-script typeface (``a:cs``) on every run;
* exactly one ``a:pPr`` per paragraph, first child (PptxGenJS repeats it per run);
* role-tagged runs verified one-to-one, so a name token is one whole run;
* picture placeholders: the ``SC_PICPH__<id>`` marker rectangles become
  ``<p:sp>`` + ``<p:ph type="pic" idx=…>`` on the slide, and a matching
  placeholder is added to the slide's layout so PowerPoint offers
  "insert picture" and python-pptx sees a picture placeholder.

Called only for slides whose metadata carries these hints, so upstream decks
are byte-identical.
"""
from __future__ import annotations

import copy

from lxml import etree

NS = {"p": "http://schemas.openxmlformats.org/presentationml/2006/main",
      "a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
PICPH_PREFIX = "SC_PICPH__"
PLACEHOLDER_IDX_BASE = 1000


def _tag(name: str) -> str:
    prefix, local = name.split(":")
    return f"{{{NS[prefix]}}}{local}"


def _name(shape: etree._Element) -> str:
    node = shape.find("p:nvSpPr/p:cNvPr", NS)
    return node.get("name", "") if node is not None else ""


def _ensure_single_ppr(paragraph: etree._Element) -> etree._Element:
    found = paragraph.findall("a:pPr", NS)
    keep = found[0] if found else etree.Element(_tag("a:pPr"))
    for extra in found[1:]:
        paragraph.remove(extra)
    if keep.getparent() is not None:
        paragraph.remove(keep)
    paragraph.insert(0, keep)
    return keep


def _set_run_language(rpr: etree._Element, lang: str) -> None:
    rpr.set("lang", lang)
    latin = rpr.find("a:latin", NS)
    cs = rpr.find("a:cs", NS)
    if latin is not None and cs is None:
        cs = etree.Element(_tag("a:cs"), typeface=latin.get("typeface", ""))
        ea = rpr.find("a:ea", NS)
        anchor = ea if ea is not None else latin
        anchor.addnext(cs)
    elif latin is not None and cs is not None and not cs.get("typeface"):
        cs.set("typeface", latin.get("typeface", ""))


def apply_text_hints(root: etree._Element, directions: dict, runs: dict) -> dict[str, int]:
    facts = {"rtlParagraphs": 0, "taggedRuns": 0}
    for shape in root.iter(_tag("p:sp")):
        name = _name(shape)
        if name not in directions and name not in runs:
            continue
        body = shape.find("p:txBody", NS)
        if body is None:
            raise ValueError(f"text hints target {name!r}, which has no text body")
        direction = directions.get(name) or {}
        paragraphs = body.findall("a:p", NS)
        for paragraph in paragraphs:
            ppr = _ensure_single_ppr(paragraph)
            if direction.get("rtl"):
                ppr.set("rtl", "1")
                ppr.set("algn", ppr.get("algn") or "r")
                for rpr in paragraph.iter(_tag("a:rPr"), _tag("a:endParaRPr")):
                    _set_run_language(rpr, str(direction.get("lang") or "ar-EG"))
                facts["rtlParagraphs"] += 1
        if name in runs:
            expected = [item["text"] for item in runs[name]]
            actual = ["".join(t.text or "" for t in run.findall("a:t", NS))
                      for paragraph in paragraphs for run in paragraph.findall("a:r", NS)]
            if actual != expected:
                raise ValueError(f"run structure of {name!r} changed during construction: {actual!r} != {expected!r}")
            facts["taggedRuns"] += sum(1 for item in runs[name] if item.get("role"))
    return facts


def _placeholder_sp(shape_id: str, name: str, idx: int, xfrm: etree._Element | None, descr: str = "") -> etree._Element:
    sp = etree.Element(_tag("p:sp"))
    nv = etree.SubElement(sp, _tag("p:nvSpPr"))
    attrs = {"id": shape_id, "name": name}
    if descr:
        attrs["descr"] = descr
    etree.SubElement(nv, _tag("p:cNvPr"), **attrs)
    locks = etree.SubElement(etree.SubElement(nv, _tag("p:cNvSpPr")), _tag("a:spLocks"))
    locks.set("noGrp", "1")
    nvpr = etree.SubElement(nv, _tag("p:nvPr"))
    etree.SubElement(nvpr, _tag("p:ph"), type="pic", sz="quarter", idx=str(idx))
    sppr = etree.SubElement(sp, _tag("p:spPr"))
    if xfrm is not None:
        sppr.append(copy.deepcopy(xfrm))
    geom = etree.SubElement(sppr, _tag("a:prstGeom"), prst="rect")
    etree.SubElement(geom, _tag("a:avLst"))
    return sp


def apply_picture_placeholders(root: etree._Element, hints: dict, slide_number: int) -> list[dict]:
    """Replace marker rectangles; return [{id, idx, xfrm}] for the layout pass, in placeholder order."""
    markers = []
    for position, shape in enumerate(root.iter(_tag("p:sp"))):
        name = _name(shape)
        if name.startswith(PICPH_PREFIX):
            object_id = name[len(PICPH_PREFIX):]
            if object_id not in hints:
                raise ValueError(f"picture placeholder marker {object_id!r} has no hint")
            order = hints[object_id].get("order")
            markers.append(((order if order is not None else 10_000) , position, object_id, shape))
    missing = set(hints) - {item[2] for item in markers}
    if missing:
        raise ValueError(f"picture placeholders missing from the slide: {sorted(missing)}")
    placed = []
    for number, (_order, _position, object_id, shape) in enumerate(sorted(markers, key=lambda m: (m[0], m[1])), 1):
        fixed = hints[object_id].get("idx")  # a fixed index (e.g. 100 for the full-page scene) the operator's
        idx = int(fixed) if fixed else PLACEHOLDER_IDX_BASE + slide_number * 20 + number  # tools address by idx
        cnv = shape.find("p:nvSpPr/p:cNvPr", NS)
        xfrm = shape.find("p:spPr/a:xfrm", NS)
        label = hints[object_id].get("label") or object_id
        name = f"Picture Placeholder {idx}" if fixed else f"Picture Placeholder {number}"
        replacement = _placeholder_sp(cnv.get("id"), name, idx, xfrm, descr=label)
        shape.getparent().replace(shape, replacement)
        placed.append({"id": object_id, "idx": idx, "xfrm": copy.deepcopy(xfrm) if xfrm is not None else None})
    return placed


def add_layout_placeholders(layout_xml: bytes, placed: list[dict]) -> bytes:
    root = etree.fromstring(layout_xml, etree.XMLParser(resolve_entities=False, no_network=True))
    tree = root.find("p:cSld/p:spTree", NS)
    existing = {ph.get("idx") for ph in tree.iter(_tag("p:ph"))}
    next_id = max([int(node.get("id", "0")) for node in root.iter(_tag("p:cNvPr"))] + [1]) + 1
    for item in placed:
        if str(item["idx"]) in existing:
            continue
        tree.append(_placeholder_sp(str(next_id), f"Picture Placeholder {item['idx']}", item["idx"], item["xfrm"]))
        existing.add(str(item["idx"]))
        next_id += 1
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
