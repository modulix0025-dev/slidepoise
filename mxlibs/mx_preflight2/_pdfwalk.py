"""Walk PDF pages with pikepdf: placed images (with CTM), colour usage, fonts, transparency.

Rule enforced: facts come from the content streams as drawn (the current
transformation matrix is tracked through q/Q/cm and nested Form XObjects), not
from the mere presence of an object in the file.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

import pikepdf

IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
MAX_DEPTH = 12

_NAME_FAMILY = {
    "/DeviceRGB": "rgb",
    "/RGB": "rgb",
    "/CalRGB": "rgb",
    "/DeviceCMYK": "cmyk",
    "/CMYK": "cmyk",
    "/DeviceGray": "gray",
    "/G": "gray",
    "/CalGray": "gray",
    "/Lab": "lab",
    "/Pattern": "pattern",
    "/Indexed": "indexed",
    "/I": "indexed",
}


def mul(m1: tuple, m2: tuple) -> tuple:
    """m1 x m2 for PDF matrices [a b c d e f] (row-vector convention)."""
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (
        a1 * a2 + b1 * c2,
        a1 * b2 + b1 * d2,
        c1 * a2 + d1 * c2,
        c1 * b2 + d1 * d2,
        e1 * a2 + f1 * c2 + e2,
        e1 * b2 + f1 * d2 + f2,
    )


def _num(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _get(dictionary, key, default=None):
    try:
        if dictionary is not None and key in dictionary:
            return dictionary[key]
    except (TypeError, ValueError, pikepdf.PdfError):
        return default
    return default


def colour_family(cs, resources=None, depth: int = 0) -> tuple[str, str]:
    """(family, label) of a colour space object. family: rgb, cmyk, gray, lab, spot, pattern, unknown."""
    if cs is None or depth > 6:
        return "unknown", "none"
    if isinstance(cs, pikepdf.Name) or isinstance(cs, str):
        name = str(cs)
        if name in _NAME_FAMILY:
            return _NAME_FAMILY[name], name.lstrip("/")
        named = _get(_get(resources, "/ColorSpace"), name)
        if named is not None:
            return colour_family(named, resources, depth + 1)
        return "unknown", name.lstrip("/")
    if isinstance(cs, pikepdf.Array) and len(cs):
        head = str(cs[0])
        if head == "/ICCBased":
            n = int(_num(_get(cs[1], "/N", 0)))
            return {1: "gray", 3: "rgb", 4: "cmyk"}.get(n, "unknown"), f"ICCBased(N={n})"
        if head in ("/Indexed", "/I"):
            family, label = colour_family(cs[1], resources, depth + 1)
            return family, f"Indexed({label})"
        if head == "/Separation":
            return "spot", f"Separation({str(cs[1]).lstrip('/')})"
        if head == "/DeviceN":
            return "spot", "DeviceN"
        if head == "/Pattern":
            return "pattern", "Pattern"
        if head in _NAME_FAMILY:
            return _NAME_FAMILY[head], head.lstrip("/")
    return "unknown", str(cs)[:40]


@dataclass
class Placement:
    page: int
    name: str
    width_px: int
    height_px: int
    placed_w_pt: float
    placed_h_pt: float
    colour_family: str
    colour_label: str
    inline: bool = False
    objgen: tuple = (0, 0)

    @property
    def dpi_x(self) -> float:
        return self.width_px / (self.placed_w_pt / 72.0) if self.placed_w_pt > 1e-6 else float("inf")

    @property
    def dpi_y(self) -> float:
        return self.height_px / (self.placed_h_pt / 72.0) if self.placed_h_pt > 1e-6 else float("inf")

    @property
    def dpi(self) -> float:
        return min(self.dpi_x, self.dpi_y)

    def as_dict(self) -> dict:
        return {
            "page": self.page,
            "name": self.name,
            "px": [self.width_px, self.height_px],
            "placed_mm": [round(self.placed_w_pt * 25.4 / 72, 2), round(self.placed_h_pt * 25.4 / 72, 2)],
            "dpi_x": round(self.dpi_x, 1),
            "dpi_y": round(self.dpi_y, 1),
            "dpi": round(self.dpi, 1),
            "colour": self.colour_label,
            "inline": self.inline,
        }


@dataclass
class PageFacts:
    index: int
    images: list = field(default_factory=list)
    colour_ops: Counter = field(default_factory=Counter)  # family -> count of colour-setting operators
    colour_labels: Counter = field(default_factory=Counter)  # label -> count (ops, images, shadings)
    shadings: int = 0
    transparency: list = field(default_factory=list)
    fonts_used: set = field(default_factory=set)
    text_ops: int = 0


def _transparency_of_gs(gs) -> list[str]:
    reasons = []
    smask = _get(gs, "/SMask")
    if smask is not None and str(smask) != "/None":
        reasons.append("soft mask")
    for key in ("/ca", "/CA"):
        value = _get(gs, key)
        if value is not None and _num(value) < 0.999:
            reasons.append(f"constant alpha {key[1:]}={_num(value):g}")
    bm = _get(gs, "/BM")
    if bm is not None:
        names = [str(v) for v in bm] if isinstance(bm, pikepdf.Array) else [str(bm)]
        if not any(n in ("/Normal", "/Compatible") for n in names):
            reasons.append(f"blend mode {names[0].lstrip('/')}")
    return reasons


def walk_page(pdf: pikepdf.Pdf, index: int) -> PageFacts:
    page = pdf.pages[index]
    facts = PageFacts(index=index + 1)
    group = _get(page.obj, "/Group")
    if group is not None and str(_get(group, "/S")) == "/Transparency":
        facts.transparency.append("page transparency group")
    user_unit = _num(_get(page.obj, "/UserUnit", 1)) or 1.0
    base = (user_unit, 0.0, 0.0, user_unit, 0.0, 0.0)
    resources = _get(page.obj, "/Resources")
    try:
        instructions = pikepdf.parse_content_stream(page)
    except pikepdf.PdfError:
        instructions = []
    _walk(pdf, instructions, resources, base, facts, depth=0, seen=set())
    return facts


def _walk(pdf, instructions, resources, ctm, facts: PageFacts, depth: int, seen: set) -> None:
    stack: list = []
    fill = stroke = ("gray", "DeviceGray")
    for item in instructions:
        op = str(item.operator)
        operands = item.operands
        if op == "q":
            stack.append((ctm, fill, stroke))
        elif op == "Q":
            if stack:
                ctm, fill, stroke = stack.pop()
        elif op == "cm" and len(operands) == 6:
            ctm = mul(tuple(_num(v) for v in operands), ctm)
        elif op in ("rg", "RG"):
            facts.colour_ops["rgb"] += 1
            facts.colour_labels["DeviceRGB"] += 1
        elif op in ("k", "K"):
            facts.colour_ops["cmyk"] += 1
            facts.colour_labels["DeviceCMYK"] += 1
        elif op in ("g", "G"):
            facts.colour_ops["gray"] += 1
            facts.colour_labels["DeviceGray"] += 1
        elif op in ("cs", "CS") and operands:
            fam = colour_family(operands[0], resources)
            if op == "cs":
                fill = fam
            else:
                stroke = fam
        elif op in ("sc", "scn", "SC", "SCN"):
            family, label = fill if op in ("sc", "scn") else stroke
            facts.colour_ops[family] += 1
            facts.colour_labels[label] += 1
        elif op == "sh" and operands:
            facts.shadings += 1
            shading = _get(_get(resources, "/Shading"), str(operands[0]))
            family, label = colour_family(_get(shading, "/ColorSpace"), resources)
            facts.colour_labels[f"shading:{label}"] += 1
            facts.colour_ops[family] += 1
        elif op == "gs" and operands:
            gs = _get(_get(resources, "/ExtGState"), str(operands[0]))
            for reason in _transparency_of_gs(gs):
                if reason not in facts.transparency:
                    facts.transparency.append(reason)
        elif op == "Tf" and operands:
            facts.fonts_used.add(str(operands[0]))
        elif op in ("Tj", "TJ", "'", '"'):
            facts.text_ops += 1
        elif op == "INLINE IMAGE" and operands:
            image = operands[0]
            w_pt, h_pt = math.hypot(ctm[0], ctm[1]), math.hypot(ctm[2], ctm[3])
            try:
                width, height = int(image.width), int(image.height)
                cs = image.colorspace
            except Exception:  # noqa: BLE001
                continue
            family, label = colour_family(
                pikepdf.Name(cs) if isinstance(cs, str) and cs.startswith("/") else cs, resources
            )
            facts.images.append(Placement(facts.index, "inline", width, height, w_pt, h_pt, family, label, True))
            facts.colour_labels[f"image:{label}"] += 1
        elif op == "Do" and operands:
            name = str(operands[0])
            xobj = _get(_get(resources, "/XObject"), name)
            if xobj is None:
                continue
            subtype = str(_get(xobj, "/Subtype"))
            if subtype == "/Image":
                if bool(_get(xobj, "/ImageMask", False)):
                    continue  # a stencil mask paints with the current fill colour
                family, label = colour_family(_get(xobj, "/ColorSpace"), resources)
                if _get(xobj, "/ColorSpace") is None and "/JPXDecode" in str(_get(xobj, "/Filter")):
                    family, label = "unknown", "JPX(embedded)"
                if _get(xobj, "/SMask") is not None:
                    if "image soft mask" not in facts.transparency:
                        facts.transparency.append("image soft mask")
                w_pt, h_pt = math.hypot(ctm[0], ctm[1]), math.hypot(ctm[2], ctm[3])
                facts.images.append(
                    Placement(
                        facts.index,
                        name,
                        int(_num(_get(xobj, "/Width"))),
                        int(_num(_get(xobj, "/Height"))),
                        w_pt,
                        h_pt,
                        family,
                        label,
                        objgen=xobj.objgen,
                    )
                )
                facts.colour_labels[f"image:{label}"] += 1
            elif subtype == "/Form":
                key = xobj.objgen
                if depth >= MAX_DEPTH or (key != (0, 0) and key in seen):
                    continue
                group = _get(xobj, "/Group")
                if group is not None and str(_get(group, "/S")) == "/Transparency":
                    if "form transparency group" not in facts.transparency:
                        facts.transparency.append("form transparency group")
                matrix = _get(xobj, "/Matrix")
                form_ctm = mul(tuple(_num(v) for v in matrix), ctm) if matrix is not None and len(matrix) == 6 else ctm
                try:
                    inner = pikepdf.parse_content_stream(xobj)
                except pikepdf.PdfError:
                    continue
                _walk(pdf, inner, _get(xobj, "/Resources", resources), form_ctm, facts, depth + 1, seen | {key})


# --------------------------------------------------------------------------- fonts
def _font_record(font) -> dict:
    subtype = str(_get(font, "/Subtype"))
    base = str(_get(font, "/BaseFont", "")).lstrip("/")
    if subtype == "/Type3":
        return {"name": base or "Type3", "subtype": "Type3", "embedded": True, "file": "CharProcs"}
    descriptor = _get(font, "/FontDescriptor")
    if subtype == "/Type0":
        descendants = _get(font, "/DescendantFonts")
        if descendants is not None and len(descendants):
            descriptor = _get(descendants[0], "/FontDescriptor")
    kind = None
    for key in ("/FontFile", "/FontFile2", "/FontFile3"):
        if _get(descriptor, key) is not None:
            kind = key.lstrip("/")
            break
    return {"name": base, "subtype": subtype.lstrip("/"), "embedded": kind is not None, "file": kind}


def _fonts_in_resources(resources, out: dict, page_no: int, depth: int, seen: set) -> None:
    if resources is None or depth > MAX_DEPTH:
        return
    fonts = _get(resources, "/Font")
    if fonts is not None:
        for _name, font in fonts.items():
            key = font.objgen if font.objgen != (0, 0) else id(font)
            if key not in out:
                out[key] = {**_font_record(font), "pages": []}
                if str(_get(font, "/Subtype")) == "/Type3":
                    _fonts_in_resources(_get(font, "/Resources"), out, page_no, depth + 1, seen)
            if page_no not in out[key]["pages"]:
                out[key]["pages"].append(page_no)
    for group in ("/XObject", "/Pattern"):
        children = _get(resources, group)
        if children is None:
            continue
        for _name, child in children.items():
            key = child.objgen
            if key in seen:
                continue
            if group == "/XObject" and str(_get(child, "/Subtype")) != "/Form":
                continue
            _fonts_in_resources(_get(child, "/Resources"), out, page_no, depth + 1, seen | {key})


def fonts_of(pdf: pikepdf.Pdf) -> list[dict]:
    out: dict = {}
    for index, page in enumerate(pdf.pages):
        _fonts_in_resources(_get(page.obj, "/Resources"), out, index + 1, 0, set())
        for annot in _get(page.obj, "/Annots", []) or []:
            appearance = _get(_get(annot, "/AP"), "/N")
            if isinstance(appearance, pikepdf.Stream):
                _fonts_in_resources(_get(appearance, "/Resources"), out, index + 1, 1, set())
    return list(out.values())


def output_intents(pdf: pikepdf.Pdf) -> list[dict]:
    from . import _icc

    found = []
    for intent in _get(pdf.Root, "/OutputIntents", []) or []:
        profile = _get(intent, "/DestOutputProfile")
        record = {
            "S": str(_get(intent, "/S", "")).lstrip("/"),
            "identifier": str(_get(intent, "/OutputConditionIdentifier", "")),
            "info": str(_get(intent, "/Info", "")),
        }
        if isinstance(profile, pikepdf.Stream):
            try:
                record.update({f"profile_{k}": v for k, v in _icc.facts(profile.read_bytes()).items()})
            except pikepdf.PdfError:
                record["profile_error"] = "unreadable"
        found.append(record)
    return found


def box_mm(page, key: str) -> tuple[float, float, float, float] | None:
    """[x0, y0, x1, y1] of a page box in mm (PDF user space), honouring UserUnit."""
    box = page.mediabox if key == "/MediaBox" else _get(page.obj, key)
    if box is None:
        return None
    unit = (_num(_get(page.obj, "/UserUnit", 1)) or 1.0) * 25.4 / 72.0
    x0, y0, x1, y1 = (_num(v) for v in box)
    return (min(x0, x1) * unit, min(y0, y1) * unit, max(x0, x1) * unit, max(y0, y1) * unit)
