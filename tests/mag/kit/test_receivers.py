"""Signed receivers (M1/M2/M6/M7) and signed packs — valid, bad signature, replay, stale, schema, activation."""
from __future__ import annotations

import copy
import hashlib
import io
import json
import zipfile
from pathlib import Path

import jsonschema
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mxstudio.kit import _vendor
from mxstudio.receivers import SCHEMA_FILES
from mxstudio.receivers.activation import activate_template_set
from mxstudio.receivers.ingest import SCHEMAS_DIR, load_schema
from mxstudio.receivers.packs import PackError, build_pack, embed_files, import_pack, read_pack
from mxstudio.receivers.routers import PREFIX, build_router
from mxstudio.receivers.signing_gate import SignedRequestGate
from mxstudio.receivers.store import CandidateStore, confirm_code
from mxstudio.receivers.validate import SchemaError, validate

SECRET = "test-shared-secret-mag"
NOW = 1_800_000_000
SIGNING = _vendor.signing()
DECK = b"PK\x03\x04 synthetic deck bytes"
DECK_SHA = hashlib.sha256(DECK).hexdigest()
ENVELOPE = {"schema_version": 1, "produced_by": {"app": "ModuleX Magazine Studio", "version": "0.8.0"},
            "created_at": "2026-10-11T12:00:00Z"}


def m1_doc(**over):
    doc = {**ENVELOPE, "contract": "mag/v1/m1", "story_key": "moon_trip", "display_name": "رحلة القمر",
           "variants": {"A5": {"ar": {"male": {"file": "moon_trip_ar_boy_A5.pptx", "sha256": DECK_SHA, "base_name": "إياد"},
                                      "female": {"file": "moon_trip_ar_girl_A5.pptx", "sha256": DECK_SHA,
                                                 "base_name": "جيداء"}}}},
           "replacements_additions": {"بكل الحب تهدى لإياد": "بكل الحب تهدى لـ{child_name}"},
           "validator_report_sha256": "a" * 64}
    doc.update(over)
    return doc


DOCS = {
    "m1": m1_doc(),
    "m2": {**ENVELOPE, "contract": "mag/v1/m2", "story_key": "moon_trip", "display_name": "رحلة القمر",
           "reference": "moon-ref", "variants": {"boy_a5": "moon_trip_ar_boy_A5.pptx"},
           "variant_sha256": {"boy_a5": DECK_SHA}, "slot_map": {"boy_a5": {"1": 1, "3": 2}},
           "measured_with": "deck_picture_slots@234be093"},
    "m6": {**ENVELOPE, "contract": "mag/v1/m6", "set_id": "kids-core-1",
           "fonts": [{"file": "MXKids-Amiri.ttf", "sha256": "b" * 64, "install_names": ["MX Kids Amiri"],
                      "roles": ["body"], "licence": "OFL-1.1"}]},
    "m7": {**ENVELOPE, "contract": "mag/v1/m7", "story_key": "moon_trip",
           "roles": {"child_name": [{"font_id": "mx-kids-amiri", "display_name_ar": "أميري", "price_tokens": 0}]}},
}
ROUTE = {"m1": "m1/template-set", "m2": "m2/deck-contract", "m6": "m6/font-set", "m7": "m7/font-choices"}


class FakeEngine:
    def __init__(self):
        self.calls = []

    def add_story(self, display_name, ar_male_file, ar_male_base, ar_female_file, ar_female_base,
                  en_male_file=None, en_male_base=None, en_female_file=None, en_female_base=None, size="A5"):
        self.calls.append({"display_name": display_name, "ar_male_file": ar_male_file, "ar_male_base": ar_male_base,
                           "ar_female_file": ar_female_file, "ar_female_base": ar_female_base, "size": size})
        return display_name


