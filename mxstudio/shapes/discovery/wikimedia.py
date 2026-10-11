"""Wikimedia Commons API discovery (File namespace search + ``imageinfo`` / ``extmetadata``).

Per-file fields used: ``LicenseShortName``, ``License``, ``LicenseUrl``, ``UsageTerms``,
``AttributionRequired``, ``Artist``, ``Restrictions``, ``NonFree``. A file is refused when
``NonFree`` is true or ``Restrictions`` is non-empty (trademark / personality rights), whatever
its licence says.
"""
from __future__ import annotations

from .base import Candidate, LicenceDecision, PoliteClient, clean_text, licence_gate, normalise_licence

DEFAULT_API = "https://commons.wikimedia.org/w/api.php"


def _meta(ext: dict, key: str) -> str:
    v = ext.get(key) or {}
    return str(v.get("value", "") if isinstance(v, dict) else v)


def search(client: PoliteClient, query: str, *, limit: int = 20, api_url: str = DEFAULT_API) -> list[Candidate]:
    params = {"action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
              "gsrsearch": clean_text(query, 100), "gsrlimit": max(1, min(int(limit), 50)), "prop": "imageinfo",
              "iiprop": "url|extmetadata|mime|sha1|size"}
    data = client.get_json(api_url, params)
    pages = ((data.get("query") or {}).get("pages") or {})
    items = sorted(pages.values(), key=lambda p: int(p.get("index", 0) or 0))
    out: list[Candidate] = []
    for page in items[: int(limit)]:
        infos = page.get("imageinfo") or []
        if not infos:
            continue
        info = infos[0]
        ext = info.get("extmetadata") or {}
        raw = _meta(ext, "License") or _meta(ext, "LicenseShortName")
        licence = normalise_licence(raw) if raw else "UNKNOWN"
        if licence == "UNKNOWN" and _meta(ext, "LicenseShortName"):
            licence = normalise_licence(_meta(ext, "LicenseShortName"))
        attribution_required = _meta(ext, "AttributionRequired").strip().lower() == "true"
        decision = licence_gate(licence, attribution_required=attribution_required)
        findings = []
        restrictions = clean_text(_meta(ext, "Restrictions"))
        nonfree = _meta(ext, "NonFree").strip().lower() == "true"
        if nonfree:
            findings.append("nonfree")
            decision = LicenceDecision(licence, "refused", False, "ملف غير حر (NonFree): مرفوض",
                                       "file is marked NonFree: refused")
        elif restrictions:
            findings.append(f"restrictions:{restrictions}")
            decision = LicenceDecision(licence, "refused", False, "عليه قيود (علامة تجارية/حقوق شخصية): مرفوض",
                                       f"restricted ({restrictions}): refused")
        mime = str(info.get("mime") or "")
        out.append(Candidate(
            source="wikimedia", source_id=clean_text(page.get("title"), 200), title=clean_text(page.get("title")),
            kind="importable", media="svg" if mime == "image/svg+xml" else "raster",
            asset_url=str(info.get("url") or ""), landing_url=clean_text(info.get("descriptionurl"), 400),
            licence=licence, licence_raw=clean_text(raw), licence_url=clean_text(_meta(ext, "LicenseUrl"), 300),
            author=clean_text(_meta(ext, "Artist")), author_url="", decision=decision,
            attribution=clean_text(_meta(ext, "Credit") or _meta(ext, "Artist"), 400),
            preview_url=str(info.get("url") or ""), findings=findings + [f"usage_terms:{clean_text(_meta(ext, 'UsageTerms'), 80)}"]))
    return out
