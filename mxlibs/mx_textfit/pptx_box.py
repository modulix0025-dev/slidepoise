"""Read the box size and font of an editor paragraph straight from the PPTX package.

Rule enforced: the facts come from the deck's own XML, with the OOXML
inheritance chain applied (run -> shape list style -> layout/master
placeholder -> master text styles / presentation default text style -> theme
fonts). Stdlib only (zipfile + ElementTree): python-pptx is not needed.

Paragraph ids follow the operator's editor: ``t-<slide>-<shape_id>-<para>``.
Assumption (pending on-device proof against OM ``app/editor/deck.py``): the
slide number is 1-based in presentation order and the paragraph index is
0-based within the shape's text body. Both bases are parameters.
"""

from __future__ import annotations

import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile

from .fit import DEFAULT_INSET_EMU, EDITOR_MAX_LINES, _message, char_limit, fit
from .measure import has_rtl

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}
_A = "{%s}" % NS["a"]
_P = "{%s}" % NS["p"]
_R = "{%s}" % NS["r"]
PARA_ID = re.compile(r"^t-(\d+)-(\d+)-(\d+)$")
_TITLE_TYPES = {"title", "ctrTitle"}
_BODY_TYPES = {"body", "subTitle", "obj", None}


class ParagraphNotFound(LookupError):
    """The paragraph id does not address a paragraph in this deck."""


class _Package:
    def __init__(self, path):
        self.zip = zipfile.ZipFile(path)
        self._xml: dict[str, ET.Element] = {}

    def xml(self, part: str) -> ET.Element | None:
        if part not in self._xml:
            try:
                self._xml[part] = ET.fromstring(self.zip.read(part))
            except KeyError:
                return None
        return self._xml[part]

    def rels(self, part: str) -> dict[str, tuple[str, str]]:
        folder, name = posixpath.split(part)
        root = self.xml(posixpath.join(folder, "_rels", name + ".rels"))
        out: dict[str, tuple[str, str]] = {}
        if root is None:
            return out
        for rel in root.findall("rel:Relationship", NS):
            target = rel.get("Target", "")
            if rel.get("TargetMode") == "External":
                continue
            resolved = (
                target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join(folder, target))
            )
            out[rel.get("Id", "")] = (rel.get("Type", "").rsplit("/", 1)[-1], resolved)
        return out

    def related(self, part: str, kind: str) -> str | None:
        for rel_type, target in self.rels(part).values():
            if rel_type == kind:
                return target
        return None

    def slide_parts(self) -> list[str]:
        pres = self.xml("ppt/presentation.xml")
        rels = self.rels("ppt/presentation.xml")
        if pres is None:
            return []
        return [rels[s.get(_R + "id")][1] for s in pres.findall("p:sldIdLst/p:sldId", NS) if s.get(_R + "id") in rels]

    def close(self):
        self.zip.close()


def _ph(sp: ET.Element) -> ET.Element | None:
    return sp.find("p:nvSpPr/p:nvPr/p:ph", NS)


def _match_placeholder(tree: ET.Element | None, ph: ET.Element, by_type_only: bool = False) -> ET.Element | None:
    if tree is None:
        return None
    ph_type, ph_idx = ph.get("type"), ph.get("idx")
    candidates = [(sp, _ph(sp)) for sp in tree.iter(_P + "sp") if _ph(sp) is not None]
    if ph_idx is not None and not by_type_only:
        for sp, other in candidates:
            if other.get("idx") == ph_idx:
                return sp
    norm = lambda t: "title" if t in _TITLE_TYPES else ("body" if t in _BODY_TYPES else t)
    for sp, other in candidates:
        if norm(other.get("type")) == norm(ph_type):
            return sp
    return None


def _lvl(container: ET.Element | None, level: int) -> ET.Element | None:
    if container is None:
        return None
    return container.find(f"a:lvl{level + 1}pPr", NS)


def _paragraph_text(para: ET.Element) -> str:
    parts: list[str] = []
    for child in para:
        if child.tag in (_A + "r", _A + "fld"):
            parts.append("".join(t.text or "" for t in child.findall("a:t", NS)))
        elif child.tag == _A + "br":
            parts.append("\n")
    return "".join(parts)


