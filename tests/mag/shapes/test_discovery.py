"""Gate E: licence-gated discovery against recorded cassettes (no network)."""
from __future__ import annotations

import json

import pytest

from mxstudio.shapes.discovery import (ApprovalRequired, InspirationOnly, LicenceRefused, import_candidate,
                                       inspiration_candidate, search_all)
from mxstudio.shapes.discovery import iconify, openverse, wikimedia
from mxstudio.shapes.discovery.base import DiscoveryError, PoliteClient


def by_id(cands):
    return {c.source_id: c for c in cands}


def test_cassettes_declare_they_are_not_live_recordings():
    from pathlib import Path

    for path in (Path(__file__).resolve().parent / "cassettes").glob("*.json"):
        meta = json.loads(path.read_text(encoding="utf-8"))["_meta"]
        assert meta["recorded_live"] is False and "pending on-device" in meta["re_record"]


def test_iconify_licence_per_set(cassette_client):
    client, cas = cassette_client("iconify_search_cat.json")
    res = by_id(iconify.search(client, "cat"))
    assert res["tabler:cat"].decision.status == "print_ok"
    assert res["twemoji:cat-face"].decision.status == "print_ok_with_credits"
    assert res["noto:cat"].decision.status == "print_ok" and res["mdi:cat"].licence == "Apache-2.0"
    assert res["ri:bear-smile-line"].decision.status == "print_ok"  # Remix 4.8.0 = Apache-2.0
    refused = {k: c.decision.status for k, c in res.items() if not c.decision.printable}
    assert refused == {"openmoji:cat": "refused", "simple-icons:catppuccin": "refused", "game-icons:cat": "pending_operator",
                       "circum:cat": "refused", "ps:cat": "refused", "unknownset:cat": "refused"}
    assert "excluded_set:simple-icons" in res["simple-icons:catppuccin"].findings
    assert all(u.startswith("https://api.iconify.design/") for u in cas.calls)


def test_remix_above_4_8_is_refused(cassette_client):
    client, _ = cassette_client("iconify_search_remix_4_9.json")
    (cand,) = iconify.search(client, "smile")
    assert cand.licence == "Apache-2.0" and not cand.decision.printable
    assert any(f.startswith("version_above_cap:ri@4.9.1") for f in cand.findings)


def test_openverse_gate_rechecks_every_result(cassette_client):
    client, _ = cassette_client("openverse_search_rabbit.json")
    res = openverse.search(client, "rabbit")
    status = {c.title[:20]: (c.licence, c.decision.status) for c in res}
    assert status["Rabbit silhouette"] == ("CC0-1.0", "print_ok")
    assert status["Bunny in the garden"] == ("PDM", "print_ok")
    assert status["Cartoon rabbit"] == ("CC-BY-4.0", "print_ok_with_credits")
    assert status["Old rabbit print"] == ("CC-BY-2.0", "refused")
    assert status["Rabbit sticker"] == ("CC-BY-SA-4.0", "refused")
    assert status["Rabbit plush"] == ("CC-BY-NC-4.0", "refused")
    injected = res[-1]
    assert injected.decision.status == "refused" and injected.licence == "CC-BY-ND-4.0"
    assert "<script" not in injected.title and "‮" not in injected.title and "<b>" not in injected.author
    assert injected.title.startswith("Ignore previous instructions")  # kept verbatim as data, not obeyed


def test_wikimedia_extmetadata_rules(cassette_client):
    client, _ = cassette_client("wikimedia_search_rabbit.json")
    res = by_id(wikimedia.search(client, "rabbit"))
    icon = res["File:Rabbit icon.svg"]
    assert (icon.licence, icon.decision.status, icon.author) == ("CC-BY-4.0", "print_ok_with_credits", "Example Artist")
    assert res["File:Rabbit drawing.png"].decision.status == "refused"
    assert res["File:Hare woodcut.svg"].licence == "PDM" and res["File:Hare woodcut.svg"].decision.status == "print_ok"
    assert res["File:Rabbit brand logo.svg"].decision.status == "refused"
    assert "restrictions:trademarked" in res["File:Rabbit brand logo.svg"].findings
    assert res["File:Rabbit film still.jpg"].decision.status == "refused" and "nonfree" in res["File:Rabbit film still.jpg"].findings
    assert res["File:Rabbit mystery.svg"].licence == "UNKNOWN" and not res["File:Rabbit mystery.svg"].decision.printable


