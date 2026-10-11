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
Measured extractor artefacts handled (each canonicalised identically on BOTH sides, so a word that is
really missing, added or changed still fails):
* the lam-alef ligature is mapped back as alef+lam by some exporters;
* bidi-mirrored punctuation («» () [] {} <> ‹›) is emitted as its mirror in right-to-left runs, so a pair
  counts as one kind of mark;
* in title fonts whose letters sit at different heights (Ruqaa stacking, a hamza or waw below the baseline:
  Aref Ruqaa, Qahiri, Mirza, Rakkas, Beiruti…) pdfium INVENTS line breaks inside a word («جيداء» → «داء|ي|ج»,
  «إلى» → «لى|إ») and may move a raised letter into the neighbouring word. Separators pdfium generated are known
  (FPDFText_IsGenerated); up to 5 ADJACENT unmatched pieces are joined when their letters are exactly one missing
  deck word (or two adjacent ones) — first across generated separators only, then also across spaces LibreOffice
  wrote inside a word. Nothing is accepted that is not a missing deck word;
* a child's name that ENDS WITH HAMZA (جيداء، هناء، أسماء، شيماء، علاء، رجاء) followed by a word in a title
  font (e.g. Lalezar) is extracted glued to that word («جيداءوسر»): the name is its own run in the deck, so the
  text is split at the boundaries of the given names before words are compared.
"""
from __future__ import annotations

import shutil
import unicodedata
from collections import Counter
from pathlib import Path

BIDI_CONTROLS = dict.fromkeys(map(ord, "‎‏‪‫‬‭‮⁦⁧⁨⁩؜"))
MIRROR_PAIRS = {"»": "«", ")": "(", "]": "[", "}": "{", ">": "<", "›": "‹", "﴿": "﴾"}
TATWEEL = "ـ"


GENERATED = "\x1e"  # marks a separator the extractor invented (not a character of the PDF)


def extract_text_marked(pdf: Path) -> str:
    """The PDF's real characters in pdfium order; separators pdfium generated become GENERATED."""
    try:
        import pypdfium2 as pdfium  # noqa: PLC0415
        import pypdfium2.raw as raw  # noqa: PLC0415
    except ImportError:
        return extract_text(pdf)
    document = pdfium.PdfDocument(str(pdf))
    pages = []
    try:
        for page in document:
            textpage = page.get_textpage()
            chars = []
            for index in range(textpage.count_chars()):
                char = chr(raw.FPDFText_GetUnicode(textpage.raw, index))
                chars.append(GENERATED if raw.FPDFText_IsGenerated(textpage.raw, index) and char.isspace() else char)
            pages.append("".join(chars))
    finally:
        document.close()
    return "\n".join(pages)


def extract_text_geometric(pdf: Path) -> str:
    """The PDF's real characters with word gaps decided by geometry along each glyph's own baseline (rotated text:
    pdfium invents a break after every glyph and loses the spaces). A space where the advance gap exceeds 0.18 em,
    a new line where the baseline jumps more than 0.6 em."""
    import ctypes  # noqa: PLC0415
    import math  # noqa: PLC0415
    try:
        import pypdfium2 as pdfium  # noqa: PLC0415
        import pypdfium2.raw as raw  # noqa: PLC0415
    except ImportError:
        return extract_text(pdf)
    document = pdfium.PdfDocument(str(pdf))
    pages = []
    try:
        for page in document:
            textpage = page.get_textpage()
            out, prev = [], None
            for index in range(textpage.count_chars()):
                if raw.FPDFText_IsGenerated(textpage.raw, index):
                    continue
                char = chr(raw.FPDFText_GetUnicode(textpage.raw, index))
                if char in "\r\n":
                    continue
                x, y = ctypes.c_double(), ctypes.c_double()
                raw.FPDFText_GetCharOrigin(textpage.raw, index, ctypes.byref(x), ctypes.byref(y))
                size = raw.FPDFText_GetFontSize(textpage.raw, index) or 12.0
                angle = raw.FPDFText_GetCharAngle(textpage.raw, index)
                dx, dy = math.cos(angle), math.sin(angle)
                if char.strip():
                    left, bottom, right, top = textpage.get_charbox(index)
                    width = abs((right - left) * dx + (top - bottom) * dy)
                    if prev is not None:
                        px, py, pw, psize = prev
                        vx, vy = x.value - px, y.value - py
                        along, across, em = vx * dx + vy * dy, -vx * dy + vy * dx, max(size, psize)
                        if abs(across) > 0.6 * em:
                            out.append("\n")
                        elif along - pw > 0.18 * em or along < -0.3 * em:
                            out.append(" ")
                    prev = (x.value, y.value, width, size)
                out.append(char)
            pages.append("".join(out))
    finally:
        document.close()
    return "\n".join(pages)


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
            punct[MIRROR_PAIRS.get(char, char)] += 1
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


