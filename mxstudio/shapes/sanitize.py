"""SVG sanitiser for everything that enters the shape pipeline from outside.

Rule: only geometry survives - ``svg/g/path/rect/circle/ellipse/line/polyline/polygon``
(+ ``title/desc`` text as inert data) with presentation attributes. Hard rejects (named
``SvgRejected`` codes): DOCTYPE/ENTITY declarations (entity expansion, XXE), unparsable XML,
non-SVG root, size/node/depth/path-data caps, non-finite or absurd coordinates.
Stripped with a named finding: ``script``, ``foreignObject``, ``style``, ``image``, ``use``,
``a``, animation, event handlers (``on*``), any ``href`` / external reference, ``url(...)``
paint servers, CSS in ``style`` attributes other than plain presentation properties,
processing instructions, comments and foreign namespaces.

``strict=True`` turns every *dangerous* strip into a rejection (used for LLM output so the
model gets told, and for nothing else).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from lxml import etree

SVG_NS = "http://www.w3.org/2000/svg"

GEOMETRY_ELEMENTS = {"svg", "g", "path", "rect", "circle", "ellipse", "line", "polyline", "polygon"}
INERT_TEXT_ELEMENTS = {"title", "desc"}
DANGEROUS_ELEMENTS = {"script": "script", "foreignObject": "foreign_object", "style": "style_element",
                      "image": "external_ref", "use": "external_ref", "a": "external_ref", "iframe": "script",
                      "animate": "animation", "animateMotion": "animation", "animateTransform": "animation",
                      "set": "animation", "handler": "script", "listener": "script", "feImage": "external_ref"}

PRESENTATION = {"fill", "fill-opacity", "fill-rule", "stroke", "stroke-width", "stroke-opacity", "stroke-linecap",
                "stroke-linejoin", "stroke-miterlimit", "stroke-dasharray", "stroke-dashoffset", "opacity",
                "clip-rule", "display", "visibility", "color"}
GEOMETRY_ATTRS = {
    "svg": {"viewBox", "width", "height", "x", "y", "preserveAspectRatio", "version"},
    "g": {"transform"},
    "path": {"d", "transform", "pathLength"},
    "rect": {"x", "y", "width", "height", "rx", "ry", "transform"},
    "circle": {"cx", "cy", "r", "transform"},
    "ellipse": {"cx", "cy", "rx", "ry", "transform"},
    "line": {"x1", "y1", "x2", "y2", "transform"},
    "polyline": {"points", "transform"},
    "polygon": {"points", "transform"},
    "title": set(), "desc": set(),
}
DANGEROUS_CODES = {"script", "foreign_object", "event_handler", "external_ref", "style_element", "css_rejected",
                   "paint_server_ref", "animation", "processing_instruction", "foreign_namespace"}

_NUM = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_SAFE_VALUE = re.compile(r"^[#a-zA-Z0-9 .,%()+\-]*$")
_TRANSFORM = re.compile(r"^\s*((matrix|translate|scale|rotate|skewX|skewY)\s*\([-+0-9.eE,\s]*\)\s*,?\s*)*$")


class SvgRejected(ValueError):
    """The input cannot be made safe; ``code`` names the rule."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class Finding:
    code: str
    detail: str

    def to_json(self) -> dict:
        return {"code": self.code, "detail": self.detail}


@dataclass
class SanitizedSvg:
    svg: str
    findings: list[Finding] = field(default_factory=list)
    node_count: int = 0
    title: str = ""

    @property
    def dangerous(self) -> list[Finding]:
        return [f for f in self.findings if f.code in DANGEROUS_CODES]

    def to_json(self) -> dict:
        return {"svg": self.svg, "findings": [f.to_json() for f in self.findings], "node_count": self.node_count,
                "title": self.title}


@dataclass(frozen=True)
class Limits:
    max_bytes: int = 2_000_000
    max_elements: int = 5_000
    max_depth: int = 48
    max_path_chars: int = 400_000
    max_numbers: int = 200_000
    max_abs_coordinate: float = 1e6


def _local(tag) -> str | None:
    if not isinstance(tag, str):
        return None
    return etree.QName(tag).localname


def _ns(tag: str) -> str | None:
    return etree.QName(tag).namespace


def _clean_text(text: str, limit: int = 300) -> str:
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f‪-‮⁦-⁩]", "", text or "")
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _check_numbers(text: str, limits: Limits, counter: list[int], where: str) -> None:
    for m in _NUM.finditer(text):
        counter[0] += 1
        if counter[0] > limits.max_numbers:
            raise SvgRejected("too_many_numbers", f"> {limits.max_numbers}")
        try:
            v = float(m.group(0))
        except ValueError:  # pragma: no cover - regex guarantees a float
            raise SvgRejected("bad_number", where) from None
        if v != v or abs(v) > limits.max_abs_coordinate:
            raise SvgRejected("coordinate_out_of_range", f"{where}={m.group(0)[:24]}")


