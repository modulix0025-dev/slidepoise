"""Deterministic pre-print blockers + an advisory interface. Stdlib + optional pypdfium2/Pillow."""
from __future__ import annotations

import json
import re
import zipfile
from collections.abc import Callable
from pathlib import Path

EMU_PER_PT = 12700
BLOCKERS = {
    "empty_placeholder": ("فيه مكان صورة فاضي في المجلة.", "a picture placeholder was left empty"),
    "text_overflow": ("فيه نص أكبر من مكانه.", "text overflows its box"),
    "child_name_missing": ("اسم الطفل مش موجود على الغلاف.", "the child's name is missing on the cover"),
    "page_count": ("عدد الصفحات غير المعتمد.", "page count differs from the approved count"),
    "blank_page": ("فيه صفحة فاضية.", "a page is blank"),
    "image_only_pdf": ("الـPDF صور بس من غير نص.", "the PDF is image-only (no fonts)"),
    "font_not_certified": ("فيه خط مش معتمد أو مش متسطّب.", "a font is not certified or not installed"),
}
_SLIDE = re.compile(r"^ppt/slides/slide(\d+)\.xml$")
_SP = re.compile(rb"<p:sp>.*?</p:sp>", re.S)
_PIC_PH = re.compile(rb'<p:ph[^>]*type="pic"')
_TYPEFACE = re.compile(rb'<a:(?:latin|ea|cs) typeface="([^"]*)"')
_HIDDEN = re.compile(rb'<p:sld[^>]*\bshow="0"')
_T = re.compile(rb"<a:t>([^<]*)</a:t>")
_XFRM = re.compile(rb'<a:off x="(-?\d+)" y="(-?\d+)"/>\s*<a:ext cx="(\d+)" cy="(\d+)"/>')
_P = re.compile(rb"<a:p>.*?</a:p>", re.S)
_SZ = re.compile(rb'<a:rPr[^>]*\bsz="(\d+)"')
_FONT_OBJECTS = re.compile(rb"/(?:BaseFont|FontFile\d?|Type0)\b")


def _finding(code: str, detail) -> dict:
    ar, en = BLOCKERS[code]
    return {"code": code, "blocking": True, "ar": ar, "en": en, "detail": detail}


def _unescape(raw: bytes) -> str:
    return raw.decode("utf-8").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"') \
        .replace("&apos;", "'").replace("&amp;", "&")


def deck_facts(deck: Path) -> dict:
    slides = {}
    with zipfile.ZipFile(deck) as archive:
        for name in archive.namelist():
            match = _SLIDE.match(name)
            if not match:
                continue
            xml = archive.read(name)
            number = int(match.group(1))
            empty = sum(1 for sp in _SP.findall(xml) if _PIC_PH.search(sp))
            boxes = []
            for sp in _SP.findall(xml):
                if b"<p:txBody>" not in sp:
                    continue
                xfrm = _XFRM.search(sp)
                paragraphs = []
                for p in _P.findall(sp):
                    text = "".join(_unescape(t) for t in _T.findall(p))
                    sizes = [int(s) / 100 for s in _SZ.findall(p)]
                    faces = [f.decode("utf-8") for f in _TYPEFACE.findall(p)]
                    paragraphs.append({"text": text, "size_pt": max(sizes) if sizes else 18.0,
                                       "typeface": next((f for f in faces if f and not f.startswith("+")), "")})
                if xfrm and any(p["text"] for p in paragraphs):
                    _, _, cx, cy = (int(v) for v in xfrm.groups())
                    boxes.append({"w_pt": cx / EMU_PER_PT, "h_pt": cy / EMU_PER_PT, "paragraphs": paragraphs})
            slides[number] = {"hidden": bool(_HIDDEN.search(xml)), "empty_placeholders": empty, "text_boxes": boxes,
                              "typefaces": sorted({f.decode("utf-8") for f in _TYPEFACE.findall(xml)} - {""}),
                              "text": " ".join(_unescape(t) for t in _T.findall(xml))}
    return {"slides": dict(sorted(slides.items()))}


def pdf_facts(pdf: Path, render_blank_check: bool = True, blank_std: float = 1.5, blank_mean: float = 245.0) -> dict:
    """A blank page = featureless (tiny luminance spread) AND paper-white; a solid-colour page is content."""
    data = Path(pdf).read_bytes()
    facts = {"bytes": len(data), "fonts": len(_FONT_OBJECTS.findall(data)), "pages": None, "blank_pages": [],
             "blank_check": "skipped"}
    try:
        import pypdfium2 as pdfium  # noqa: PLC0415
    except ImportError:  # pragma: no cover - OM may not have it; count pages via the raw bytes instead
        facts["pages"] = len(re.findall(rb"/Type\s*/Page(?![sR\w])", data))
        return facts
    document = pdfium.PdfDocument(str(pdf))
    try:
        facts["pages"] = len(document)
        if facts["fonts"] == 0:
            # fonts are often inside compressed object streams; ask the parser instead of the raw bytes
            facts["fonts"] = sum(1 for page in document for obj in page.get_objects() if obj.type == 1)
        if render_blank_check:
            import numpy as np  # noqa: PLC0415
            for number, page in enumerate(document, 1):
                image = np.asarray(page.render(scale=0.25).to_pil().convert("L"), dtype=float)
                if image.std() < blank_std and image.mean() >= blank_mean:
                    facts["blank_pages"].append(number)
            facts["blank_check"] = "rendered"
    finally:
        document.close()
    return facts