def split_at_names(text: str, names: list[str] | None) -> str:
    """Put a space where a given name touches a letter on either side («جيداءوسر» → «جيداء وسر»)."""
    import re  # noqa: PLC0415
    out = unicodedata.normalize("NFC", (text or "").translate(BIDI_CONTROLS))
    for name in sorted({n for n in (names or []) if n and n.strip()}, key=len, reverse=True):
        pattern = re.escape(unicodedata.normalize("NFC", name.strip()))
        out = re.sub(rf"(?<=\w)({pattern})", r" \1", out)
        out = re.sub(rf"({pattern})(?=\w)", r"\1 ", out)
    return out


def _signature(word: str) -> str:
    return "".join(sorted(unicodedata.normalize("NFC", word)))


def _tokens(text: str) -> list[tuple[str, bool]]:
    """(word, joined to the previous word only by generated separators) for every word of the text.
    Generated separators: GENERATED, CR and LF (pdfium's invented line breaks); anything else is real."""
    text = unicodedata.normalize("NFD", unicodedata.normalize("NFC", (text or "").translate(BIDI_CONTROLS)))
    out, current, only_generated, seen_real = [], [], True, False
    for char in text + " ":
        category = unicodedata.category(char)
        if category == "Mn" or char == TATWEEL:
            continue
        if category[0] in "LN":
            if not current:
                only_generated = not seen_real
                seen_real = False
            current.append(char)
            continue
        if current:
            out.append((unicodedata.normalize("NFC", "".join(current)), only_generated and bool(out)))
            current = []
            seen_real = False
        if char not in (GENERATED, "\r", "\n"):
            seen_real = True
    return out


def heal_fragments(expected: Counter, tokens: list[tuple[str, bool]], max_window: int = 5) -> tuple[Counter, int]:
    """Join consecutive pieces when their letters are exactly one or two missing deck words and every piece is
    otherwise unmatched. Pass 1 crosses only GENERATED separators; pass 2 also crosses spaces the PDF itself carries
    (LibreOffice writes a space inside some words of stacked/decorative fonts: «هناء» → «ناء ه», «وتغمز» →
    «ز م غ ت و»). Both passes join at most `max_window` ADJACENT pieces and only into words the deck has and the
    PDF otherwise lacks: a word that is really missing or changed has no letters to be rebuilt from, so it still
    fails. Returns (word-signature multiset, joins made)."""
    best = None
    for sizes in (range(2, max_window + 1), range(max_window, 1, -1)):  # «قالت» vs «وقالت»: try both orders
        groups = [[_signature(word), joined] for word, joined in tokens]
        healed = _heal_pass(expected, groups, sizes, cross_real=False)
        healed += _heal_pass(expected, groups, sizes, cross_real=True)
        actual = Counter(g[0] for g in groups)
        score = (sum((expected - actual).values()), healed)
        if best is None or score < best[0]:
            best = (score, actual, healed)
    return best[1], best[2]


