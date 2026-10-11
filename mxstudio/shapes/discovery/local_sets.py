"""Offline Iconify search over the installed shape packs (``<dir>/iconify/<prefix>/icons.json``).

The packs are the official ``@iconify-json`` sets pinned in ``catalog/shapes/packs.json`` and
shipped by the Full installer (or built by the Doctor). Search and import follow the same rules
as the online Iconify API: licence per set from the set's own ``info.json``, excluded prefixes
and version caps from ``catalog/shapes/sources.json``, and nothing enters the library without
the operator's approval (``import_candidate``). Search works with no network at all.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .base import REFUSED, Candidate, LicenceDecision, clean_text, licence_gate, normalise_licence, sources

SCHEME = "iconify-local://"
_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int("".join(ch for ch in part if ch.isdigit()) or 0) for part in str(v).split("."))


class LocalSets:
    """Lazily loads each set once; search ranks by whole-word, then prefix, then substring match."""

    def __init__(self, folders: list[Path]):
        self.folders = [Path(f) for f in folders]
        self._sets: dict[str, dict] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        for folder in self.folders:
            for icons_path in sorted(folder.glob("iconify/*/icons.json")):
                prefix = icons_path.parent.name
                if prefix in self._sets:
                    continue  # the Full installer's copy (first folder) wins
                try:
                    info = json.loads((icons_path.parent / "info.json").read_text(encoding="utf-8"))
                    self._sets[prefix] = {"path": icons_path, "info": info, "data": None}
                except (OSError, ValueError):
                    continue

    def prefixes(self) -> list[str]:
        self._load()
        return sorted(self._sets)

    def _data(self, prefix: str) -> dict:
        entry = self._sets[prefix]
        if entry["data"] is None:
            entry["data"] = json.loads(entry["path"].read_text(encoding="utf-8"))
        return entry["data"]

    def _decision(self, prefix: str) -> tuple[str, str, LicenceDecision, list[str]]:
        cfg = sources()
        info = self._sets[prefix]["info"]
        lic = info.get("license") or {}
        raw = str(lic.get("spdx") or lic.get("title") or "")
        licence = normalise_licence(raw)
        decision, findings = licence_gate(licence), []
        excluded = cfg.get("iconify_excluded_prefixes", {})
        if prefix in excluded:
            findings.append(f"excluded_set:{prefix}")
            decision = LicenceDecision(licence, REFUSED, False, "مجموعة مستبعدة: " + clean_text(excluded[prefix]),
                                       "excluded set: " + clean_text(excluded[prefix]))
        cap = cfg.get("iconify_version_caps", {}).get(prefix)
        if cap is not None:
            version = str(info.get("version") or "")
            if not version or _version_tuple(version) > _version_tuple(cap):
                findings.append(f"version_above_cap:{prefix}@{version or '?'}>{cap}")
                decision = LicenceDecision(licence, REFUSED, False, f"إصدار أعلى من {cap}: مرفوض",
                                           f"set version {version or 'unknown'} is above the {cap} cap")
        return licence, raw, decision, findings

    def search(self, query: str, *, limit: int = 20) -> list[Candidate]:
        self._load()
        words = [w for w in re.split(r"[^a-z0-9]+", clean_text(query, 100).lower()) if w]
        if not words:
            return []
        scored: list[tuple[int, str, str]] = []
        for prefix in self._sets:
            data = self._data(prefix)
            names = list(data.get("icons", {})) + [a for a, v in (data.get("aliases") or {}).items()
                                                   if set(v) <= {"parent"}]
            for name in names:
                parts = name.split("-")
                score = 0
                for w in words:
                    if w in parts:
                        score += 3
                    elif any(p.startswith(w) for p in parts):
                        score += 2
                    elif w in name:
                        score += 1
                    else:
                        score = 0
                        break
                if score:
                    scored.append((-score + len(parts) * 0.01, prefix, name))  # fewer extra words rank higher
        scored.sort()
        return [self._candidate(prefix, name) for _, prefix, name in scored[: max(1, int(limit))]]

    def _candidate(self, prefix: str, name: str) -> Candidate:
        info = self._sets[prefix]["info"]
        licence, raw, decision, findings = self._decision(prefix)
        lic = info.get("license") or {}
        author = info.get("author") or {}
        return Candidate(
            source="iconify", source_id=f"{prefix}:{name}", title=clean_text(name.replace("-", " ")),
            kind="importable", media="svg", asset_url=f"{SCHEME}{prefix}/{name}",
            landing_url=f"https://icon-sets.iconify.design/{prefix}/{name}/", licence=licence,
            licence_raw=clean_text(raw), licence_url=clean_text(lic.get("url") or "", 300),
            author=clean_text(author.get("name") or ""), author_url=clean_text(author.get("url") or "", 300),
            decision=decision, attribution=clean_text(f"{info.get('name', prefix)} by {author.get('name', '?')}"),
            tags=["offline-pack", *[clean_text(t, 40) for t in (info.get("tags") or [])][:7]], preview_url="",
            findings=findings)

    def svg(self, asset_url: str) -> bytes:
        """The icon as a standalone SVG, built from the set exactly as the Iconify API would serve it."""
        if not asset_url.startswith(SCHEME):
            raise KeyError(asset_url)
        prefix, _, name = asset_url[len(SCHEME):].partition("/")
        self._load()
        if prefix not in self._sets or not _NAME.match(name):
            raise KeyError(asset_url)
        data = self._data(prefix)
        icons, aliases = data.get("icons", {}), data.get("aliases") or {}
        if name not in icons and name in aliases and set(aliases[name]) <= {"parent"}:
            name = aliases[name]["parent"]
        icon = icons[name]
        left, top = icon.get("left", data.get("left", 0)), icon.get("top", data.get("top", 0))
        width, height = icon.get("width", data.get("width", 16)), icon.get("height", data.get("height", 16))
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
               f'viewBox="{left} {top} {width} {height}">{icon["body"]}</svg>')
        return svg.encode("utf-8")


class LocalClient:
    """The ``client.get`` that ``import_candidate`` expects, served from the local packs."""

    def __init__(self, sets: LocalSets):
        self.sets = sets

    def get(self, url: str, asset: bool = False, **_):
        return self.sets.svg(url), "image/svg+xml"
