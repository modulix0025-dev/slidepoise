"""Read font names out of a PDF (raw bytes + FlateDecode streams), stdlib only.

Used by export proofs to compare the deck's typefaces with what the engine embedded; a deck
typeface missing from the PDF is reported as a substitution (fact, not a verdict).
"""
from __future__ import annotations

import re
import zlib

_STREAM = re.compile(rb"stream\r?\n")
_BASEFONT = re.compile(rb"/BaseFont\s*/([^\s/<>\[\]()]+)")


def _chunks(data: bytes, limit: int = 4000):
    yield data
    for n, m in enumerate(_STREAM.finditer(data)):
        if n >= limit:
            break
        end = data.find(b"endstream", m.end())
        if end < 0:
            continue
        try:
            yield zlib.decompress(data[m.end():end])
        except Exception:  # noqa: BLE001
            continue


def _unescape(name: bytes) -> str:
    raw = re.sub(rb"#([0-9A-Fa-f]{2})", lambda m: bytes([int(m.group(1), 16)]), name)
    text = raw.decode("utf-8", "replace")
    return text.split("+", 1)[1] if re.match(r"^[A-Z]{6}\+", text) else text


def pdf_font_names(data: bytes) -> list[str]:
    names = set()
    for chunk in _chunks(data or b""):
        for m in _BASEFONT.finditer(chunk):
            names.add(_unescape(m.group(1)))
    return sorted(names)


def norm_font(name: str) -> str:
    """Compare key: case/space/hyphen-insensitive, style suffix dropped (PDF names drop spaces)."""
    key = re.sub(r"[\s\-_,]", "", name).lower()
    return re.sub(r"(regular|bold|italic|boldItalic|mt|ps)+$", "", key, flags=re.IGNORECASE)
