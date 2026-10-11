"""«ابدأ هنا» chat (text + pictures + revisions), pending approvals, the Claude provider and the MCP server."""
from __future__ import annotations

import base64
import io
import json
import os
import subprocess
import sys
import warnings
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from starlette.testclient import TestClient

from mxstudio.agent.tools import Tool, ToolError
from mxstudio.app.server import create_app
from mxstudio.app.state import AppState

ROOT = Path(__file__).resolve().parents[3]
warnings.filterwarnings("ignore", category=DeprecationWarning)


def _png(colour="#F2A33A", size=(64, 48)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, "PNG")
    return out.getvalue()


@pytest.fixture()
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("MXS_WORKSPACE", str(tmp_path / "المشروع" / "data"))
    st = AppState.create(tmp_path / "home")
    yield st
    st.close()


def _ui(state):
    app = create_app(state)
    client = TestClient(app, client=("127.0.0.1", 50123))
    client.get("/")
    csrf = client.get("/api/session").json()["csrf"]
    return app, client, {"X-MXS-CSRF": csrf}


# -- pending approvals ------------------------------------------------------------------
def test_agent_irreversible_request_is_queued_and_only_a_human_decides(state):
    state.workspace.save("template_set", "moon", {"validation": {"ok": True}})
    args = {"kind": "template_set", "key": "moon", "version": 1, "approved_by": "operator"}
    asked = state.tools.call("workspace.approve", args, actor="agent:mcp")
    assert asked["code"] == "CONFIRMATION_REQUIRED" and asked["pending_id"]
    again = state.tools.call("workspace.approve", args, actor="agent")
    assert again["pending_id"] == asked["pending_id"]  # one request, not two
    assert state.workspace.get("template_set", "moon")["approved"] is False
    for actor in ("agent", "agent:mcp", "ui"):  # an agent (or a forged non-session actor) cannot decide
        with pytest.raises(ToolError):
            state.tools.decide(asked["pending_id"], True, actor)
    done = state.tools.decide(asked["pending_id"], True, "ui:abcd1234")
    assert done["ok"] and done["status"] == "approved"
    assert state.workspace.get("template_set", "moon")["approved"] is True
    entry = state.tools.audit.entries(5)[0]
    assert entry["actor"] == "ui:abcd1234" and entry["outcome"] == "ok" and entry["token"]
    with pytest.raises(ToolError):  # decided once, never again
        state.tools.decide(asked["pending_id"], True, "ui:abcd1234")


def test_rejected_request_never_runs_and_ui_decision_needs_the_session(state):
    state.workspace.save("template_set", "sea", {"validation": {"ok": True}})
    asked = state.tools.call("workspace.approve", {"kind": "template_set", "key": "sea", "version": 1,
                                                    "approved_by": "operator"}, actor="agent")
    app, client, headers = _ui(state)
    assert client.get("/api/pending").json()["pending"][0]["id"] == asked["pending_id"]
    url = f"/api/pending/{asked['pending_id']}/decide"
    assert client.post(url, json={"approve": True}).status_code == 403  # no CSRF header: not the Studio window
    assert client.post(url, json={"approve": False}, headers=headers).json()["status"] == "rejected"
    assert state.workspace.get("template_set", "sea")["approved"] is False
    assert client.get("/api/pending").json()["pending"] == []


# -- uploads ----------------------------------------------------------------------------------
def test_upload_accepts_real_pictures_only_and_serves_them(state):
    app, client, headers = _ui(state)
    data = _png()
    ok = client.post("/api/uploads", json={"name": "design.png", "data_b64": base64.b64encode(data).decode()},
                     headers=headers).json()
    sha = ok["reference"]["sha"]
    assert ok["ok"] and ok["reference"]["width"] == 64
    served = client.get(f"/api/blobs/{sha}")
    assert served.status_code == 200 and served.headers["content-type"] == "image/png" and served.content == data
    bad = client.post("/api/uploads", json={"name": "x.png", "data_b64": base64.b64encode(b"not an image").decode()},
                      headers=headers)
    assert bad.status_code == 400
    text_sha = state.workspace.put_bytes(b"secret notes")
    assert client.get(f"/api/blobs/{text_sha}").status_code == 404  # only pictures are served
    assert client.get("/api/blobs/../../etc").status_code == 404
    refs = state.tools.call("studio.references", {}, actor="agent")["result"]["references"]
    assert refs[0]["sha"] == sha


