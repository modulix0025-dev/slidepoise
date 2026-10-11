"""OFL Reserved Font Names (RFN): parse them, and refuse a modified font that still uses one.

OFL-1.1 condition 3: "No Modified Version of the Font Software may use the
Reserved Font Name(s) unless explicit written permission is granted". Instancing
a variable font, renaming, merging or subsetting *for redistribution* makes a
Modified Version, so an Office-safe build of a family that declares any RFN is
renamed to ``MX Kids <id> …`` and keeps the licence. Subsets embedded inside a
PDF/PPTX are ordinary document use and need no rename.

The RFN is read only from the licence header (the part before "This Font
Software is licensed"), because the licence body itself defines the term
"Reserved Font Name" and would otherwise be mistaken for a declaration.
"""
from __future__ import annotations

import re
import unicodedata

_HEADER_END = re.compile(r"This Font Software is licensed", re.IGNORECASE)
_DECL = re.compile(r"Reserved\s+Font\s+Names?\s*:?\s*(?P<rest>.+?)(?:\.\s|\.$|\n\s*\n|$)", re.IGNORECASE | re.DOTALL)
_QUOTED = re.compile(r"[\"“”'‘’]([^\"“”'‘’]+)[\"“”'‘’]")
RENAME_PREFIX = "MX Kids"


def licence_header(text: str) -> str:
    match = _HEADER_END.search(text or "")
    return (text or "")[: match.start()] if match else (text or "")[:2000]


def parse_reserved_font_names(licence_text: str) -> list[str]:
    """Every RFN declared in an OFL header, in order, duplicates kept (they are facts of the file)."""
    names: list[str] = []
    for decl in _DECL.finditer(licence_header(licence_text)):
        rest = " ".join(decl.group("rest").split())
        quoted = _QUOTED.findall(rest)
        if quoted:
            names.extend(" ".join(q.split()) for q in quoted)
        else:  # e.g. `with Reserved Font Name EURM10.`
            token = re.match(r"[A-Za-z0-9][\w\- ]*?(?=[,.;]|$| and )", rest)
            if token:
                names.append(token.group(0).strip())
    return names


def _fold(value: str) -> str:
    return unicodedata.normalize("NFC", value or "").casefold()


def _squash(value: str) -> str:
    return re.sub(r"[\s\-_]+", "", _fold(value))


def rfn_conflicts(name: str, rfns: list[str]) -> list[str]:
    """RFNs that `name` still uses (case-insensitive; also matched with spaces removed, for PostScript names)."""
    hits = []
    for rfn in dict.fromkeys(rfns):
        if not rfn.strip():
            continue
        if _fold(" ".join(rfn.split())) in _fold(" ".join(name.split())) or _squash(rfn) in _squash(name):
            hits.append(rfn)
    return hits


def renamed_family(font_id: str, family: str, rfns: list[str]) -> str:
    """``MX Kids <id> <family words that are not part of any RFN>`` — never contains an RFN."""
    reserved_words = {_fold(word) for rfn in rfns for word in rfn.split()}
    kept = [word for word in family.split() if _fold(word) not in reserved_words]
    candidate = " ".join([RENAME_PREFIX, font_id, *kept])
    while kept and rfn_conflicts(candidate, rfns):
        kept.pop()
        candidate = " ".join([RENAME_PREFIX, font_id, *kept])
    return candidate