def _heal_pass(expected: Counter, groups: list, sizes, cross_real: bool) -> int:
    healed = 0
    changed = True
    while changed:
        changed = False
        actual = Counter(g[0] for g in groups)
        missing, extra = expected - actual, actual - expected
        if not missing:
            break
        pairs = {}
        missing_list = list(missing.elements())
        for a in range(len(missing_list)):
            for b in range(a + 1, len(missing_list)):
                pairs.setdefault(_signature(missing_list[a] + missing_list[b]), (missing_list[a], missing_list[b]))
        for size in sizes:
            for start in range(0, len(groups) - size + 1):
                window = groups[start:start + size]
                if not cross_real and not all(g[1] for g in window[1:]):
                    continue  # a real space inside: not in this pass
                merged = _signature("".join(g[0] for g in window))
                if merged in missing:
                    replacement = [[merged, window[0][1]]]
                elif merged in pairs:
                    first, second = pairs[merged]
                    replacement = [[first, window[0][1]], [second, False]]
                else:
                    continue
                # accept only when the difference to the deck strictly shrinks (a piece that alone looked like a deck
                # word may be part of a longer one: «جنمة» + «و» = «ونجمة»); the final verdict stays exact equality
                after = actual - Counter(g[0] for g in window) + Counter(r[0] for r in replacement)
                if sum(((expected - after) + (after - expected)).values()) >= sum((missing + extra).values()):
                    continue
                groups[start:start + size] = replacement
                healed += 1
                changed = True
                break
            if changed:
                break
    return healed


def _classify(text: str) -> tuple[Counter, Counter, Counter]:
    """Letters/digits, marks and punctuation of a text as multisets (whitespace, tatweel and bidi controls ignored)."""
    letters, marks, punct = Counter(), Counter(), Counter()
    for char in unicodedata.normalize("NFD", unicodedata.normalize("NFC", (text or "").translate(BIDI_CONTROLS))):
        category = unicodedata.category(char)
        if category == "Mn":
            marks[char] += 1
        elif char.isspace() or char == TATWEEL or char == GENERATED:
            continue
        elif category[0] in "LN":
            letters[char] += 1
        else:
            punct[MIRROR_PAIRS.get(char, char)] += 1
    return letters, marks, punct


def boxes_from_spec(spec: dict) -> list[dict]:
    """Where each text box prints, as FRACTIONS of its page (origin top-left), for box_proof — mapped onto each PDF
    page's real size, so it holds whatever physical size the deck was given. One entry per textbox, slide order."""
    out = []
    for page, slide in enumerate(spec["slides"]):
        dims = slide.get("dimensions_px") or spec["slides"][0]["dimensions_px"]
        for obj in slide["objects"]:
            if obj.get("kind") != "textbox":
                continue
            x, y, w, h = obj["bbox_px"]
            text = "".join(run["text"] for run in obj.get("runs", [])) or obj.get("text", "")
            out.append({"page": page, "text": text, "fx": (x + w / 2) / dims[0], "fy": (y + h / 2) / dims[1],
                        "fw": w / dims[0], "fh": h / dims[1],
                        "rotate": float((obj.get("fx") or {}).get("rotate", 0) or 0)})
    return out


