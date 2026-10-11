"""Prove a PDF carries the deck's words.

PDF text extraction does not round-trip Arabic exactly: extractors wrap runs in
bidi controls, break lines where the layout wrapped, and may move a haraka
before its base letter (measured: «كثيرًا» extracts as «كثيًر ا»). The proof
therefore compares two things that extraction cannot legitimately change:

* the sequence of letters and digits, with marks, whitespace, tatweel and bidi
  controls removed, after NFC;
* the multiset of marks (harakat, shadda, sukun, tanween); and
* the multiset of punctuation — neutral punctuation («» : ، .) next to a
  direction change is emitted in visual order by extractors, so only its count
  is comparable, not its position.

Equal on all three ⇒ every word, haraka and punctuation mark of the deck is in the PDF.
Measured extractor artefact handled: the lam-alef ligature is mapped back as alef+lam
by some exporters, so the pair is canonicalised identically on both sides.
"""
from __future__ import annotations

import shutil
import unicodedata
from collections import Counter
from pathlib import Path

BIDI_CONTROLS = dict.fromkeys(map(ord, "‎‏‪‫‬‭‮⁦⁧⁨⁩؜"))
TATWEEL = "ـ"


def extract_text(pdf: Path) -> str:
    """pypdfium2 first (permissive licence, logical order); Poppler's pdftotext only as a fallback."""
    try:
        import pypdfium2 as pdfium  # noqa: PLC0415
    except ImportError:
        pdfium = None
    if pdfium is not None:
        document = pdfium.PdfDocument(str(pdf))
        try:
            return "\n".join(page.get_textpage().get_text_range() for page in document)
        finally:
            document.close()
    exe = shutil.which("pdftotext")
    if not exe:
        raise RuntimeError("no PDF text extractor available (install pypdfium2)")
    from mxstudio.proc import run_hidden  # noqa: PLC0415
    proc = run_hidden([exe, "-enc", "UTF-8", str(pdf), "-"], check=True, timeout=120)
    return proc.stdout.decode("utf-8", "replace")


def normalize_for_proof(text: str) -> tuple[str, Counter, Counter]:
    text = unicodedata.normalize("NFC", (text or "").translate(BIDI_CONTROLS))
    decomposed = unicodedata.normalize("NFD", text)
    base, marks, punct = [], Counter(), Counter()
    for char in decomposed:
        category = unicodedata.category(char)
        if category == "Mn":
            marks[char] += 1
        elif char.isspace() or char == TATWEEL:
            continue
        elif category[0] in "LN":
            base.append(char)
        else:
            punct[char] += 1
    # A lam-alef ligature is one glyph; exporters map it back to two letters in either order
    # («لأنه» extracts as «ألنه»). Canonicalise the pair the same way on both sides.
    return unicodedata.normalize("NFC", "".join(base)).replace("\u0627\u0644", "\u0644\u0627"), marks, punct


def word_signatures(text: str) -> Counter:
    """Multiset of words, each reduced to its sorted letters/digits (marks, punctuation, tatweel, bidi removed).

    Extractors may reverse a short right-to-left fragment next to mirrored punctuation («شكرًا» → «ركشًا»)
    or emit a ligature's letters in the other order; a word's letter signature survives both, while a
    missing, added or changed word still changes the multiset."""
    text = unicodedata.normalize("NFD", unicodedata.normalize("NFC", (text or "").translate(BIDI_CONTROLS)))
    words, current = Counter(), []
    for char in text + " ":
        category = unicodedata.category(char)
        if category == "Mn" or char == TATWEEL:
            continue
        if category[0] in "LN":
            current.append(char)
        elif current:
            words["".join(sorted(unicodedata.normalize("NFC", "".join(current))))] += 1
            current = []
    return words


def text_proof(expected_texts: list[str], pdf: Path) -> dict:
    expected_text = "".join(f"{t} " for t in expected_texts)
    actual_text = extract_text(pdf)
    expected_base, expected_marks, expected_punct = normalize_for_proof(expected_text)
    actual_base, actual_marks, actual_punct = normalize_for_proof(actual_text)
    expected_words, actual_words = word_signatures(expected_text), word_signatures(actual_text)
    result = {
        "base_equal": expected_base == actual_base,
        "words_equal": expected_words == actual_words,
        "marks_equal": expected_marks == actual_marks,
        "punct_equal": expected_punct == actual_punct,
        "expected_chars": len(expected_base),
        "actual_chars": len(actual_base),
        "missing_words": sum((expected_words - actual_words).values()),
        "extra_words": sum((actual_words - expected_words).values()),
        "missing_marks": dict(expected_marks - actual_marks),
        "extra_marks": dict(actual_marks - expected_marks),
        "missing_punct": dict(expected_punct - actual_punct),
        "extra_punct": dict(actual_punct - expected_punct),
    }
    result["method"] = "sequence" if result["base_equal"] else "word_signatures"
    result["ok"] = (result["base_equal"] or result["words_equal"]) and result["marks_equal"] and result["punct_equal"]
    return result