def _theme_fonts(theme: ET.Element | None) -> dict[str, str]:
    out: dict[str, str] = {}
    if theme is None:
        return out
    scheme = theme.find(".//a:fontScheme", NS)
    if scheme is None:
        return out
    for tag, key in (("majorFont", "mj"), ("minorFont", "mn")):
        node = scheme.find(f"a:{tag}", NS)
        if node is None:
            continue
        for script in ("latin", "ea", "cs"):
            el = node.find(f"a:{script}", NS)
            if el is not None and el.get("typeface"):
                out[f"+{key}-{'lt' if script == 'latin' else script}"] = el.get("typeface")
        arab = node.find("a:font[@script='Arab']", NS)
        if arab is not None and arab.get("typeface") and not out.get(f"+{key}-cs"):
            out[f"+{key}-cs"] = arab.get("typeface")
    return out


def _spacing(el: ET.Element | None, size_pt: float) -> tuple[float | None, float | None]:
    """(multiple, points) of an lnSpc/spcBef/spcAft element."""
    if el is None:
        return None, None
    pct = el.find("a:spcPct", NS)
    if pct is not None and pct.get("val"):
        return int(pct.get("val")) / 100000.0, None
    pts = el.find("a:spcPts", NS)
    if pts is not None and pts.get("val"):
        return None, int(pts.get("val")) / 100.0
    return None, None