def _default_fit() -> Callable | None:
    try:
        from slidepoise.arabic.fit import fit_text  # noqa: PLC0415 - Studio side
    except ImportError:
        try:
            import mx_textfit  # noqa: PLC0415 - OM side (vendored next to this library)
        except ImportError:
            return None

        def fit(text, w_pt, h_pt, family, size_pt):
            result = mx_textfit.fit(text, (int(w_pt * EMU_PER_PT), int(h_pt * EMU_PER_PT)),
                                    {"family": family, "size_pt": size_pt}, {"min_size_pt": size_pt})
            return bool(result["fits"])
        return fit

    def fit(text, w_pt, h_pt, family, size_pt):
        try:
            return fit_text(text, w_pt, h_pt, family, max_size_pt=size_pt, min_size_pt=size_pt, inset_pt=0.0).fits
        except LookupError:
            return True  # an unknown family is reported by the font check, not as an overflow
    return fit


def run_gate(deck: Path, pdf: Path, *, approved_pages: int, child_name: str, cover_slide: int = 1,
             certified_fonts: set[str] | None = None, installed_fonts: set[str] | None = None,
             fit: Callable | None = None, check_overflow: bool = True) -> dict:
    """All deterministic blockers for one order. Returns {"hold", "findings", "facts"}; never writes state."""
    deck_info = deck_facts(Path(deck))
    pdf_info = pdf_facts(Path(pdf))
    findings = []
    visible = {n: s for n, s in deck_info["slides"].items() if not s["hidden"]}
    empty = {n: s["empty_placeholders"] for n, s in visible.items() if s["empty_placeholders"]}
    if empty:
        findings.append(_finding("empty_placeholder", {"slides": empty}))
    if check_overflow:
        fit = fit or _default_fit()
        if fit is not None:
            overflowing = []
            for number, slide in visible.items():
                for box in slide["text_boxes"]:
                    text = "\n".join(p["text"] for p in box["paragraphs"])
                    first = box["paragraphs"][0]
                    if not fit(text, box["w_pt"], box["h_pt"], first["typeface"], first["size_pt"]):
                        overflowing.append({"slide": number, "text": text[:60]})
            if overflowing:
                findings.append(_finding("text_overflow", overflowing))
    cover = deck_info["slides"].get(cover_slide, {})
    if child_name and child_name not in cover.get("text", ""):
        findings.append(_finding("child_name_missing", {"cover_slide": cover_slide}))
    if pdf_info["pages"] != approved_pages:
        findings.append(_finding("page_count", {"pdf": pdf_info["pages"], "approved": approved_pages}))
    if pdf_info["blank_pages"]:
        findings.append(_finding("blank_page", {"pages": pdf_info["blank_pages"]}))
    if pdf_info["fonts"] == 0:
        findings.append(_finding("image_only_pdf", {"fonts": 0}))
    if certified_fonts is not None or installed_fonts is not None:
        used = sorted({face for s in visible.values() for face in s["typefaces"] if not face.startswith("+")})
        bad = [face for face in used if (certified_fonts is not None and face not in certified_fonts)
               or (installed_fonts is not None and face not in installed_fonts)]
        if bad:
            findings.append(_finding("font_not_certified", {"fonts": bad}))
    return {"hold": bool(findings), "findings": findings,
            "facts": {"slides": len(deck_info["slides"]), "visible_slides": len(visible), **pdf_info}}


ADVISORY_CHECKS = ("wrong_gender_figure", "figure_identity_drift", "scene_page_mismatch", "visible_artefacts")


def advisory_review(judge: Callable[[str, dict], dict] | None, pages: list[dict]) -> list[dict]:
    """Ask a vision judge about each page; results are advisory only (they cannot hold a job)."""
    if judge is None:
        return [{"check": "advisory", "advisory": True, "status": "not_configured"}]
    out = []
    for page in pages:
        for check in ADVISORY_CHECKS:
            verdict = judge(check, page) or {}
            out.append({"page": page.get("page"), "check": check, "advisory": True,
                        "concern": bool(verdict.get("concern")), "reason": str(verdict.get("reason", ""))[:300]})
    return out


def qa_sheet(gate: dict, advisory: list[dict], out_json: Path) -> Path:
    """The per-order QA record attached beside the PDF (`…_final.pdf.qa.json`)."""
    record = {"schema": "mx_qagate/1", "hold": gate["hold"], "blockers": gate["findings"], "facts": gate["facts"],
              "advisory": advisory, "advisory_changes_state": False}
    out_json = Path(out_json)
    out_json.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    return out_json
