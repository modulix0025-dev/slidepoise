"""The local server: loopback only, CSRF on mutations, human-only confirmation, write-only secrets."""
from __future__ import annotations

import json
import warnings

import httpx
import pytest

warnings.filterwarnings("ignore", category=DeprecationWarning)
from starlette.testclient import TestClient  # noqa: E402

from mxstudio.app.runner import read_lock, running_instance, serve, shutdown  # noqa: E402
from mxstudio.app.server import create_app  # noqa: E402
from mxstudio.app.state import AppState  # noqa: E402


@pytest.fixture()
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("MXS_WORKSPACE", str(tmp_path / "المشروع" / "ModuleX_MagazineStudio_Data"))
    return AppState.create(tmp_path / "home")


def _ui(state):
    client = TestClient(create_app(state), client=("127.0.0.1", 50123))
    client.get("/")
    csrf = client.get("/api/session").json()["csrf"]
    return client, {"X-MXS-CSRF": csrf}


def test_non_loopback_peers_are_refused(state):
    remote = TestClient(create_app(state), client=("10.0.0.5", 4000))
    response = remote.get("/api/health")
    assert response.status_code == 403 and response.json()["code"] == "LOOPBACK_ONLY"
    local = TestClient(create_app(state), client=("127.0.0.1", 4000))
    assert local.get("/api/health").json()["ok"] is True


def test_mutations_need_the_session_csrf(state):
    client, headers = _ui(state)
    assert client.post("/api/settings", json={"theme": "night"}).status_code == 403
    assert client.post("/api/settings", json={"theme": "night"}, headers={"X-MXS-CSRF": "guess"}).status_code == 403
    assert client.post("/api/settings", json={"theme": "night"}, headers=headers).json()["theme"] == "night"
    assert client.post("/api/settings", json={"api_key": "x"}, headers=headers).status_code == 400


def test_secrets_never_come_back(state):
    client, headers = _ui(state)
    client.post("/api/secrets/provider.text_vision", json={"value": "sk-live-abc"}, headers=headers)
    listing = client.get("/api/secrets").json()
    everything = json.dumps(listing) + json.dumps(client.get("/api/settings").json()) + \
        json.dumps(client.get("/api/audit").json())
    assert "sk-live-abc" not in everything and listing["secrets"][0]["fingerprint"]


def test_irreversible_tool_flow_through_http(state):
    client, headers = _ui(state)
    ws = state.workspace
    ws.save("template_set", "golden_fish", {"t": 1})
    args = {"kind": "template_set", "key": "golden_fish", "version": 1, "approved_by": "ModuleX operator"}
    refused = client.post("/api/tools/workspace.approve", json={"args": args, "actor": "agent"}, headers=headers).json()
    assert refused["code"] == "CONFIRMATION_REQUIRED"
    agent = TestClient(create_app(state), client=("127.0.0.1", 50999))  # no UI session → cannot mint
    assert agent.post("/api/confirm", json={"tool": "workspace.approve", "args": args}).status_code == 403
    token = client.post("/api/confirm", json={"tool": "workspace.approve", "args": args}, headers=headers).json()["token"]
    ok = client.post("/api/tools/workspace.approve", json={"args": args, "actor": "agent", "confirmation_token": token},
                     headers=headers).json()
    assert ok["ok"] is True and ws.get("template_set", "golden_fish", 1)["approved"]
    photo = client.post("/api/tools/customer_photo.ai_edit", json={"args": {"order": "x"}}, headers=headers).json()
    assert photo["code"] == "FORBIDDEN_BY_OPERATOR_RULE"


def test_m0_contract_and_features(state):
    client, _ = _ui(state)
    assert client.get("/internal/mag/v1/health").json()["contract"] == "mag/v1"
    contract = client.get("/internal/mag/v1/contract").json()
    assert contract["contract"] == "mag/v1" and "signing" in contract
    assert isinstance(client.get("/api/features").json()["features"], dict)
    assert client.get("/ui/../server.py").status_code == 404


def test_runner_single_instance_lockfile_and_shutdown(tmp_path, monkeypatch):
    monkeypatch.setenv("MXS_WORKSPACE", str(tmp_path / "ws"))
    home = tmp_path / "home"
    server, thread, port = serve(home, block=False)
    try:
        assert httpx.get(f"http://127.0.0.1:{port}/api/health").json()["ok"]
        assert running_instance(home)["port"] == port
        with pytest.raises(RuntimeError, match="already running"):
            serve(home, block=False)
        assert httpx.post(f"http://127.0.0.1:{port}/api/shutdown", headers={"X-MXS-Shutdown": "wrong"}).status_code == 403
        assert shutdown(home) is True
        thread.join(timeout=10)
        assert not thread.is_alive()
        assert read_lock(home) is None
    finally:
        server.should_exit = True
