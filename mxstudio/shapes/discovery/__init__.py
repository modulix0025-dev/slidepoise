"""Licence-gated discovery over official APIs (Iconify, Openverse, Wikimedia Commons) and
local CC0 packs. Used only when the library has nothing that fits (see ``service.discover``)."""
from __future__ import annotations

from . import iconify, openverse, packs, wikimedia
from .base import (ApprovalRequired, Candidate, DiscoveryError, ImportedAsset, InspirationOnly, LicenceDecision,
                   LicenceRefused, PoliteClient, Provenance, clean_text, import_candidate, inspiration_candidate,
                   licence_gate, normalise_licence)

SEARCHERS = {"iconify": iconify.search, "openverse": openverse.search, "wikimedia": wikimedia.search}


def search_all(client: PoliteClient, query: str, *, sources: list[str] | None = None, limit: int = 20) -> dict:
    """Run the enabled searchers; one failing source never hides the others' results."""
    results: list[Candidate] = []
    errors: dict[str, str] = {}
    for name in sources or list(SEARCHERS):
        if name not in SEARCHERS:
            errors[name] = "not an official API source"
            continue
        try:
            results.extend(SEARCHERS[name](client, query, limit=limit))
        except DiscoveryError as exc:
            errors[name] = str(exc)
    printable = [c for c in results if c.decision.printable]
    refused = [c for c in results if not c.decision.printable]
    return {"query": clean_text(query, 100), "printable": printable, "refused": refused, "errors": errors}


__all__ = ["iconify", "openverse", "packs", "wikimedia", "ApprovalRequired", "Candidate", "DiscoveryError", "ImportedAsset", "InspirationOnly", "LicenceDecision",
           "LicenceRefused", "PoliteClient", "Provenance", "SEARCHERS", "clean_text", "import_candidate",
           "inspiration_candidate", "licence_gate", "normalise_licence", "search_all"]