def box_proof(boxes: list[dict], pdf: Path, margin_pt: float = 6.0) -> dict:
    """Order-free proof: the letters, marks and punctuation the PDF draws inside each text box equal that box's text,
    and nothing (but whitespace) is drawn outside every box. Extraction order and word gaps play no part, so PDFium's
    line regrouping of stacked Arabic glyphs cannot break it; a missing, extra or changed word in a box still changes
    that box's multiset."""
    import math  # noqa: PLC0415

    import pypdfium2 as pdfium  # noqa: PLC0415
    import pypdfium2.raw as raw  # noqa: PLC0415
    found = [[Counter(), Counter(), Counter()] for _ in boxes]
    stray = Counter()
    document = pdfium.PdfDocument(str(pdf))
    try:
        for page_index, page in enumerate(document):
            textpage = page.get_textpage()
            width, height = page.get_size()
            mine = [i for i, b in enumerate(boxes) if b["page"] == page_index]
            placed = {i: (boxes[i]["fx"] * width, height - boxes[i]["fy"] * height, boxes[i]["fw"] * width,
                          boxes[i]["fh"] * height) for i in mine}
            for index in range(textpage.count_chars()):
                if raw.FPDFText_IsGenerated(textpage.raw, index):
                    continue
                char = chr(raw.FPDFText_GetUnicode(textpage.raw, index))
                if char.isspace():
                    continue
                left, bottom, right, top = textpage.get_charbox(index)
                cx, cy = (left + right) / 2, (bottom + top) / 2
                home = None
                for i in mine:
                    bx, by, bw, bh = placed[i]
                    a = math.radians(boxes[i]["rotate"])
                    dx, dy = cx - bx, cy - by
                    u = dx * math.cos(a) - dy * math.sin(a)  # into the box's own axes (PDF y up, rotation clockwise)
                    v = dx * math.sin(a) + dy * math.cos(a)
                    if abs(u) <= bw / 2 + margin_pt and abs(v) <= bh / 2 + margin_pt:
                        home = i
                        break
                letters, marks, punct = _classify(char)
                if home is None:
                    stray += letters + punct
                    continue
                found[home][0] += letters
                found[home][1] += marks
                found[home][2] += punct
    finally:
        document.close()
    bad = []
    for i, box in enumerate(boxes):
        want = _classify(box["text"])
        if tuple(want) != tuple(found[i]):
            bad.append({"page": box["page"] + 1, "text": box["text"][:60],
                        "missing": "".join((want[0] - found[i][0]).elements())[:40],
                        "extra": "".join((found[i][0] - want[0]).elements())[:40],
                        "marks_equal": want[1] == found[i][1], "punct_equal": want[2] == found[i][2]})
    return {"ok": not bad and not stray, "boxes": len(boxes), "mismatched_boxes": bad[:10],
            "stray_outside_boxes": "".join(stray.elements())[:60]}


def text_proof(expected_texts: list[str], pdf: Path, names: list[str] | None = None,
               boxes: list[dict] | None = None) -> dict:
    """`names`: the deck's child-name runs (each its own run), used only to undo the glued-name extraction."""
    text = extract_text(pdf)
    result = compare_texts(expected_texts, text, names, marked_text=extract_text_marked(pdf))
    result["view"] = "pdfium"
    if not result["ok"]:  # rotated text: words rebuilt from glyph geometry (same characters, other word gaps)
        geometric = compare_texts(expected_texts, text, names, marked_text=extract_text_geometric(pdf))
        if geometric["ok"]:
            geometric["view"] = "geometry"
            return geometric
    boxes_cover = bool(boxes) and Counter(b["text"] for b in boxes) == Counter(expected_texts)
    if not result["ok"] and boxes_cover and result["marks_equal"] and result["punct_equal"]:
        # PDFium regroups stacked/decorative Arabic glyphs into other "lines": prove per box, order-free
        located = box_proof(boxes, pdf)
        result["box_proof"] = located
        if located["ok"]:
            result.update(ok=True, view="boxes")
    return result


def compare_texts(expected_texts: list[str], actual_text: str, names: list[str] | None = None,
                  marked_text: str | None = None) -> dict:
    expected_text = split_at_names("".join(f"{t} " for t in expected_texts), names)
    actual_text = split_at_names(actual_text, names)
    word_text = split_at_names(marked_text if marked_text is not None else actual_text, names)
    expected_base, expected_marks, expected_punct = normalize_for_proof(expected_text)
    actual_base, actual_marks, actual_punct = normalize_for_proof(actual_text)
    expected_words = word_signatures(expected_text)
    actual_words, healed = heal_fragments(expected_words, _tokens(word_text))
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
    result["fragments_joined"] = healed
    result["method"] = "sequence" if result["base_equal"] else "word_signatures"
    result["ok"] = (result["base_equal"] or result["words_equal"]) and result["marks_equal"] and result["punct_equal"]
    return result