def paragraph_box(pptx_path, para_id: str, *, slide_base: int = 1, para_base: int = 0) -> dict:
    """Box size, insets, auto-fit and resolved font of the paragraph ``t-<slide>-<shape_id>-<para>``."""
    match = PARA_ID.match(str(para_id or "").strip())
    if not match:
        raise ValueError(f"not an editor paragraph id: {para_id!r} (expected t-<slide>-<shape_id>-<para>)")
    slide_no, shape_id, para_no = (int(v) for v in match.groups())
    pkg = _Package(pptx_path)
    try:
        slides = pkg.slide_parts()
        slide_index = slide_no - slide_base
        if not 0 <= slide_index < len(slides):
            raise ParagraphNotFound(f"slide {slide_no} does not exist ({len(slides)} slides)")
        slide_part = slides[slide_index]
        slide = pkg.xml(slide_part)
        parents = {child: parent for parent in slide.iter() for child in parent}
        shape = None
        for sp in slide.iter(_P + "sp"):
            c_nv = sp.find("p:nvSpPr/p:cNvPr", NS)
            if c_nv is not None and c_nv.get("id") == str(shape_id):
                shape = sp
                break
        if shape is None:
            raise ParagraphNotFound(f"shape id {shape_id} is not on slide {slide_no}")
        body = shape.find("p:txBody", NS)
        paras = body.findall("a:p", NS) if body is not None else []
        para_index = para_no - para_base
        if not 0 <= para_index < len(paras):
            raise ParagraphNotFound(f"shape {shape_id} on slide {slide_no} has {len(paras)} paragraph(s)")
        para = paras[para_index]

        layout_part = pkg.related(slide_part, "slideLayout")
        master_part = pkg.related(layout_part, "slideMaster") if layout_part else None
        theme_part = pkg.related(master_part, "theme") if master_part else None
        layout = pkg.xml(layout_part) if layout_part else None
        master = pkg.xml(master_part) if master_part else None
        theme_fonts = _theme_fonts(pkg.xml(theme_part) if theme_part else None)
        pres = pkg.xml("ppt/presentation.xml")

        ph = _ph(shape)
        layout_sp = _match_placeholder(layout, ph) if ph is not None else None
        master_sp = _match_placeholder(master, ph, by_type_only=True) if ph is not None else None
        level = int((para.find("a:pPr", NS).get("lvl") if para.find("a:pPr", NS) is not None else 0) or 0)

        # ---- list-style chain, highest priority first --------------------------------------
        styles: list[ET.Element] = []
        own_ppr = para.find("a:pPr", NS)
        for sp in (shape, layout_sp, master_sp):
            if sp is not None:
                node = _lvl(sp.find("p:txBody/a:lstStyle", NS), level)
                if node is not None:
                    styles.append(node)
        if ph is not None and master is not None:
            kind = (
                "titleStyle"
                if ph.get("type") in _TITLE_TYPES
                else ("bodyStyle" if ph.get("type") in _BODY_TYPES else "otherStyle")
            )
            node = _lvl(master.find(f"p:txStyles/p:{kind}", NS), level)
            if node is not None:
                styles.append(node)
        else:
            for container in (
                (pres.find("p:defaultTextStyle", NS) if pres is not None else None),
                (master.find("p:txStyles/p:otherStyle", NS) if master is not None else None),
            ):
                node = _lvl(container, level)
                if node is not None:
                    styles.append(node)
        ppr_chain = [el for el in [own_ppr, *styles] if el is not None]
        run = para.find("a:r/a:rPr", NS)
        if run is None:
            run = para.find("a:fld/a:rPr", NS)
        if run is None:
            run = para.find("a:endParaRPr", NS)
        rpr_chain = [el for el in [run, *[s.find("a:defRPr", NS) for s in styles]] if el is not None]

        def rattr(name: str):
            for el in rpr_chain:
                if el.get(name) is not None:
                    return el.get(name)
            return None

        def rface(script: str) -> str | None:
            for el in rpr_chain:
                node = el.find(f"a:{script}", NS)
                if node is not None and node.get("typeface"):
                    face = node.get("typeface")
                    return theme_fonts.get(face, face) if face.startswith("+") else face
            return None

        def pchild(name: str) -> ET.Element | None:
            for el in ppr_chain:
                node = el.find(f"a:{name}", NS)
                if node is not None:
                    return node
            return None

        def pattr(name: str):
            for el in ppr_chain:
                if el.get(name) is not None:
                    return el.get(name)
            return None

        # ---- body properties (insets, wrap, autofit) -----------------------------------------
        body_chain = [sp.find("p:txBody/a:bodyPr", NS) for sp in (shape, layout_sp, master_sp) if sp is not None]
        body_chain = [b for b in body_chain if b is not None]

        def battr(name: str, default):
            for el in body_chain:
                if el.get(name) is not None:
                    return el.get(name)
            return default

        insets = tuple(
            int(battr(name, dflt))
            for name, dflt in zip(("lIns", "tIns", "rIns", "bIns"), DEFAULT_INSET_EMU, strict=True)
        )
        autofit, font_scale, spacing_reduction = "none", 1.0, 0.0
        for el in body_chain:
            norm = el.find("a:normAutofit", NS)
            if norm is not None:
                autofit = "norm"
                font_scale = int(norm.get("fontScale", "100000")) / 100000.0
                spacing_reduction = int(norm.get("lnSpcReduction", "0")) / 100000.0
                break
            if el.find("a:spAutoFit", NS) is not None:
                autofit = "shape"
                break
            if el.find("a:noAutofit", NS) is not None:
                break
        wrap = battr("wrap", "square") != "none"

        # ---- geometry --------------------------------------------------------------------------
        ext = None
        for sp in (shape, layout_sp, master_sp):
            if sp is not None and sp.find("p:spPr/a:xfrm/a:ext", NS) is not None:
                ext = sp.find("p:spPr/a:xfrm/a:ext", NS)
                break
        if ext is None:
            raise ParagraphNotFound(f"shape {shape_id} on slide {slide_no} has no size")
        cx, cy = float(ext.get("cx", 0)), float(ext.get("cy", 0))
        node = parents.get(shape)
        while node is not None:  # group transforms scale child extents
            if node.tag == _P + "grpSp":
                xfrm = node.find("p:grpSpPr/a:xfrm", NS)
                if xfrm is not None:
                    g_ext, g_ch = xfrm.find("a:ext", NS), xfrm.find("a:chExt", NS)
                    if g_ext is not None and g_ch is not None and float(g_ch.get("cx", 0)) and float(g_ch.get("cy", 0)):
                        cx *= float(g_ext.get("cx")) / float(g_ch.get("cx"))
                        cy *= float(g_ext.get("cy")) / float(g_ch.get("cy"))
            node = parents.get(node)

        # ---- font ------------------------------------------------------------------------------
        text = _paragraph_text(para)
        all_texts = [_paragraph_text(p) for p in paras]
        declared = int(rattr("sz") or 1800) / 100.0
        size_pt = round(declared * font_scale * 2) / 2 if autofit == "norm" and font_scale < 1 else declared
        latin, cs = rface("latin"), rface("cs")
        rtl_text = has_rtl("".join(all_texts))
        family = (cs or latin) if rtl_text else (latin or cs)
        multiple, exact = _spacing(pchild("lnSpc"), size_pt)
        if multiple is not None:
            multiple = max(0.1, multiple - spacing_reduction)
        reserved = 0.0
        for p in paras:  # paragraph spacing before/after, measured in points
            p_ppr = p.find("a:pPr", NS)
            for name in ("spcBef", "spcAft"):
                el = p_ppr.find(f"a:{name}", NS) if p_ppr is not None else None
                el = el if el is not None else pchild(name)
                mult, pts = _spacing(el, size_pt)
                reserved += pts if pts is not None else (mult or 0.0) * size_pt * 1.2
        name_el = shape.find("p:nvSpPr/p:cNvPr", NS)
        return {
            "para_id": para_id,
            "slide": slide_no,
            "shape_id": shape_id,
            "para_index": para_no,
            "slide_part": slide_part,
            "shape_name": name_el.get("name", "") if name_el is not None else "",
            "placeholder": None if ph is None else {"type": ph.get("type"), "idx": ph.get("idx")},
            "text": text,
            "shape_paragraphs": all_texts,
            "box_emu": (int(round(cx)), int(round(cy))),
            "inset_emu": insets,
            "wrap": wrap,
            "autofit": autofit,
            "font_scale": font_scale,
            "line_spacing_reduction": spacing_reduction,
            "rtl": (pattr("rtl") == "1") if pattr("rtl") is not None else rtl_text,
            "align": pattr("algn"),
            "font": {
                "family": family,
                "size_pt": size_pt,
                "declared_size_pt": declared,
                "bold": rattr("b") in ("1", "true"),
                "italic": rattr("i") in ("1", "true"),
                "line_spacing": multiple or 1.0,
                "line_spacing_pt": exact,
                "latin": latin,
                "cs": cs,
            },
            "reserved_height_pt": round(reserved, 3),
            "rules": {
                "inset_emu": insets,
                "allow_shrink": autofit == "norm",
                "grow_height": autofit == "shape",
                "max_lines": EDITOR_MAX_LINES,
                "reserved_height_pt": round(reserved, 3),
            },
            "char_limit": char_limit(text),
        }
    finally:
        pkg.close()


