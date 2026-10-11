"""Iconify API discovery (``/search`` + ``/{prefix}/{name}.svg``).

Licence is per icon *set*: ``collections[prefix].license.spdx`` from the same response (verified
field, see docs/mag/phase-0/evidence/licence_verification_2026-10-11.md). Brand sets and refused
sets are excluded; Remix Icon is accepted only up to version 4.8.0 (Apache-2.0).
"""
from __future__ import annotations

from .base import REFUSED, Candidate, LicenceDecision, PoliteClient, clean_text, licence_gate, normalise_licence, sources

DEFAULT_BASE = "https://api.iconify.design"


def _version_tuple(v: str) -> tuple[int, ...]:
    out = []
    for part in str(v).split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out)


def search(client: PoliteClient, query: str, *, limit: int = 32, base_url: str = DEFAULT_BASE) -> list[Candidate]:
    q = clean_text(query, 100)
    data = client.get_json(f"{base_url}/search", {"query": q, "limit": max(32, min(int(limit), 999))})
    cfg = sources()
    excluded = cfg.get("iconify_excluded_prefixes", {})
    caps = cfg.get("iconify_version_caps", {})
    collections = data.get("collections") or {}
    out: list[Candidate] = []
    for full in data.get("icons", [])[: int(limit)]:
        full = str(full)
        if ":" not in full:
            continue
        prefix, name = full.split(":", 1)
        info = collections.get(prefix) or {}
        lic = info.get("license") or {}
        raw = str(lic.get("spdx") or lic.get("title") or "")
        licence = normalise_licence(raw)
        findings = []
        decision = licence_gate(licence)
        if prefix in excluded:
            findings.append(f"excluded_set:{prefix}")
            decision = LicenceDecision(licence, REFUSED, False, "مجموعة مستبعدة: " + clean_text(excluded[prefix]),
                                      "excluded set: " + clean_text(excluded[prefix]))
        cap = caps.get(prefix)
        if cap is not None:
            version = str(info.get("version") or "")
            if not version or _version_tuple(version) > _version_tuple(cap):
                findings.append(f"version_above_cap:{prefix}@{version or '?'}>{cap}")
                decision = LicenceDecision(licence, REFUSED, False, f"إصدار أعلى من {cap}: مرفوض",
                                          f"set version {version or 'unknown'} is above the {cap} cap: refused")
        author = info.get("author") or {}
        out.append(Candidate(
            source="iconify", source_id=full, title=clean_text(name.replace("-", " ")), kind="importable", media="svg",
            asset_url=f"{base_url}/{prefix}/{name}.svg", landing_url=f"https://icon-sets.iconify.design/{prefix}/{name}/",
            licence=licence, licence_raw=clean_text(raw), licence_url=clean_text(lic.get("url") or "", 300),
            author=clean_text(author.get("name") or ""), author_url=clean_text(author.get("url") or "", 300),
            decision=decision, attribution=clean_text(f"{info.get('name', prefix)} by {author.get('name', '?')}"),
            tags=[clean_text(t, 40) for t in (info.get("tags") or [])][:8], preview_url=f"{base_url}/{prefix}/{name}.svg",
            findings=findings))
    return out