# -- chat ---------------------------------------------------------------------------------------
class ScriptedVisionModel:
    """Replays moves and records what it was shown (text + pictures) on every call."""

    def __init__(self, moves):
        self.moves, self.seen = list(moves), []

    def chat(self, messages, **_kw):
        self.seen.append([{"role": m["role"], "content": m["content"], "images": len(m.get("images") or [])}
                          for m in messages])
        move = self.moves.pop(0) if self.moves else {"final": "done"}
        return {"text": json.dumps(move, ensure_ascii=False), "usage": {}}


def test_chat_sees_pictures_previews_and_history_and_queues_irreversible(state, monkeypatch):
    app, client, headers = _ui(state)
    preview_sha = state.workspace.put_bytes(_png("#336699", (400, 300)))
    state.tools.register(Tool("test.fake_build", "x", "fake build with a preview", {"type": "object"},
                              lambda args: {"ok": True, "preview_sha": preview_sha}))
    state.settings.update({"agent": {"mode": "full"}})
    ref = client.post("/api/uploads", json={"name": "d.png", "data_b64": base64.b64encode(_png()).decode()},
                      headers=headers).json()["reference"]["sha"]
    model = ScriptedVisionModel([
        {"plan": ["read the picture", "build"]},
        {"tool": "colour.from_art", "args": {"reference": ref, "k": 3}},
        {"tool": "test.fake_build", "args": {}},
        {"final": "بنيت أول نسخة"},
        {"tool": "workspace.approve", "args": {"kind": "template_set", "key": "x", "version": 1, "approved_by": "me"}},
    ])
    monkeypatch.setattr("mxstudio.agent.api._provider", lambda _state: model)
    conversation = client.post("/api/agent/conversations", json={"title": "test"}, headers=headers).json()["id"]
    first = client.post(f"/api/agent/conversations/{conversation}/messages",
                        json={"text": "قصة عن البحر بألوان الصورة دي", "references": [ref]}, headers=headers).json()
    assert first["status"] == "done" and first["reply"] == "بنيت أول نسخة" and first["preview_sha"] == preview_sha
    assert model.seen[0][-1]["images"] == 1  # the operator's picture went to the model
    palette = json.loads(model.seen[2][-1]["content"].split("\n(Attached")[0])
    assert palette["instruction_like_text_found"] is False and "colours" in palette["content"]
    assert model.seen[3][-1]["images"] == 1  # the build preview went back to the model to look at
    second = client.post(f"/api/agent/conversations/{conversation}/messages",
                         json={"text": "خلاص اعتمده"}, headers=headers).json()
    assert second["status"] == "needs_confirmation" and second["pending"]["pending_id"]
    history = model.seen[4]
    assert any(m["content"].startswith("قصة عن البحر") for m in history)  # the revision turn sees turn one
    assert sum(m["images"] for m in history) == 2  # earlier picture + earlier preview re-attached
    shown = client.get(f"/api/agent/conversations/{conversation}").json()
    assert [m["who"] for m in shown["messages"]][:3] == ["operator", "agent", "agent"]
    assert shown["messages"][0]["image_shas"] == [ref] and shown["previews"] == [preview_sha]
    assert client.get("/api/pending").json()["pending"][0]["tool"] == "workspace.approve"


