"""M6 sync: certified-only payload, sha256-checked install, ack names compared exactly, signed bytes."""
from __future__ import annotations

import shutil

import pytest

from mxstudio.fonts.install import Account, MemoryBackend
from mxstudio.fonts.sync import (SyncRefused, apply_payload, build_payload, encode, sign_payload, verify_ack,
                                 verify_payload, verify_signed)

QA = {"families": [{"family": "Tajawal", "status": "certified_print"},
                   {"family": "Amiri", "status": "certified_print"},
                   {"family": "Reem Kufi Fun", "status": "screen_only"}]}
OPERATOR = Account("operator", "S-1-5-21-1-1001")
SERVICE = Account("SYSTEM", "S-1-5-18", session_id=0, is_service=True)


@pytest.fixture()
def payload(fonts):
    return build_payload("set-2026-10", [{"path": fonts["tajawal"], "family": "Tajawal", "roles": ["body"]},
                                         {"path": fonts["amiri"], "family": "Amiri", "roles": ["body", "title"]}], QA)


@pytest.fixture()
def files_dir(fonts, tmp_path):
    folder = tmp_path / "incoming"
    folder.mkdir()
    for key in ("tajawal", "amiri"):
        shutil.copy(fonts[key], folder)
    return folder


def test_payload_shape(payload):
    assert payload["set_id"] == "set-2026-10"
    first = payload["fonts"][0]
    assert first["file"] == "Tajawal-Regular.ttf" and first["install_names"] == ["Tajawal"]
    assert len(first["sha256"]) == 64 and first["roles"] == ["body"]


def test_round_trip_to_an_ack(payload, files_dir, tmp_path):
    backend = MemoryBackend(tmp_path / "machine", account=OPERATOR)
    ack = apply_payload(payload, files_dir, backend, exporter=OPERATOR)
    assert ack["installed"][0] == {"file": "Tajawal-Regular.ttf", "windows_reported_name": "Tajawal",
                                   "scope": "user"}
    assert verify_ack(payload, ack, installer=OPERATOR) == []


def test_service_exporter_gets_machine_scope(payload, files_dir, tmp_path):
    backend = MemoryBackend(tmp_path / "m2", admin=True, account=OPERATOR)
    ack = apply_payload(payload, files_dir, backend, exporter=SERVICE)
    assert {i["scope"] for i in ack["installed"]} == {"machine"}
    assert verify_ack(payload, ack, installer=OPERATOR) == []


def test_negative_control_uncertified_font_is_refused(fonts):
    with pytest.raises(SyncRefused) as excinfo:
        build_payload("s", [{"path": fonts["reemkufifun"], "family": "Reem Kufi Fun", "roles": ["title"]}], QA)
    assert excinfo.value.findings[0]["finding"] == "sync_font_not_certified"


def test_negative_control_tampered_bytes_are_refused(payload, files_dir, tmp_path):
    with open(files_dir / "Amiri-Regular.ttf", "ab") as handle:
        handle.write(b"x")
    assert [f["finding"] for f in verify_payload(payload, files_dir)] == ["sync_sha256_mismatch"]
    with pytest.raises(SyncRefused):
        apply_payload(payload, files_dir, MemoryBackend(tmp_path / "m3"), exporter=OPERATOR)


def test_negative_control_ack_problems_are_named(payload):
    entry = dict(payload["fonts"][0], install_names=["Blabeloo  MagdySoliman"])  # two spaces, as in real decks
    bad_payload = {**payload, "fonts": [entry, payload["fonts"][1]]}
    ack = {"set_id": payload["set_id"], "account": {"name": "SYSTEM", "sid": "S-1-5-18", "session_id": 0,
                                                    "is_service": True},
           "installed": [{"file": "Tajawal-Regular.ttf", "windows_reported_name": "Blabeloo MagdySoliman",
                          "scope": "user"},
                         {"file": "Extra.ttf", "windows_reported_name": "Extra", "scope": "machine"}]}
    found = [f["finding"] for f in verify_ack(bad_payload, ack, installer=OPERATOR)]
    assert found == ["sync_reported_name_mismatch", "sync_scope_invisible_to_exporter", "sync_file_not_installed",
                     "sync_ack_unexpected_file"]


def test_signed_with_the_operator_contract(payload):
    raw = encode(payload)
    headers = sign_payload(raw, "s3cret", timestamp=1_760_000_000)
    assert verify_signed(raw, headers, "s3cret", now=1_760_000_010) == (True, "ok")
    assert verify_signed(raw.replace(b"set-2026-10", b"set-2026-11"), headers, "s3cret",
                         now=1_760_000_010) == (False, "signature mismatch")