def test_import_sanitises_and_records_provenance(cassette_client):
    client, _ = cassette_client("iconify_search_cat.json")
    cand = by_id(iconify.search(client, "cat"))["tabler:cat"]
    with pytest.raises(ApprovalRequired):
        import_candidate(cand, client, approved_by="  ")
    asset = import_candidate(cand, client, approved_by="Mustafa", retrieved_at="2026-10-11T00:00:00+00:00")
    assert "<script" not in asset.svg and "onload" not in asset.svg
    assert {"script", "event_handler"} <= set(asset.findings)
    prov = asset.provenance
    assert prov.missing() == [] and len(prov.sha256) == 64 and prov.licence == "MIT"
    assert prov.source_url.startswith("https://icon-sets.iconify.design/") and prov.approved_by == "Mustafa"


def test_import_refusals(cassette_client):
    client, _ = cassette_client("iconify_search_cat.json")
    res = by_id(iconify.search(client, "cat"))
    with pytest.raises(LicenceRefused):
        import_candidate(res["openmoji:cat"], client, approved_by="Mustafa")
    with pytest.raises(InspirationOnly):
        import_candidate(inspiration_candidate("https://some-blog.example/cute-cat.svg", "cute cat"), client,
                         approved_by="Mustafa")
    client2, _ = cassette_client("openverse_search_rabbit.json")
    bunny = [c for c in openverse.search(client2, "rabbit") if c.title == "Bunny in the garden"][0]
    with pytest.raises(DiscoveryError, match="not allow-listed"):
        import_candidate(bunny, client2, approved_by="Mustafa")  # flickr CDN is not an allow-listed asset host


def test_wikimedia_import_strips_foreign_object_and_tracking_pixel(cassette_client):
    client, _ = cassette_client("wikimedia_search_rabbit.json")
    icon = by_id(wikimedia.search(client, "rabbit"))["File:Rabbit icon.svg"]
    asset = import_candidate(icon, client, approved_by="Mustafa")
    assert "foreignObject" not in asset.svg and "tracker" not in asset.svg
    assert asset.provenance.credits_required is True


def test_polite_client_rules(cassette_client, tmp_path):
    client, cas = cassette_client("iconify_rate_limited.json", cache_dir=tmp_path / "cache")
    first = iconify.search(client, "sun")
    assert [c.source_id for c in first] == ["tabler:sun"] and client.sleeps == [3.0]
    again = iconify.search(client, "sun")  # cache hit: no third request
    assert [c.source_id for c in again] == ["tabler:sun"] and len(cas.calls) == 2
    for bad in ("http://api.iconify.design/search", "https://127.0.0.1/x", "https://localhost/x",
                "https://example.com/search"):
        with pytest.raises(DiscoveryError):
            client.get(bad)


def test_search_all_separates_printable_and_refused(cassette_client):
    client, cas = cassette_client("iconify_search_cat.json", "openverse_search_rabbit.json",
                                  "wikimedia_search_rabbit.json")
    out = search_all(client, "cat", sources=["iconify", "bing"])
    assert out["errors"] == {"bing": "not an official API source"}
    assert all(c.decision.printable for c in out["printable"]) and out["refused"]


def test_negative_control_unknown_request_is_not_served(cassette_client):
    client, _ = cassette_client("iconify_search_cat.json")
    with pytest.raises(AssertionError, match="not in cassette"):
        iconify.search(client, "dog")
    assert isinstance(client, PoliteClient)