def test_chat_without_a_model_says_how_to_set_one(state):
    app, client, headers = _ui(state)
    conversation = client.post("/api/agent/conversations", json={}, headers=headers).json()["id"]
    answer = client.post(f"/api/agent/conversations/{conversation}/messages", json={"text": "hi"}, headers=headers)
    assert answer.status_code == 409 and "الإعدادات" in answer.json()["detail"]["ar"]


def test_suggestion_only_mode_is_said_to_the_model(state, monkeypatch):
    app, client, headers = _ui(state)
    model = ScriptedVisionModel([{"final": "خطة بس"}])
    monkeypatch.setattr("mxstudio.agent.api._provider", lambda _state: model)
    conversation = client.post("/api/agent/conversations", json={}, headers=headers).json()["id"]
    reply = client.post(f"/api/agent/conversations/{conversation}/messages", json={"text": "ابني"},
                        headers=headers).json()
    assert reply["mode"] == "suggest_only" and model.seen[0][-1]["content"].startswith("SUGGESTION-ONLY MODE")


# -- providers ------------------------------------------------------------------------------------
class FakeAnthropic:
    def __init__(self, stop_reason="end_turn"):
        self.calls, self.stop_reason = [], stop_reason
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(stop_reason=self.stop_reason, model=kwargs["model"],
                               content=[SimpleNamespace(type="thinking", thinking=""),
                                        SimpleNamespace(type="text", text='{"final": "ok"}')],
                               usage=SimpleNamespace(input_tokens=10, output_tokens=5))


def test_claude_provider_sends_system_pictures_effort_and_fallbacks():
    from mxstudio.providers.base import AnthropicClaude
    fake = FakeAnthropic()
    provider = AnthropicClaude(api_key="k", client=fake)
    reply = provider.chat([{"role": "system", "content": "rules"}, {"role": "user", "content": "hi", "images": [_png()]},
                           {"role": "assistant", "content": '{"plan": []}'}, {"role": "user", "content": "go"}])
    call = fake.calls[0]
    assert reply["text"] == '{"final": "ok"}' and call["model"] == "claude-opus-5-5"
    assert call["system"] == "rules" and call["fallbacks"] == "default"
    assert call["betas"] == ["server-side-fallback-2026-07-01"] and call["output_config"] == {"effort": "medium"}
    first = call["messages"][0]["content"]
    assert first[0]["type"] == "image" and first[0]["source"]["media_type"] == "image/png" and first[-1]["text"] == "hi"
    assert [m["role"] for m in call["messages"]] == ["user", "assistant", "user"]
    refused = AnthropicClaude(api_key="k", client=FakeAnthropic("refusal")).chat([{"role": "user", "content": "x"}])
    assert refused["refusal"] and json.loads(refused["text"])["final"]


def test_registry_builds_claude_only_with_a_key():
    from mxstudio.providers import ProviderError, build_text_provider
    config = {"kind": "anthropic", "model": "claude-opus-5-5", "enabled": True}
    with pytest.raises(ProviderError):
        build_text_provider(config, None)
    assert build_text_provider(config, "sk-test").model == "claude-opus-5-5"


def test_openai_compatible_sends_pictures_inside_their_own_message():
    import httpx

    from mxstudio.providers.base import OpenAICompatible
    sent = {}

    def handler(request):
        sent.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    provider = OpenAICompatible(base_url="http://gpu:8000", model="m", transport=httpx.MockTransport(handler))
    provider.chat([{"role": "user", "content": "look", "images": [_png()]}, {"role": "assistant", "content": "ok"},
                   {"role": "user", "content": "next"}])
    first = sent["messages"][0]["content"]
    assert first[0] == {"type": "text", "text": "look"} and first[1]["image_url"]["url"].startswith("data:image/png")
    assert sent["messages"][2]["content"] == "next"


