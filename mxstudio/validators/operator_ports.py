"""Faithful ports of the operator's own rules, used to validate what the Studio emits.

The two functions below the PORT markers are copied verbatim from the brief's
Appendix B (OM `app/services/story_engine.py` and Console
`execution_console/services/magazine_pptx.py`). They are not "improved": a
template is valid only if the operator's unchanged code accepts it, so the
validators run that code. The sha256 of each verbatim block is pinned by
tests/mag/test_operator_ports.py; the Integration Kit compares the same blocks
with the real files on the operator's machine.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

log = logging.getLogger("mxstudio.operator_ports")

# ---- PORT BEGIN: OM app/services/story_engine.py (Appendix B.1, verbatim) ----
def replace_in_paragraph(paragraph, old, new):
    """
    استبدال النص حتى لو متقسم على أكتر من run.
    المحاولة 1: بحث في كل run لوحده
    المحاولة 2: لم النص كله وبحث cross-run
    """
    runs = paragraph.runs
    if not runs:
        return False

    simple_found = False
    for run in runs:
        if old in run.text:
            run.text = run.text.replace(old, new)
            simple_found = True

    if simple_found:
        return True

    full_text = "".join(run.text for run in runs)
    if old not in full_text:
        return False

    new_full_text = full_text.replace(old, new)
    runs[0].text = new_full_text
    for i in range(1, len(runs)):
        runs[i].text = ""
    return True


def replace_in_shape(shape, old, new):
    """استبدال النص في أي shape بما فيها الـ GROUP shapes"""
    count = 0
    if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
        for sub_shape in shape.shapes:
            count += replace_in_shape(sub_shape, old, new)
    if shape.has_text_frame:
        for para in shape.text_frame.paragraphs:
            if replace_in_paragraph(para, old, new):
                count += 1
    return count
# ---- PORT END: story_engine.py ----

# ---- PORT BEGIN: Console magazine_pptx.py (Appendix B.4, verbatim) ----
ENTRY_STEM = "modulex_scene_{:02d}"
SCENE_LABEL_RE = re.compile(r"(?:image\s+)?scene[_\-\s]*(\d+)", re.IGNORECASE)
SLIDE_NAME_RE = re.compile(r"slide[_\-\s]*(\d+)", re.IGNORECASE)

#: An EMPTY picture placeholder in slideN.xml: <p:sp> carrying <p:ph type="pic">.
#: A FILLED one is a <p:pic> that still carries the same <p:ph>, so counting
#: `<p:ph type="pic"` alone cannot tell full from empty — the <p:pic> wrapper is
#: what changes. Both facts are read straight out of the zip; no python-pptx
#: needed, so this works even where the engine does not.
_PH_PIC_RE = re.compile(rb'<p:ph[^>]*type="pic"')
_SLIDE_RE = re.compile(r"^ppt/slides/slide(\d+)\.xml$")

def deck_picture_slots(pptx_path) -> dict:
    """{slide_no: n_picture_placeholders} for the deck. {} on any problem."""
    out = {}
    try:
        import zipfile
        with zipfile.ZipFile(str(pptx_path)) as z:
            for name in z.namelist():
                m = _SLIDE_RE.match(name)
                if not m:
                    continue
                n = len(_PH_PIC_RE.findall(z.read(name)))
                if n:
                    out[int(m.group(1))] = n
    except Exception:  # noqa: BLE001
        log.debug("deck slot scan failed for %s", pptx_path, exc_info=True)
    return out
# ---- PORT END: magazine_pptx.py ----


def replay_generate_story(template: Path, base_name: str, child_name: str, extra: dict[str, str] | None = None,
                          out_path: Path | None = None) -> dict:
    """Replay OM's two replacement steps in OM's order on a copy of the template.

    STEP 1: base_name -> child_name in every shape of every slide.
    STEP 2: each `extra` entry (old -> new with "{child_name}") in the same way.
    Returns per-step counts (paragraphs replaced, as OM counts them) and the text
    of every paragraph afterwards. Mirrors Appendix B.1; the exact STEP 2 loop
    shape is re-verified on device by the Integration Kit.
    """
    prs = Presentation(str(template))
    step1 = 0
    for slide in prs.slides:
        for shape in slide.shapes:
            step1 += replace_in_shape(shape, base_name, child_name)
    step2: dict[str, int] = {}
    for old, new in (extra or {}).items():
        target = new.replace("{child_name}", child_name)
        hits = 0
        for slide in prs.slides:
            for shape in slide.shapes:
                hits += replace_in_shape(shape, old, target)
        step2[old] = hits
    texts = [paragraph.text for slide in prs.slides for shape in slide.shapes if shape.has_text_frame
             for paragraph in shape.text_frame.paragraphs]
    if out_path is not None:
        prs.save(str(out_path))
    return {"step1": step1, "step2": step2, "total": step1 + sum(step2.values()), "paragraph_texts": texts}


def name_run_integrity(pptx_path: Path, base_name: str) -> list[dict]:
    """Every occurrence of base_name and whether it lies whole inside one run.

    A name split across runs is still found by OM's cross-run fallback, but that
    fallback collapses the whole paragraph into its first run and loses every
    other run's formatting — so the factory requires whole-run names.
    """
    prs = Presentation(str(pptx_path))
    found = []
    for number, slide in enumerate(prs.slides, 1):
        for shape in slide.shapes:
            if not shape.has_text_frame:
                continue
            for p_index, paragraph in enumerate(shape.text_frame.paragraphs):
                text = "".join(run.text for run in paragraph.runs)
                count = text.count(base_name)
                whole = sum(run.text.count(base_name) for run in paragraph.runs)
                if count:
                    found.append({"slide": number, "shape": shape.name, "paragraph": p_index,
                                  "occurrences": count, "whole_run_occurrences": whole, "ok": whole == count})
    return found
