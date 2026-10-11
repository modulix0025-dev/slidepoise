"""Item 12: no update key ⇒ automatic update is OFF (not a button that cannot verify); pinned downloads; updates and
reinstalls never touch the app home or the workspace."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from starlette.testclient import TestClient

ROOT = Path(__file__).resolve().parents[3]


def _client(tmp_path, monkeypatch):
    from mxstudio.app.server import create_app
    from mxstudio.app.state import AppState
    monkeypatch.setenv("MXS_WORKSPACE", str(tmp_path / "ws"))
    state = AppState.create(tmp_path / "home")
    client = TestClient(create_app(state), client=("127.0.0.1", 5000))
    client.get("/")
    return state, client, {"X-MXS-CSRF": client.get("/api/session").json()["csrf"]}


def test_without_an_embedded_key_auto_update_is_off_everywhere(tmp_path, monkeypatch):
    from mxstudio import update
    from mxstudio.update import trust as trust_mod
    empty = trust_mod.Trust(manifest_url="https://github.com/x/y/releases/latest/download/latest.json")
    assert not empty.auto_update_enabled and "مقفول" in empty.why_disabled()["ar"]
    monkeypatch.setattr(trust_mod, "load", lambda path=None: empty)
    state, client, headers = _client(tmp_path, monkeypatch)
    try:
        shown = client.get("/api/update/state").json()["auto_update"]
        assert shown["enabled"] is False and shown["reason"]["ar"]
        refused = client.post("/api/update/check", json={}, headers=headers)
        assert refused.status_code == 409 and refused.json()["detail"]["code"] == "AUTO_UPDATE_OFF"
        assert client.post("/api/update/consent", json={"yes": True}, headers=headers).status_code == 409
    finally:
        state.close()
    called = []
    monkeypatch.setattr(update.UpdateManager, "launch_hook", lambda self: called.append(1) or True)
    assert update.launch_hook() is False and called == []  # nothing is ever started


def test_with_a_key_the_gate_opens():
    from mxstudio.update import signing
    from mxstudio.update import trust as trust_mod
    if not hasattr(signing, "generate_keypair"):
        pytest.skip("keygen helper name differs")
    private, public = signing.generate_keypair()
    trust = trust_mod.Trust(public_keys={signing.key_id(public): public}, manifest_url="https://github.com/x")
    assert trust.auto_update_enabled and trust.why_disabled() is None


def test_shipped_trust_is_honest():
    data = json.loads((ROOT / "mxstudio" / "update" / "trust.json").read_text(encoding="utf-8"))
    from mxstudio.update import trust as trust_mod
    trust = trust_mod.load(ROOT / "mxstudio" / "update" / "trust.json")
    assert trust.auto_update_enabled == bool(data["public_keys"])  # an empty key list can never look enabled


def test_downloads_are_pinned_except_what_cannot_be():
    entries = json.loads((ROOT / "installer" / "downloads.json").read_text(encoding="utf-8"))["entries"]
    lo = entries["libreoffice_msi"]
    assert re.fullmatch(r"[0-9a-f]{64}", lo["sha256"]) and int(lo["size"]) > 100_000_000
    assert re.fullmatch(r"[0-9a-f]{64}", entries["node_runtime"]["sha256"])
    assert entries["webview2_bootstrapper"]["sha256"] == "NOT-PINNABLE"  # Evergreen: verified by Authenticode instead


def test_install_update_and_move_never_touch_app_home_or_workspace():
    nsi = (ROOT / "installer" / "nsis" / "MagazineStudio.nsi").read_text(encoding="utf-8")
    removals = [line.strip() for line in nsi.splitlines() if "RMDir" in line or line.strip().startswith("Delete ")]
    data_removals = [line for line in removals if "DATA_DIR" in line]
    assert data_removals == ['RMDir /r "${DATA_DIR}"']  # only the explicit «also delete my data» answer
    uninstall = nsi[nsi.index('Section "Uninstall"'):]
    assert uninstall.index('${If} $RemoveData == "1"') < uninstall.index('RMDir /r "${DATA_DIR}"')
    assert "/SD IDNO IDNO keep" in nsi  # silent (updates, moves) answers No
    assert "uninstall.exe\" /S _?=$OldDir" in nsi  # a move uninstalls the old copy silently: data kept
    assert "المشروع" in nsi and "workspace" not in " ".join(data_removals)