@pytest.fixture()
def client(tmp_path):
    clock = {"now": NOW}
    guard = SIGNING.ReplayGuard(ttl_seconds=300, max_entries=100, env={})
    gate = SignedRequestGate(SIGNING, lambda: SECRET, guard=guard, now=lambda: clock["now"])
    store = CandidateStore(tmp_path / "mag_candidates")
    engine = FakeEngine()
    templates = tmp_path / "story_templates"
    templates.mkdir()

    def activator(doc, cdir):
        return activate_template_set(doc, cdir, story_engine=engine, templates_dir=templates)

    app = FastAPI()
    app.include_router(build_router(kinds=("m1", "m2", "m6", "m7"), gate=gate, store=store, activator=activator,
                                    system="OM"))
    c = TestClient(app)
    c.clock, c.store, c.engine, c.templates = clock, store, engine, templates
    return c


def signed(c, method, path, body=b"", *, ts=None, secret=SECRET):
    headers = SIGNING.sign(secret, method, path, body, timestamp=ts if ts is not None else c.clock["now"])
    headers["Content-Type"] = "application/json"
    return c.request(method, path, content=body, headers=headers)


def raw(doc):
    return json.dumps(doc, ensure_ascii=False).encode("utf-8")


@pytest.mark.parametrize("kind", ["m1", "m2", "m6", "m7"])
def test_valid_signed_document_becomes_a_candidate(client, kind):
    r = signed(client, "POST", f"{PREFIX}/{ROUTE[kind]}", raw(DOCS[kind]))
    assert r.status_code == 202, r.json()
    body = r.json()
    assert body["status"] == "candidate" and body["candidate_id"].startswith(kind + "-")
    listed = signed(client, "GET", f"{PREFIX}/candidates/{kind}").json()["candidates"]
    assert [c["candidate_id"] for c in listed] == [body["candidate_id"]]
    assert "confirm_code_sha256" not in listed[0]


def test_bad_signature_is_refused(client):
    r = signed(client, "POST", f"{PREFIX}/m7/font-choices", raw(DOCS["m7"]), secret="wrong-secret")
    assert r.status_code == 401 and r.json()["reason"] == "signature mismatch"
    assert client.store.list("m7") == []


def test_signature_is_bound_to_method_and_path(client):
    body = raw(DOCS["m7"])
    headers = SIGNING.sign(SECRET, "POST", f"{PREFIX}/m2/deck-contract", body, timestamp=NOW)
    r = client.post(f"{PREFIX}/m7/font-choices", content=body, headers=headers)
    assert r.status_code == 401


def test_replay_is_refused(client):
    body = raw(DOCS["m7"])
    headers = SIGNING.sign(SECRET, "POST", f"{PREFIX}/m7/font-choices", body, timestamp=NOW)
    assert client.post(f"{PREFIX}/m7/font-choices", content=body, headers=headers).status_code == 202
    again = client.post(f"{PREFIX}/m7/font-choices", content=body, headers=headers)
    assert again.status_code == 409 and "replayed" in again.json()["reason"]


def test_stale_timestamp_is_refused(client):
    r = signed(client, "POST", f"{PREFIX}/m7/font-choices", raw(DOCS["m7"]), ts=NOW - 301)
    assert r.status_code == 401 and r.json()["reason"] == "timestamp outside allowed skew"


def test_missing_headers_and_missing_secret(client, tmp_path):
    assert client.get(f"{PREFIX}/health").status_code == 401
    gate = SignedRequestGate(SIGNING, lambda: None)
    app = FastAPI()
    app.include_router(build_router(kinds=("m7",), gate=gate, store=CandidateStore(tmp_path / "x")))
    assert TestClient(app).get(f"{PREFIX}/health").status_code == 503


def test_signed_health_and_contract(client):
    assert signed(client, "GET", f"{PREFIX}/health").json()["kinds"] == ["m1", "m2", "m6", "m7"]
    schemas = signed(client, "GET", f"{PREFIX}/contract").json()["schemas_sha256"]
    assert schemas["m1"] == hashlib.sha256((SCHEMAS_DIR / SCHEMA_FILES["m1"]).read_bytes()).hexdigest()


def test_schema_violation_is_named(client):
    doc = copy.deepcopy(DOCS["m2"])
    doc["slot_map"]["boy_a5"]["0"] = 1  # slide numbers start at 1
    r = signed(client, "POST", f"{PREFIX}/m2/deck-contract", raw(doc))
    assert r.status_code == 422 and any("slot_map.boy_a5" in e for e in r.json()["errors"])


