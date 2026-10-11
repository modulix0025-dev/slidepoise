"""Local asset packs (e.g. Kenney, CC0) imported from a folder or zip the operator downloaded.

Rule: the pack's own ``License.txt`` (or ``LICENSE*``) must state CC0 / public domain; otherwise
nothing in it is importable. SVG files are sanitised; provenance points at the pack file.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

from .base import Candidate, clean_text, licence_gate

_CC0 = re.compile(r"\bCC0\b|creative\s+commons\s+zero|public\s+domain\s+dedication", re.I)


def pack_licence(names_and_text: dict[str, str]) -> str:
    for name, text in names_and_text.items():
        if re.match(r"(?i)^(.*/)?licen[sc]e[^/]*\.(txt|md)$", name) and _CC0.search(text or ""):
            return "CC0-1.0"
    return "UNKNOWN"


def scan_pack(path: str | Path, *, source_url: str, author: str = "Kenney") -> list[Candidate]:
    """List SVG/PNG members of a pack with the pack-level licence decision."""
    path = Path(path)
    texts: dict[str, str] = {}
    members: list[str] = []
    if path.is_dir():
        for p in sorted(path.rglob("*")):
            if p.is_file():
                rel = p.relative_to(path).as_posix()
                members.append(rel)
                if p.suffix.lower() in (".txt", ".md") and p.stat().st_size < 200_000:
                    texts[rel] = p.read_text(encoding="utf-8", errors="replace")
    else:
        with zipfile.ZipFile(path) as z:
            for info in z.infolist():
                members.append(info.filename)
                if info.filename.lower().endswith((".txt", ".md")) and info.file_size < 200_000:
                    texts[info.filename] = z.read(info).decode("utf-8", errors="replace")
    licence = pack_licence(texts)
    decision = licence_gate(licence)
    out = []
    for m in members:
        if not m.lower().endswith((".svg", ".png")):
            continue
        out.append(Candidate(source="kenney", source_id=m, title=clean_text(Path(m).stem.replace("_", " ")),
                             kind="importable", media="svg" if m.lower().endswith(".svg") else "raster",
                             asset_url=f"pack://{path.name}/{m}", landing_url=source_url, licence=licence,
                             licence_raw="License.txt", licence_url="https://creativecommons.org/publicdomain/zero/1.0/"
                             if licence == "CC0-1.0" else "", author=author, author_url=source_url, decision=decision,
                             findings=[] if licence == "CC0-1.0" else ["pack_licence_not_cc0"]))
    return out


def read_member(path: str | Path, member: str) -> bytes:
    path = Path(path)
    if path.is_dir():
        target = (path / member).resolve()
        if path.resolve() not in target.parents:
            raise ValueError("member escapes the pack folder")
        return target.read_bytes()
    with zipfile.ZipFile(path) as z:
        return z.read(member)
