"""Prove a PDF carries the deck's words.

PDF text extraction does not round-trip Arabic exactly: extractors wrap runs in
bidi controls, break lines where the layout wrapped, and may move a haraka
before its base letter (measured: «كثيرًا» extracts as «كثيًر ا»). The proof
therefore compares two things that extraction cannot legitimately change:

* the sequence of base characters (letters, digits, punctuation) with marks,
  whitespace, tatweel and bidi controls removed, after NFC; and
* the multiset of marks (harakat, shadda, sukun, tanween).

Equal on both ⇒ every word and every haraka of the deck is in the PDF.
"""
from __future__ import annotations

import shutil
import unicodedata
from collections import Counter
from pathlib import Path

BIDI_CONTROLS = dict.fromkeys(map(ord, "‎‏‪‫‬‭‮⁦⁧⁨⁩؜"))
TATWEEL = "ـ"


def extract_text(pdf: Path) -> str:
    exe = shutil.which("pdftotext")
    if exe:
        from mxstudio.proc import run_hidden  # noqa: PLC0415
        proc = run_hidden([exe, "-enc", "UTF-8", str(pdf), "-"], check=True, timeout=120)
        return proc.stdout.decode("utf-8", "replace")
    import pypdfium2 as pdfium  # noqa: PLC0415 - permissive fallback when Poppler is absent
    document = pdfium.PdfDocument(str(pdf))
    try:
        return "\n".join(page.get_textpage().get_text_range() for page in document)
    finally:
        document.close()


def normalize_for_proof(text: str) -> tuple[str, Counter]:
    text = unicodedata.normalize("NFC", (text or "").translate(BIDI_CONTROLS))
    decomposed = unicodedata.normalize("NFD", text)
    base, marks = [], Counter()
    for char in decomposed:
        if unicodedata.category(char) == "Mn":
            marks[char] += 1
        elif not char.isspace() and char != TATWEEL:
            base.append(char)
    return unicodedata.normalize("NFC", "".join(base)), marks


def text_proof(expected_texts: list[str], pdf: Path) -> dict:
    expected_base, expected_marks = normalize_for_proof("".join(expected_texts))
    actual_base, actual_marks = normalize_for_proof(extract_text(pdf))
    return {
        "base_equal": expected_base == actual_base,
        "marks_equal": expected_marks == actual_marks,
        "ok": expected_base == actual_base and expected_marks == actual_marks,
        "expected_chars": len(expected_base),
        "actual_chars": len(actual_base),
        "missing_marks": dict(expected_marks - actual_marks),
        "extra_marks": dict(actual_marks - expected_marks),
    }
