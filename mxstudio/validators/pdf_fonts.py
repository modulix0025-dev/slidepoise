"""Which fonts really ended up in an exported PDF — and whether any deck typeface was SUBSTITUTED.

Operator report: fonts copied but not registered made PowerPoint draw Microsoft JhengHei for Tajawal and Calibri
for Nunito; the PDF still carried text, so every text check passed. This module reads the PDF's font dictionaries
(BaseFont, subset prefix removed) and compares them with the deck's typefaces:

* ``missing``: a deck typeface that appears under no PDF font name (it was replaced);
* ``unexpected``: a PDF font that belongs to no deck typeface (the replacement: JhengHei, Calibri, DejaVu…).
Names are compared without spaces, hyphens and case; Office builds renamed for a Reserved Font Name are matched
through their installed family name (mxstudio.fonts.office_build.install_name_map).
"""
from __future__ import annotations

import re
from pathlib import Path

SUBSET = re.compile(r"^[A-Z]{6}\+")


def _norm(name: str) -> str:
    return re.sub(r"[\s\-_,]+", "", str(name)).casefold()


def pdf_font_names(pdf: Path) -> set[str]:
    import pikepdf  # noqa: PLC0415

    names: set[str] = set()
    with pikepdf.open(str(pdf)) as document:
        for obj in document.objects:
            try:
                if isinstance(obj, pikepdf.Dictionary) and obj.get("/Type") == "/Font" and "/BaseFont" in obj:
                    if obj.get("/Subtype") == "/Type0":
                        continue  # its descendant CIDFont carries the same BaseFont
                    names.add(SUBSET.sub("", str(obj["/BaseFont"]).lstrip("/")))
            except Exception:  # noqa: BLE001 - a malformed dictionary is skipped, never fatal
                continue
    return names


def substitutions(typefaces: set[str], pdf_fonts: set[str], install_names: dict[str, str] | None = None) -> dict:
    install_names = install_names or {}
    wanted = {face: {_norm(face), _norm(install_names.get(face, face))} for face in typefaces}
    fonts = {font: _norm(font) for font in pdf_fonts}
    used: set[str] = set()
    missing = []
    for face, keys in sorted(wanted.items()):
        hits = [font for font, key in fonts.items() if any(key.startswith(k) for k in keys)]
        if hits:
            used.update(hits)
        else:
            missing.append(face)
    unexpected = sorted(font for font in fonts if font not in used)
    return {"ok": not missing and not unexpected, "missing": missing, "unexpected": unexpected,
            "pdf_fonts": sorted(pdf_fonts)}


def check_pdf(pdf: Path, typefaces: set[str]) -> dict:
    try:
        from mxstudio.fonts.office_build import install_name_map  # noqa: PLC0415
        names = install_name_map()
    except Exception:  # noqa: BLE001 - without the map, plain names are compared
        names = {}
    return substitutions(set(typefaces), pdf_font_names(pdf), names)