def test_cross_checks_beyond_schema(client):
    doc = copy.deepcopy(DOCS["m2"])
    doc["slot_map"]["girl_a5"] = {"1": 1}
    r = signed(client, "POST", f"{PREFIX}/m2/deck-contract", raw(doc))
    assert r.status_code == 422 and "not a declared variant" in r.json()["errors"][0]
    bad_file = embed_files(m1_doc(), {"moon_trip_ar_boy_A5.pptx": b"other bytes"})
    r = signed(client, "POST", f"{PREFIX}/m1/template-set", raw(bad_file))
    assert r.status_code == 422 and "sha256 differs" in r.json()["errors"][0]


def test_duplicate_is_idempotent(client):
    body = raw(DOCS["m6"])
    first = signed(client, "POST", f"{PREFIX}/m6/font-set", body).json()
    client.clock["now"] += 1  # new timestamp -> new signature, same document
    second = signed(client, "POST", f"{PREFIX}/m6/font-set", body)
    assert second.status_code == 200 and second.json()["duplicate"] is True
    assert second.json()["candidate_id"] == first["candidate_id"]


def test_m1_activation_needs_the_operator_code_and_goes_through_add_story(client):
    doc = embed_files(m1_doc(), {"moon_trip_ar_boy_A5.pptx": DECK, "moon_trip_ar_girl_A5.pptx": DECK})
    body = raw(doc)
    cid = signed(client, "POST", f"{PREFIX}/m1/template-set", body).json()["candidate_id"]
    path = f"{PREFIX}/m1/candidates/{cid}/activate"
    client.clock["now"] += 1
    refused = signed(client, "POST", path, json.dumps({"operator_confirmation": "nope"}).encode())
    assert refused.status_code == 403 and client.engine.calls == []
    client.clock["now"] += 1
    ok = signed(client, "POST", path, json.dumps({"operator_confirmation": confirm_code(body)}).encode())
    assert ok.status_code == 200, ok.json()
    assert ok.json()["function"] == "add_story"
    assert client.engine.calls == [{"display_name": "رحلة القمر", "ar_male_file": "moon_trip_ar_boy_A5.pptx",
                                    "ar_male_base": "إياد", "ar_female_file": "moon_trip_ar_girl_A5.pptx",
                                    "ar_female_base": "جيداء", "size": "A5"}]
    assert sorted(p.name for p in client.templates.iterdir()) == ["moon_trip_ar_boy_A5.pptx",
                                                                 "moon_trip_ar_girl_A5.pptx"]
    assert client.store.list("m1")[0]["status"] == "activated"


def test_activation_blocks_on_unfillable_parameters_and_never_overwrites(tmp_path):
    class Strict:
        def add_story(self, display_name, ar_male_file, ar_male_base, ar_female_file, ar_female_base, owner_id):
            raise AssertionError("must not be called")

    cdir = tmp_path / "cand"
    (cdir / "files").mkdir(parents=True)
    res = activate_template_set(m1_doc(), cdir, story_engine=Strict(), templates_dir=tmp_path)
    assert res["status"] == "blocked" and res["missing"] == ["owner_id"]
    (cdir / "files" / "moon_trip_ar_boy_A5.pptx").write_bytes(DECK)
    (tmp_path / "t").mkdir()
    (tmp_path / "t" / "moon_trip_ar_boy_A5.pptx").write_bytes(b"operator's existing file")
    res = activate_template_set(m1_doc(), cdir, story_engine=FakeEngine(), templates_dir=tmp_path / "t")
    assert res["status"] == "blocked" and "already exists" in res["reason"]
    assert (tmp_path / "t" / "moon_trip_ar_boy_A5.pptx").read_bytes() == b"operator's existing file"


# ---------------------------------------------------------------- packs ----

