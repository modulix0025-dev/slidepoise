"""Text proof with names that end with hamza (جيداء، هناء، أسماء، شيماء، علاء، رجاء).

Operator report: theme «adventure», title «{NAME} وسرّ الهرم الكبير», name «جيداء»: PDF text extraction glued the name
to the next word in the title font (Lalezar) — «جيداءوسر» — and text_proof failed although the page was right.
The fix splits the text at the deck's name runs on BOTH sides before comparing words; a word that is really
missing, added or changed still fails (negative controls below).
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from mxstudio.factory.validate import HAMZA_NAMES, LONGEST_NAMES
from mxstudio.validators.pdf_text import compare_texts

ROOT = Path(__file__).resolve().parents[3]
TITLE = " وسرّ الهرم الكبير"
POSITIONS = {
    "start": lambda n: [{"text": n, "role": "child_name"}, {"text": TITLE}],
    "middle": lambda n: [{"text": "رحلة "}, {"text": n, "role": "child_name"}, {"text": " إلى الهرم"}],
    "end": lambda n: [{"text": "سرّ الهرم مع "}, {"text": n, "role": "child_name"}],
}


def _text(runs):
    return "".join(r["text"] for r in runs)


def test_every_hamza_name_is_in_the_proof_names():
    assert set(HAMZA_NAMES) == {"جيداء", "هناء", "أسماء", "شيماء", "علاء", "رجاء"}
    assert all(name.endswith("ء") for name in HAMZA_NAMES) and LONGEST_NAMES["ar"]


@pytest.mark.parametrize("name", HAMZA_NAMES)
@pytest.mark.parametrize("position", sorted(POSITIONS))
def test_glued_name_extraction_passes_only_with_the_name_boundary(name, position):
    runs = POSITIONS[position](name)
    expected = [_text(runs)]
    words = expected[0].split()
    i = words.index(name)
    glued = words[:]  # the extractor's artefact: name + the next (or previous) word in one token
    if i + 1 < len(glued):
        glued[i:i + 2] = [glued[i] + glued[i + 1]]
    else:
        glued[i - 1:i + 1] = [glued[i - 1] + glued[i]]
    extracted = " ".join(reversed(glued))  # right-to-left runs come out in visual order
    assert not compare_texts(expected, extracted)["ok"]  # the bug, reproduced without the fix
    assert compare_texts(expected, extracted, names=list(HAMZA_NAMES))["ok"]


@pytest.mark.parametrize("name", HAMZA_NAMES)
def test_negative_controls_still_fail_with_the_names(name):
    expected = [f"{name}{TITLE}"]
    glued = f"الكبير الهرم {name}وسرّ"
    assert compare_texts(expected, glued, list(HAMZA_NAMES))["ok"]
    assert not compare_texts(expected, f"الهرم {name}وسرّ", list(HAMZA_NAMES))["ok"]  # a word is missing
    assert not compare_texts(expected, f"الصغير الهرم {name}وسرّ", list(HAMZA_NAMES))["ok"]  # a word changed
    assert not compare_texts(expected, f"الكبير الكبير الهرم {name}وسرّ", list(HAMZA_NAMES))["ok"]  # extra word
    assert not compare_texts(expected, "الكبير الهرم وسرّ", list(HAMZA_NAMES))["ok"]  # the name is missing


def test_mirrored_quotes_count_as_quotes_but_a_missing_quote_fails():
    assert compare_texts(["قالت «مرحبا»"], "قالت »مرحبا«")["ok"]
    assert not compare_texts(["قالت «مرحبا»"], "قالت مرحبا«")["ok"]


def _title_fonts() -> list[str]:
    themes = json.loads((ROOT / "catalog" / "fonts" / "type_themes.json").read_text(encoding="utf-8"))["themes"]
    return sorted({t[k] for t in themes for k in ("ar_title", "ar_name", "ar_dedication")})


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from install_vault import files_present, install_shaped_vault  # noqa: E402


def _font_files_present(family: str) -> bool:
    return files_present([family])


needs_render = pytest.mark.skipif(not (shutil.which("soffice") and shutil.which("node")
                                       and (ROOT / "node_modules" / "pptxgenjs").is_dir()),
                                  reason="LibreOffice + Node + pptxgenjs are needed for the rendered proof")


@needs_render
@pytest.mark.parametrize("font", _title_fonts())
def test_every_title_font_with_every_hamza_name_in_every_position_passes_the_real_proof(font, tmp_path_factory):
    """Rendered deck (forked PptxGenJS) → LibreOffice PDF → text_proof, per title/name font of the 33 themes."""
    if not _font_files_present(font):
        pytest.skip(f"{font}: run `python tools/fetch_test_fonts.py` (pinned google/fonts files)")
    from mxstudio.factory.validate import _pptx_to_pdf
    from mxstudio.validators.pdf_text import text_proof
    from mxstudio.validators.synthetic_story import render
    from slidepoise.print_geometry import PageSpec

    from mxstudio.fonts.office_build import deck_family
    base = tmp_path_factory.mktemp("hamza")
    vault = install_shaped_vault(base / "installed", [font])  # what the installer registers (Office builds)
    font = deck_family(font)
    conf = base / "fonts.conf"
    conf.write_text('<?xml version="1.0"?><fontconfig><include ignore_missing="yes">/etc/fonts/fonts.conf</include>'
                    f"<dir>{vault}</dir><cachedir>{base / 'fc'}</cachedir></fontconfig>", encoding="utf-8")
    os.environ["FONTCONFIG_FILE"] = str(conf)
    os.environ["MODULEX_SOFFICE"] = shutil.which("soffice")
    page = PageSpec.preset("A4", bleed_mm=3, safe_mm=5, dpi=300)
    w, h = page.canvas_px
    slides, texts = [], []
    for number, name in enumerate(HAMZA_NAMES, 1):
        objects = []
        for row, position in enumerate(sorted(POSITIONS)):
            runs = POSITIONS[position](name)
            texts.append(_text(runs))
            objects.append({"id": f"p{number}_t{row}", "kind": "textbox", "z": 1, "runs": runs,
                            "bbox_px": [200, 300 + row * 900, w - 400, 700],
                            "style": {"font_family": font, "font_size_pt": 40, "direction": "rtl", "lang": "ar-EG",
                                      "color": "#111111", "alignment": "center", "vertical_alignment": "middle",
                                      "line_spacing_multiple": 1.0}})
        slides.append({"id": f"p{number}", "dimensions_px": [w, h], "background": "#FFFFFF", "objects": objects})
    deck = base / "titles.pptx"
    render({"title": font, "language": "ar-EG", "slides": slides}, deck, python=sys.executable)
    pdf = base / "titles.pdf"
    record = _pptx_to_pdf().convert(deck, pdf, expect_pages=len(slides), engines=["soffice"])
    from mxstudio.validators.pdf_text import boxes_from_spec
    spec = {"slides": slides}
    boxes = boxes_from_spec(spec)
    proof = text_proof(texts, pdf, names=list(HAMZA_NAMES), boxes=boxes)
    assert proof["ok"], (font, proof)
    assert not text_proof(texts + ["كلمة ناقصة"], pdf, names=list(HAMZA_NAMES), boxes=boxes)["ok"]  # negative control
    broken = [dict(b) for b in boxes]
    broken[4]["text"] = broken[4]["text"].replace("الهرم", "البحر")  # a changed word in one box
    assert not text_proof([b["text"] for b in broken], pdf, names=list(HAMZA_NAMES), boxes=broken)["ok"]
    assert record["pages"] == len(slides)