def sanitize_svg(data: str | bytes, *, strict: bool = False, limits: Limits = Limits()) -> SanitizedSvg:
    """Return a geometry-only SVG or raise :class:`SvgRejected`."""
    raw = data.encode("utf-8") if isinstance(data, str) else bytes(data)
    if len(raw) > limits.max_bytes:
        raise SvgRejected("too_large", f"{len(raw)} bytes > {limits.max_bytes}")
    if b"\x00" in raw or raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        raise SvgRejected("encoding", "only UTF-8 SVG is accepted")
    head = raw.lower()
    if b"<!doctype" in head or b"<!entity" in head or b"<!element" in head or b"<!attlist" in head:
        raise SvgRejected("doctype_or_entity", "DTDs and entities are never accepted")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, dtd_validation=False,
                             huge_tree=False, remove_comments=True, remove_pis=False, recover=False)
    try:
        root = etree.fromstring(raw, parser)
    except etree.XMLSyntaxError as exc:
        raise SvgRejected("xml_syntax", str(exc)[:200]) from None
    if root.getroottree().docinfo.doctype:
        raise SvgRejected("doctype_or_entity", "DTDs and entities are never accepted")
    if _local(root.tag) != "svg" or _ns(root.tag) not in (SVG_NS, None):
        raise SvgRejected("not_svg", f"root is {root.tag!r}")

    findings: list[Finding] = []
    total = 0
    for el in root.iter():
        total += 1
        if total > limits.max_elements:
            raise SvgRejected("too_many_nodes", f"> {limits.max_elements} elements")

    def depth(el, d=0):
        if d > limits.max_depth:
            raise SvgRejected("too_deep", f"> {limits.max_depth}")
        for child in el:
            depth(child, d + 1)

    depth(root)

    # processing instructions anywhere (incl. before the root)
    prev = root.getprevious()
    while prev is not None:
        if isinstance(prev, etree._ProcessingInstruction):
            findings.append(Finding("processing_instruction", prev.target))
        prev = prev.getprevious()

    counter = [0]
    title = ""
    out_root = etree.Element(f"{{{SVG_NS}}}svg", nsmap={None: SVG_NS})
    kept = 0

    def copy_attrs(src, dst, name: str) -> None:
        allowed = GEOMETRY_ATTRS.get(name, set()) | (PRESENTATION if name not in INERT_TEXT_ELEMENTS else set())
        for key, value in src.attrib.items():
            local = etree.QName(key).localname
            ns = etree.QName(key).namespace
            low = local.lower()
            if low.startswith("on"):
                findings.append(Finding("event_handler", f"{name}@{local}"))
                continue
            if low in ("href", "src") or (ns and "xlink" in ns):
                findings.append(Finding("external_ref", f"{name}@{local}"))
                continue
            if ns is not None:
                findings.append(Finding("foreign_attribute", f"{name}@{local}"))
                continue
            if local == "style":
                for decl in value.split(";"):
                    if not decl.strip():
                        continue
                    prop, _, val = decl.partition(":")
                    prop, val = prop.strip().lower(), val.strip()
                    if prop not in PRESENTATION or "url(" in val.lower() or not _SAFE_VALUE.match(val) \
                            or "expression" in val.lower():
                        findings.append(Finding("css_rejected", f"{name}: {prop}"))
                        continue
                    dst.set(prop, val)
                continue
            if local not in allowed:
                if local not in ("id", "class", "version"):
                    findings.append(Finding("attribute_stripped", f"{name}@{local}"))
                continue
            if local in PRESENTATION:
                if "url(" in value.lower():
                    findings.append(Finding("paint_server_ref", f"{name}@{local}"))
                    continue
                if not _SAFE_VALUE.match(value):
                    findings.append(Finding("css_rejected", f"{name}@{local}"))
                    continue
            if local == "transform" and not _TRANSFORM.match(value):
                findings.append(Finding("attribute_stripped", f"{name}@transform"))
                continue
            if local == "d" and len(value) > limits.max_path_chars:
                raise SvgRejected("path_data_too_long", f"{len(value)} chars")
            if local in ("d", "points", "viewBox", "transform", "x", "y", "width", "height", "cx", "cy", "r",
                         "rx", "ry", "x1", "y1", "x2", "y2"):
                _check_numbers(value, limits, counter, f"{name}@{local}")
            dst.set(local, value)

    def walk(src, dst) -> None:
        nonlocal kept, title
        for child in src:
            if isinstance(child, etree._ProcessingInstruction):
                findings.append(Finding("processing_instruction", child.target))
                continue
            if not isinstance(child.tag, str):
                continue
            name = _local(child.tag)
            ns = _ns(child.tag)
            if ns not in (SVG_NS, None):
                findings.append(Finding("foreign_namespace" if name != "foreignObject" else "foreign_object",
                                        f"{{{ns}}}{name}"))
                continue
            if name in DANGEROUS_ELEMENTS:
                findings.append(Finding(DANGEROUS_ELEMENTS[name], name))
                continue
            if name in INERT_TEXT_ELEMENTS:
                if name == "title" and not title:
                    title = _clean_text("".join(child.itertext()))
                continue
            if name not in GEOMETRY_ELEMENTS:
                findings.append(Finding("element_stripped", name or "?"))
                continue
            if name == "svg":
                findings.append(Finding("nested_svg_flattened", "svg"))
                name = "g"
            new = etree.SubElement(dst, f"{{{SVG_NS}}}{name}")
            kept += 1
            copy_attrs(child, new, name)
            if child.text and child.text.strip():
                findings.append(Finding("text_stripped", name))
            walk(child, new)

    copy_attrs(root, out_root, "svg")
    walk(root, out_root)
    if not out_root.get("viewBox") and not (out_root.get("width") and out_root.get("height")):
        raise SvgRejected("no_viewport", "needs viewBox or width+height")
    if kept == 0:
        raise SvgRejected("no_geometry", "nothing drawable left")
    if strict and any(f.code in DANGEROUS_CODES for f in findings):
        bad = sorted({f.code for f in findings if f.code in DANGEROUS_CODES})
        raise SvgRejected("dangerous_content", ", ".join(bad))
    svg = etree.tostring(out_root, encoding="unicode")
    return SanitizedSvg(svg=svg, findings=findings, node_count=kept + 1, title=title)
