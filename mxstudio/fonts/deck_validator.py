"""Deck font validator: every typeface a deck uses must be installed AND certified on the exporting machine.

Rule: a PPTX is refused **by exact font name** when any typeface it references
for exported content is not installed on the export machine, or is installed
but not certified for print. References are collected from ``a:latin``,
``a:ea``, ``a:cs`` and ``a:sym`` in slides, layouts, masters, charts and
diagram drawings; theme placeholders ``+mj-lt/+mn-lt/+mj-ea/+mn-ea/+mj-cs/
+mn-cs`` are resolved through the theme of the part's slide master (an empty
theme ``cs``/``ea`` falls back to the theme's ``<a:font script="Arab">`` entry,
which is what PowerPoint uses for Arabic runs). Notes and handout parts are
listed separately because they are not exported.

Names are compared the way Office does — NFC, end-trimmed, case-insensitive —
and internal whitespace is significant: ``Blabeloo  MagdySoliman`` (two
spaces) is a different name from ``Blabeloo MagdySoliman``.
"""
from __future__ import annotations

import json
import posixpath
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from lxml import etree

from slidepoise.arabic.fonts import FontRegistry, normalize_family

from mxstudio.fonts.paths import OFFICE_BUILDS_JSON

NS = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main",
      "r": "http://schemas.openxmlformats.org/package/2006/relationships"}
FONT_TAGS = ("latin", "ea", "cs", "sym")
EXPORTED = re.compile(r"^ppt/(slides|slideLayouts|slideMasters|charts|diagrams)/[^/]+\.xml$")
NOT_EXPORTED = re.compile(r"^ppt/(notesSlides|notesMasters|handoutMasters)/[^/]+\.xml$")
THEME_TOKENS = {"+mj-lt": ("majorFont", "latin"), "+mn-lt": ("minorFont", "latin"),
                "+mj-ea": ("majorFont", "ea"), "+mn-ea": ("minorFont", "ea"),
                "+mj-cs": ("majorFont", "cs"), "+mn-cs": ("minorFont", "cs")}
_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"


@dataclass
class Reference:
    typeface: str
    part: str
    element: str
    via_theme: str | None = None


@dataclass
class DeckFontReport:
    ok: bool
    typefaces: list[dict]
    refusals: list[dict]
    not_exported: list[dict] = field(default_factory=list)
    unresolved_theme_tokens: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"ok": self.ok, "typefaces": self.typefaces, "refusals": self.refusals,
                "not_exported": self.not_exported, "unresolved_theme_tokens": self.unresolved_theme_tokens}


def _rels(archive: zipfile.ZipFile, part: str) -> dict[str, str]:
    """Relationship type suffix → absolute target part for `part`."""
    folder, name = posixpath.split(part)
    rels_name = posixpath.join(folder, "_rels", name + ".rels")
    if rels_name not in archive.namelist():
        return {}
    root = etree.fromstring(archive.read(rels_name))
    out = {}
    for rel in root.findall("r:Relationship", NS):
        if rel.get("TargetMode") == "External":
            continue
        kind = rel.get("Type", "").replace(_REL_TYPE, "")
        out.setdefault(kind, posixpath.normpath(posixpath.join(folder, rel.get("Target", ""))))
    return out


def _theme_fonts(archive: zipfile.ZipFile, theme_part: str) -> dict[str, dict[str, str]]:
    root = etree.fromstring(archive.read(theme_part))
    fonts: dict[str, dict[str, str]] = {}
    for group in ("majorFont", "minorFont"):
        node = root.find(f".//a:fontScheme/a:{group}", NS)
        entry: dict[str, str] = {}
        if node is not None:
            for tag in ("latin", "ea", "cs"):
                child = node.find(f"a:{tag}", NS)
                entry[tag] = child.get("typeface", "") if child is not None else ""
            for script_font in node.findall("a:font", NS):
                entry[f"script:{script_font.get('script')}"] = script_font.get("typeface", "")
        fonts[group] = entry
    return fonts


def _master_of(archive: zipfile.ZipFile, part: str) -> str | None:
    seen = set()
    while part and part not in seen:
        seen.add(part)
        if "/slideMasters/" in part:
            return part
        rels = _rels(archive, part)
        part = rels.get("slideMaster") or rels.get("slideLayout") or ""
    return None


def _theme_for(archive: zipfile.ZipFile, part: str) -> str | None:
    if "/charts/" in part or "/diagrams/" in part:
        # charts/diagrams inherit the presentation's first master theme
        masters = sorted(n for n in archive.namelist() if re.match(r"^ppt/slideMasters/[^/]+\.xml$", n))
        part = masters[0] if masters else ""
    master = _master_of(archive, part) if part else None
    return _rels(archive, master).get("theme") if master else None


