"""Openverse API discovery (``/v1/images/``).

Per-image licence fields: ``license``, ``license_version``, ``license_url``, ``creator``,
``attribution``, ``source``, ``provider``. The request already filters to ``cc0,pdm,by``; the
gate re-checks every result anyway (the response, not the request, is the evidence).
"""
from __future__ import annotations

from .base import Candidate, PoliteClient, clean_text, licence_gate, normalise_licence, sources

DEFAULT_BASE = "https://api.openverse.org/v1"


def search(client: PoliteClient, query: str, *, limit: int = 20, base_url: str = DEFAULT_BASE) -> list[Candidate]:
    filt = next((s.get("request_license_filter") for s in sources()["sources"] if s["id"] == "openverse"), "cc0,pdm,by")
    data = client.get_json(f"{base_url}/images/", {"q": clean_text(query, 100), "license": filt,
                                                   "page_size": max(1, min(int(limit), 50))})
    out: list[Candidate] = []
    for item in data.get("results", [])[: int(limit)]:
        raw = str(item.get("license") or "")
        ver = str(item.get("license_version") or "")
        licence = normalise_licence(raw, ver)
        decision = licence_gate(licence)
        ftype = str(item.get("filetype") or "").lower()
        url = str(item.get("url") or "")
        media = "svg" if ftype == "svg" or url.lower().endswith(".svg") else "raster"
        out.append(Candidate(
            source="openverse", source_id=clean_text(item.get("id"), 80), title=clean_text(item.get("title")),
            kind="importable", media=media, asset_url=url, landing_url=clean_text(item.get("foreign_landing_url"), 400),
            licence=licence, licence_raw=clean_text(f"{raw} {ver}".strip()),
            licence_url=clean_text(item.get("license_url"), 300), author=clean_text(item.get("creator")),
            author_url=clean_text(item.get("creator_url"), 300), decision=decision,
            attribution=clean_text(item.get("attribution"), 400),
            tags=[clean_text(t.get("name") if isinstance(t, dict) else t, 40) for t in (item.get("tags") or [])][:8],
            preview_url=clean_text(item.get("thumbnail"), 400),
            findings=[f"provider:{clean_text(item.get('provider'), 40)}", f"source:{clean_text(item.get('source'), 40)}"]))
    return out