def test_pack_roundtrip_through_the_same_ingest_path(tmp_path):
    files = {"moon_trip_ar_boy_A5.pptx": DECK}
    pack = build_pack("m1", m1_doc(), secret=SECRET, signing=SIGNING, pack_id="moon-trip-1", files=files,
                      timestamp=NOW)
    assert pack == build_pack("m1", m1_doc(), secret=SECRET, signing=SIGNING, pack_id="moon-trip-1", files=files,
                              timestamp=NOW)  # deterministic
    store = CandidateStore(tmp_path / "c")
    status, body = import_pack(pack, secret=SECRET, signing=SIGNING, store=store)
    assert status == 202 and body["pack_id"] == "moon-trip-1"
    meta = store.list("m1")[0]
    assert meta["source"] == "pack:moon-trip-1" and meta["files"] == {"moon_trip_ar_boy_A5.pptx": DECK_SHA}
    assert import_pack(pack, secret=SECRET, signing=SIGNING, store=store)[1]["duplicate"] is True


def _rezip(pack: bytes, mutate) -> bytes:
    src = zipfile.ZipFile(io.BytesIO(pack))
    members = {n: src.read(n) for n in src.namelist()}
    mutate(members)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, d in members.items():
            z.writestr(n, d)
    return buf.getvalue()


@pytest.mark.parametrize("mutation,reason", [
    (lambda m: m.__setitem__("files/moon_trip_ar_boy_A5.pptx", b"swapped"), "sha256 mismatch"),
    (lambda m: m.__setitem__("manifest.json", m["manifest.json"].replace(b"moon-trip-1", b"moon-trip-2")),
     "signature mismatch"),
    (lambda m: m.__setitem__("files/extra.pptx", b"x"), "undeclared members"),
    (lambda m: m.__setitem__("../evil.py", b"x"), "unsafe member"),
    (lambda m: m.__setitem__("document.json", b"{}"), "document.json sha256 mismatch"),
])
def test_tampered_packs_are_refused(tmp_path, mutation, reason):
    pack = build_pack("m1", m1_doc(), secret=SECRET, signing=SIGNING, pack_id="moon-trip-1",
                      files={"moon_trip_ar_boy_A5.pptx": DECK}, timestamp=NOW)
    with pytest.raises(PackError, match=reason):
        read_pack(_rezip(pack, mutation), secret=SECRET, signing=SIGNING)
    status, _ = import_pack(_rezip(pack, mutation), secret=SECRET, signing=SIGNING,
                               store=CandidateStore(tmp_path / "c"))
    assert status == 400 and not (tmp_path / "c").exists()


def test_pack_with_wrong_secret_is_refused():
    pack = build_pack("m7", DOCS["m7"], secret=SECRET, signing=SIGNING, pack_id="fonts-1", timestamp=NOW)
    with pytest.raises(PackError, match="signature mismatch"):
        read_pack(pack, secret="another-secret", signing=SIGNING)


# ---------------------------------------------------------------- schemas ----

@pytest.mark.parametrize("kind", ["m1", "m2", "m6", "m7"])
def test_subset_validator_agrees_with_jsonschema(kind):
    schema = load_schema(kind)
    jsonschema.Draft202012Validator.check_schema(schema)
    good = DOCS[kind]
    bad_docs = [dict(good, contract="mag/v1/zz"), {k: v for k, v in good.items() if k != "produced_by"},
                dict(good, unexpected=1), dict(good, schema_version=2), dict(good, created_at="yesterday")]
    for doc, expect_ok in [(good, True)] + [(b, False) for b in bad_docs]:
        mine = validate(doc, schema) == []
        ref = jsonschema.Draft202012Validator(schema).is_valid(doc)
        assert mine == ref == expect_ok, (kind, doc)


def test_validator_refuses_unknown_keywords():
    with pytest.raises(SchemaError):
        validate({}, {"type": "object", "if": {}})


def test_receivers_package_is_relocatable():
    """The payload copied into the operator's systems may import only stdlib, fastapi and itself."""
    pkg = Path(__file__).resolve().parents[3] / "mxstudio" / "receivers"
    for path in pkg.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "mxstudio" not in text.replace("``mxstudio``", "").split('"""', 2)[-1], path.name
        assert "import jsonschema" not in text