def fit_paragraph_edit(
    pptx_path,
    para_id: str,
    new_text: str,
    rules: dict | None = None,
    *,
    slide_base: int = 1,
    para_base: int = 0,
    original_text: str | None = None,
    **fit_kwargs,
) -> dict:
    """Would the customer's edit of one paragraph still fit its shape?

    The whole shape body is measured (the other paragraphs keep their text), with
    the edited paragraph's font. The editor's character cap is applied to the
    edited paragraph (``original_text`` defaults to the deck's current text).
    """
    info = paragraph_box(pptx_path, para_id, slide_base=slide_base, para_base=para_base)
    body = list(info["shape_paragraphs"])
    body[info["para_index"] - para_base] = new_text
    merged_rules = {**info["rules"], **(rules or {})}
    merged_rules.pop("max_chars", None)
    result = fit("\n".join(body), info["box_emu"], info["font"], merged_rules, **fit_kwargs)
    limit = char_limit(info["text"] if original_text is None else original_text)
    result["char_limit"] = limit
    result["paragraph"] = info
    if len(new_text or "") > limit and result["verdict"] in ("fits", "will_shrink", "does_not_fit"):
        ar, en = _message("too_many_chars", chars=len(new_text), max_chars=limit)
        result.update(fits=False, verdict="does_not_fit", reason="too_many_chars", ar=ar, en=en)
    return result