# -- factory theme ------------------------------------------------------------------------------------
def test_theme_colours_are_applied_and_missing_fonts_are_named(fixture_registry):
    from mxstudio.factory.api import resolve_theme
    theme = resolve_theme({"colours": {"panel": "#FFEEDD"}}, registry=fixture_registry)
    assert theme["colours"]["panel"] == "#FFEEDD" and theme["fonts"]["title"] == "Tajawal"
    with pytest.raises(ToolError) as missing:
        resolve_theme({"type_theme": "classic_fun"}, registry=fixture_registry)  # Baloo/Lemonada not in fixtures
    assert missing.value.code == "FONTS_NOT_INSTALLED" and missing.value.details["missing"]
    with pytest.raises(ToolError):
        resolve_theme({"type_theme": "no_such_theme"}, registry=fixture_registry)


# -- MCP ----------------------------------------------------------------------------------------------------
def _mcp(tmp_path, lines: list) -> list[dict]:
    env = dict(os.environ, MXS_HOME=str(tmp_path / "home"), MXS_WORKSPACE=str(tmp_path / "المشروع" / "ws"),
               PYTHONPATH=str(ROOT), PYTHONUTF8="1")
    payload = "".join((json.dumps(m, ensure_ascii=False) if isinstance(m, dict) else m) + "\n" for m in lines)
    proc = subprocess.run([sys.executable, "-m", "mxstudio", "mcp"], input=payload.encode("utf-8"), env=env,
                          capture_output=True, timeout=120, cwd=str(ROOT))
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")[-2000:]
    return [json.loads(line) for line in proc.stdout.decode("utf-8").splitlines() if line.strip()]


def test_mcp_server_speaks_the_protocol_and_never_runs_irreversible_tools(tmp_path):
    picture = tmp_path / "تصميم.png"
    picture.write_bytes(_png())
    replies = _mcp(tmp_path, [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "studio_add_reference_image", "arguments": {"path": str(picture), "name": "design"}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
         "params": {"name": "workspace__approve",
                    "arguments": {"kind": "template_set", "key": "x", "version": 1, "approved_by": "me"}}},
        {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "studio_pending_approvals"}},
        {"jsonrpc": "2.0", "id": 6, "method": "tools/call",
         "params": {"name": "studio_manual", "arguments": {"query": "design_from_brief"}}},
        "this is not json",
        {"jsonrpc": "2.0", "id": 7, "method": "no/such"},
        {"jsonrpc": "2.0", "id": 8, "method": "ping"},
    ])
    by_id = {r.get("id"): r for r in replies}
    assert by_id[1]["result"]["protocolVersion"] == "2025-06-18" and "pending" in by_id[1]["result"]["instructions"]
    names = {t["name"] for t in by_id[2]["result"]["tools"]}
    assert {"factory__build", "factory__preview", "studio_view_preview", "studio_add_reference_image"} <= names
    assert all(t["inputSchema"]["type"] == "object" for t in by_id[2]["result"]["tools"])
    sha = json.loads(by_id[3]["result"]["content"][0]["text"])["sha"]
    assert len(sha) == 64
    assert by_id[4]["result"]["isError"] and "Queued for the operator" in by_id[4]["result"]["content"][-1]["text"]
    pending = json.loads(by_id[5]["result"]["content"][0]["text"])["pending"]
    assert pending[0]["tool"] == "workspace.approve" and pending[0]["actor"] == "agent:mcp"
    assert "factory.build" in by_id[6]["result"]["content"][0]["text"]
    assert by_id[None]["error"]["code"] == -32700 and by_id[7]["error"]["code"] == -32601 and by_id[8]["result"] == {}
    view = _mcp(tmp_path, [{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                            "params": {"name": "studio_view_reference", "arguments": {"sha": sha}}}])[0]
    assert view["result"]["content"][0]["type"] == "image" and view["result"]["content"][0]["mimeType"] == "image/jpeg"


def test_mcp_client_config_points_at_this_install():
    from mxstudio.mcp.server import client_config
    entry = client_config()["mcpServers"]["modulex-studio"]
    assert entry["command"] == sys.executable and entry["args"] == ["-m", "mxstudio", "mcp"]