def _clean(typeface: str) -> str:
    return typeface[1:] if typeface.startswith("@") else typeface  # vertical-text alias


def referenced_typefaces(pptx: Path) -> tuple[list[Reference], list[Reference], list[dict]]:
    """(exported references, not-exported references, unresolved theme tokens)."""
    exported: list[Reference] = []
    hidden: list[Reference] = []
    unresolved: list[dict] = []
    with zipfile.ZipFile(pptx) as archive:
        theme_cache: dict[str, dict] = {}
        for part in sorted(archive.namelist()):
            is_exported = bool(EXPORTED.match(part))
            if not is_exported and not NOT_EXPORTED.match(part):
                continue
            root = etree.fromstring(archive.read(part))
            theme_part = None
            for tag in FONT_TAGS:
                for node in root.iter(f"{{{NS['a']}}}{tag}"):
                    typeface = node.get("typeface")
                    if typeface is None or typeface == "":
                        continue
                    via = None
                    if typeface in THEME_TOKENS:
                        theme_part = theme_part or _theme_for(archive, part)
                        if not theme_part:
                            unresolved.append({"part": part, "token": typeface, "reason": "no theme"})
                            continue
                        theme = theme_cache.setdefault(theme_part, _theme_fonts(archive, theme_part))
                        group, slot = THEME_TOKENS[typeface]
                        resolved = theme.get(group, {}).get(slot, "")
                        if not resolved and slot == "cs":
                            resolved = theme.get(group, {}).get("script:Arab", "")
                        if not resolved:
                            unresolved.append({"part": part, "token": typeface, "reason": "empty in theme"})
                            continue
                        via, typeface = typeface, resolved
                    ref = Reference(typeface=_clean(typeface), part=part, element=f"a:{tag}", via_theme=via)
                    (exported if is_exported else hidden).append(ref)
    return exported, hidden, unresolved


def _summarise(refs: Iterable[Reference]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for ref in refs:
        item = out.setdefault(normalize_family(ref.typeface), {"name": ref.typeface, "parts": set(),
                                                               "elements": set(), "via_theme": set()})
        item["parts"].add(ref.part)
        item["elements"].add(ref.element)
        if ref.via_theme:
            item["via_theme"].add(ref.via_theme)
    return out


def certified_install_names(builds_path: Path = OFFICE_BUILDS_JSON, extra: Iterable[str] = ()) -> set[str]:
    """Every family name an installed certified font reports (ID1 and ID16), plus operator-certified extras."""
    data = json.loads(Path(builds_path).read_text(encoding="utf-8"))
    names: set[str] = set(extra)
    for plan in data["families"]:
        if plan.get("qa_status") != "certified_print":
            continue
        if plan.get("install_family"):
            names.add(plan["install_family"])
        for item in plan.get("files", []):
            names.update(n for n in (item.get("family"), item.get("typographic_family")) if n)
    return names


def _installed_check(installed) -> Callable[[str], bool]:
    if isinstance(installed, FontRegistry):
        return installed.has
    if callable(installed):
        return installed
    pool = {normalize_family(n) for n in installed}
    return lambda name: normalize_family(name) in pool


def validate_deck(pptx: Path, *, installed, certified: Iterable[str]) -> DeckFontReport:
    """Refuse by name every exported typeface that is not installed, or installed but not certified."""
    is_installed = _installed_check(installed)
    certified_pool = {normalize_family(n) for n in certified}
    exported, hidden, unresolved = referenced_typefaces(Path(pptx))
    typefaces, refusals = [], []
    for key, item in sorted(_summarise(exported).items()):
        name = item["name"]
        present = is_installed(name)
        ok_cert = key in certified_pool
        typefaces.append({"name": name, "installed": present, "certified": ok_cert,
                          "parts": sorted(item["parts"]), "elements": sorted(item["elements"]),
                          "via_theme": sorted(item["via_theme"])})
        if not present:
            refusals.append({"finding": "deck_font_not_installed", "typeface": name,
                             "ar": f"الخط «{name}» مش متثبّت على جهاز التصدير — الديك اترفض.",
                             "en": f"typeface «{name}» is not installed on the export machine — deck refused"})
        elif not ok_cert:
            refusals.append({"finding": "deck_font_not_certified", "typeface": name,
                             "ar": f"الخط «{name}» متثبّت بس مش معتمد للطباعة — الديك اترفض.",
                             "en": f"typeface «{name}» is installed but not certified for print — deck refused"})
    not_exported = [{"name": item["name"], "parts": sorted(item["parts"])}
                    for _k, item in sorted(_summarise(hidden).items())]
    return DeckFontReport(ok=not refusals, typefaces=typefaces, refusals=refusals, not_exported=not_exported,
                          unresolved_theme_tokens=unresolved)
