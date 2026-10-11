"""References remain portable, traceable and separate from private libraries.

ModuleX fork: the upstream `pwc-public` profile (third-party PwC / Strategy&
documents with no open-content licence) is removed from this fork — brief §5 and
plan decision D1. The same retrieval guarantees are now exercised on a small
generated catalog whose images are created by the test itself.
"""
import hashlib
import json
from pathlib import Path

from PIL import Image

from slidepoise.reference_retrieval import retrieve

ROOT = Path(__file__).resolve().parents[1]


def _catalog(tmp_path: Path) -> Path:
    library = tmp_path / "profile" / "libraries" / "visual_references"
    library.mkdir(parents=True)
    items = {}
    pages = [
        (1, "cover", "photographic cover", False),
        (2, "roadmap", "staged roadmap with sequence of stages", True),
        (3, "comparison", "two column comparison", True),
        (4, "roadmap", "three stage sequence timeline roadmap", True),
    ]
    for number, role, layout, eligible in pages:
        name = f"generated-page-{number:02d}.png"
        Image.new("RGB", (160, 90), (number * 40, 120, 200)).save(library / name)
        items[f"gen{number}"] = {
            "id": f"gen{number}", "name": f"Generated {layout}", "description": layout, "roles": [role],
            "layout": layout, "path": name, "tags": [role], "retrieval_eligible": eligible,
            "provenance": {"source_type": "generated_fixture", "generated_reference": True, "license": "CC0-1.0"},
            "source_page": number, "source_filename": "generated-fixture", "visibility": "public_reference",
            "image_sha256": hashlib.sha256((library / name).read_bytes()).hexdigest(),
        }
    catalog = library / "catalog.json"
    catalog.write_text(json.dumps({"schema_version": "1.0.0", "selection_owner": "host_agent", "items": items}))
    return catalog


def test_third_party_reference_profile_is_not_shipped():
    assert not (ROOT / "profiles" / "pwc-public").exists()
    for path in (ROOT / "profiles").rglob("*.pdf"):
        raise AssertionError(f"unexpected document shipped in profiles: {path}")


def test_references_are_portable_and_verified(tmp_path):
    catalog = _catalog(tmp_path)
    for entry in json.loads(catalog.read_text())["items"].values():
        image = (catalog.parent / entry["path"]).resolve()
        assert image.is_relative_to(catalog.parent.resolve())
        assert hashlib.sha256(image.read_bytes()).hexdigest() == entry["image_sha256"]
    metadata = catalog.read_text()
    assert "/Users/" not in metadata
    assert "user_private_document" not in metadata


def test_default_retrieval_respects_editorial_eligibility(tmp_path):
    catalog = _catalog(tmp_path)
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"resolved_profile": {"profile_id": "generated-fixture"},
                                  "libraries": {"visual_references": {"catalog": str(catalog)}}}))
    intent = tmp_path / "intent.json"
    intent.write_text(json.dumps({"communication_job": "explain staged roadmap",
                                  "information_structure": {"type": "roadmap"},
                                  "semantic_relationships": ["sequence", "stages"]}))
    result = retrieve(config, intent, tmp_path / "candidates.json", tmp_path / "candidates.png", authenticity="any")
    assert result["candidates"]
    assert all(e["metadata"].get("retrieval_eligible") is not False for e in result["candidates"])
    assert any(e["metadata"]["source_page"] == 4 for e in result["candidates"])
    assert "selected_visual_references" not in result