# -- Claude Desktop connection ------------------------------------------------------------------------
def test_claude_desktop_config_is_merged_backed_up_and_never_broken(tmp_path):
    from mxstudio.mcp import clients
    from mxstudio.mcp.server import client_config
    entry = client_config()["mcpServers"]["modulex-studio"]
    path = tmp_path / "Claude" / "claude_desktop_config.json"
    path.parent.mkdir()
    original = {"mcpServers": {"filesystem": {"command": "npx", "args": ["x"]}}, "globalShortcut": "Ctrl+Space"}
    path.write_text(json.dumps(original), encoding="utf-8")
    before = clients.status(entry, [path])
    assert before["claude_desktop_found"] and not before["connected"] and before["other_servers"] == ["filesystem"]
    done = clients.install(entry, [path])
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["mcpServers"]["modulex-studio"] == entry
    assert data["mcpServers"]["filesystem"] == original["mcpServers"]["filesystem"]
    assert data["globalShortcut"] == "Ctrl+Space"
    assert json.loads(Path(done["backup"]).read_text(encoding="utf-8")) == original
    assert clients.status(entry, [path])["connected"] is True
    assert clients.remove([path])["removed"] and "modulex-studio" not in json.loads(path.read_text())["mcpServers"]
    path.write_text("{ broken", encoding="utf-8")
    with pytest.raises(clients.ConfigProblem):
        clients.install(entry, [path])
    assert path.read_text(encoding="utf-8") == "{ broken"  # untouched
    assert clients.status(entry, [path])["problem"]["ar"]


def test_claude_desktop_config_created_when_claude_desktop_has_its_folder(tmp_path):
    from mxstudio.mcp import clients
    missing = tmp_path / "nowhere" / "claude_desktop_config.json"
    folder = tmp_path / "Claude" / "claude_desktop_config.json"
    folder.parent.mkdir()
    assert clients.config_path([missing, folder]) == folder  # the folder Claude Desktop made wins
    clients.install({"command": "x", "args": ["mcp"]}, [missing, folder])
    assert json.loads(folder.read_text())["mcpServers"]["modulex-studio"]["args"] == ["mcp"]
    assert not missing.exists()


def test_self_test_starts_the_server_exactly_as_claude_desktop_will(tmp_path, monkeypatch):
    from mxstudio.mcp import clients
    from mxstudio.mcp.server import client_config
    monkeypatch.setenv("MXS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("MXS_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    result = clients.self_test(client_config()["mcpServers"]["modulex-studio"])
    assert result["ok"] and result["tools"] > 40 and result["server"]["name"] == "modulex-magazine-studio"
    broken = clients.self_test({"command": str(tmp_path / "no-such.exe"), "args": ["mcp"]})
    assert broken["ok"] is False and broken["ar"]


def test_connection_routes_need_the_studio_window(state, tmp_path, monkeypatch):
    from mxstudio.mcp import clients
    target = tmp_path / "Claude" / "claude_desktop_config.json"
    target.parent.mkdir()
    monkeypatch.setattr(clients, "config_candidates", lambda: [target])
    app, client, headers = _ui(state)
    assert client.get("/api/mcp/claude-desktop").json()["connected"] is False
    assert client.post("/api/mcp/claude-desktop/install", json={}).status_code == 403  # no CSRF: not the window
    assert not target.exists()
    assert client.post("/api/mcp/claude-desktop/install", json={}, headers=headers).json()["path"] == str(target)
    assert client.get("/api/mcp/claude-desktop").json()["connected"] is True
    assert client.post("/api/mcp/claude-desktop/remove", json={}, headers=headers).json()["removed"] is True
    names = {s["name"] for s in state.tools.specs()}
    assert not any("claude" in n or "desktop" in n for n in names)  # no agent tool can touch Claude Desktop
