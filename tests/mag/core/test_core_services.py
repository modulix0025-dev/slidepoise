"""Phase 2 core services: workspace, queue, budget, secrets, providers, agent tools."""
from __future__ import annotations

import json

import httpx
import pytest

from mxstudio.agent.tools import Tool, ToolRegistry
from mxstudio.budget import BudgetExceeded, BudgetGuard, Prices
from mxstudio.providers import ProviderError, build_image_provider, build_text_provider, model_licence_findings
from mxstudio.providers.base import ComfyUIRemote, OpenAICompatible
from mxstudio.secrets import SecretStore, fingerprint
from mxstudio.worker import JobQueue, Worker
from mxstudio.workspace import ImmutableError, Workspace


class Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


# -- workspace ---------------------------------------------------------------
def test_workspace_versions_are_immutable_once_approved(tmp_path):
    ws = Workspace(tmp_path / "مساحة العمل")
    sha = ws.put_bytes(b"deck bytes")
    assert ws.verify_blob(sha) and ws.put_bytes(b"deck bytes") == sha
    v1 = ws.save("template_set", "golden_fish", {"title": "السمكة"}, {"deck": sha})
    v2 = ws.save("template_set", "golden_fish", {"title": "السمكة الذهبية"}, {"deck": sha})
    assert (v1, v2) == (1, 2)
    ws.approve("template_set", "golden_fish", 1, "ModuleX operator")
    with pytest.raises(ImmutableError):
        ws.approve("template_set", "golden_fish", 1, "again")
    with pytest.raises(ValueError):
        ws.approve("template_set", "golden_fish", 2, "")
    assert ws.latest_approved("template_set", "golden_fish")["version"] == 1
    assert ws.diff("template_set", "golden_fish", 1, 2)["body"] == {"title": {"from": "السمكة", "to": "السمكة الذهبية"}}
    v3 = ws.restore("template_set", "golden_fish", 1)
    assert ws.get("template_set", "golden_fish")["body"]["title"] == "السمكة" and v3 == 3
    assert ws.get("template_set", "golden_fish", 1)["approved"] is True
    with pytest.raises(FileNotFoundError):
        ws.save("template_set", "x", {}, {"deck": "0" * 64})


def test_blob_tampering_is_detected(tmp_path):
    ws = Workspace(tmp_path)
    sha = ws.put_bytes(b"original")
    ws.blob_path(sha).write_bytes(b"tampered")
    assert not ws.verify_blob(sha)
    with pytest.raises(ValueError):
        ws.blob_path("../../etc/passwd")


# -- queue -------------------------------------------------------------------
def test_queue_leases_expire_and_jobs_survive_a_crash(tmp_path):
    clock = Clock()
    queue = JobQueue(tmp_path / "q.sqlite3", clock=clock)
    job = queue.enqueue("render", {"slide": 1}, idempotency_key="render-1", max_attempts=2)
    assert queue.enqueue("render", {"slide": 1}, idempotency_key="render-1")["id"] == job["id"]
    leased = queue.lease("w1", lease_seconds=30)
    assert leased["id"] == job["id"] and leased["attempts"] == 1
    assert queue.lease("w2") is None
    clock.now += 31  # w1 "crashed"
    again = queue.lease("w2", lease_seconds=30)
    assert again["id"] == job["id"] and again["attempts"] == 2
    assert not queue.complete(job["id"], "w1", {})  # stale owner cannot finish
    clock.now += 31
    assert queue.lease("w3") is None
    assert queue.get(job["id"])["state"] == "failed"


def test_worker_records_handler_failures_and_retries(tmp_path):
    queue = JobQueue(tmp_path / "q.sqlite3")
    calls = {"n": 0}

    def flaky(payload):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient")
        return {"ok": payload["x"] * 2}

    job = queue.enqueue("flaky", {"x": 21}, max_attempts=3)
    worker = Worker(queue, {"flaky": flaky})
    assert worker.run_once()["state"] == "queued"
    done = worker.run_once()
    assert done["state"] == "done" and done["result"] == {"ok": 42} and done["id"] == job["id"]


# -- budget ------------------------------------------------------------------
def test_budget_refuses_past_ceilings(tmp_path):
    clock = Clock()
    guard = BudgetGuard(tmp_path / "b.sqlite3", per_job_usd=1.0, per_day_usd=1.5, clock=clock)
    price = Prices(per_image=0.4)
    estimate = guard.estimate(price, images=2)
    assert estimate == 0.8
    guard.check("job-a", estimate)
    guard.record("job-a", "comfyui", 0.8)
    with pytest.raises(BudgetExceeded) as exc:
        guard.check("job-a", 0.4)
    assert "الحد المسموح" in exc.value.message_ar
    guard.record("job-b", "comfyui", 0.6)
    with pytest.raises(BudgetExceeded):
        guard.check("job-c", 0.2)
    clock.now += 86401
    assert guard.check("job-c", 0.2)["day_spent_usd"] == 0
    assert guard.estimate(Prices(), input_tokens=10_000) == 0  # self-hosted default costs nothing


# -- secrets -----------------------------------------------------------------
def test_secrets_are_write_only(tmp_path):
    store = SecretStore(tmp_path / "secrets.json")
    shown = store.set("provider.text_vision", "sk-very-secret-value")
    assert shown == {"name": "provider.text_vision", "set": True, "fingerprint": fingerprint("sk-very-secret-value"),
                     "backend": store.backend}
    assert "sk-very-secret-value" not in json.dumps(store.list())
    assert store.get("provider.text_vision") == "sk-very-secret-value"
    raw = (tmp_path / "secrets.json").read_text()
    assert "sk-very-secret-value" not in raw  # sealed (base64 here, DPAPI on Windows)
    assert store.delete("provider.text_vision") and store.get("provider.text_vision") is None


# -- providers ---------------------------------------------------------------
def test_openai_compatible_chat_and_vision_payload():
    seen = {}

    def handler(request: httpx.Request):
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "Qwen/Qwen3-VL-8B-Instruct"}]})
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"choices": [{"message": {"content": "تمام"}}], "usage": {"total_tokens": 5}})

    provider = OpenAICompatible("http://gpu:8000", "Qwen/Qwen3-VL-8B-Instruct", api_key="k",
                                transport=httpx.MockTransport(handler))
    out = provider.chat([{"role": "user", "content": "بص على الصفحة"}], images=[b"\x89PNG"])
    assert out["text"] == "تمام" and seen["auth"] == "Bearer k"
    parts = seen["body"]["messages"][-1]["content"]
    assert parts[0]["type"] == "text" and parts[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert provider.test_connection()["model_listed"] is True


def test_comfyui_fills_placeholders_and_fetches_images():
    workflow = {"3": {"inputs": {"text": "__PROMPT__", "width": "__WIDTH__", "height": "__HEIGHT__",
                                 "seed": "__SEED__", "ckpt_name": "qwen_image_fp8.safetensors"}}}
    calls = []

    def handler(request: httpx.Request):
        calls.append(request.url.path)
        if request.url.path == "/prompt":
            graph = json.loads(request.content)["prompt"]
            assert graph["3"]["inputs"] == {"text": "بحر \"أزرق\"", "width": 1819, "height": 2551, "seed": 7,
                                            "ckpt_name": "qwen_image_fp8.safetensors"}
            return httpx.Response(200, json={"prompt_id": "p1"})
        if request.url.path == "/history/p1":
            return httpx.Response(200, json={"p1": {"outputs": {"9": {"images": [{"filename": "a.png"}]}}}})
        return httpx.Response(200, content=b"PNGDATA")

    provider = ComfyUIRemote("http://gpu:8188", workflow, transport=httpx.MockTransport(handler), sleep=lambda s: None)
    assert provider.generate('بحر "أزرق"', width=1819, height=2551, seed=7) == [b"PNGDATA"]
    assert calls == ["/prompt", "/history/p1", "/view"]


def test_non_commercial_weights_are_refused():
    banned = {"1": {"inputs": {"unet_name": "flux1-kontext-dev-fp8.safetensors"}}}
    assert model_licence_findings(banned)[0]["finding"] == "model_licence_not_allowed"
    assert model_licence_findings({"1": {"inputs": {"unet_name": "qwen_image_edit_2511.safetensors"}}}) == []
    with pytest.raises(ProviderError):
        build_image_provider({"kind": "comfyui", "enabled": True, "base_url": "http://x", "workflow_graph": banned})
    with pytest.raises(ProviderError):
        build_text_provider({"kind": "openai_compatible", "enabled": False})


# -- agent tools ---------------------------------------------------------------
def _registry(tmp_path, clock=None):
    registry = ToolRegistry(tmp_path / "agent.sqlite3", clock=clock or Clock())
    registry.register(Tool("echo", "رد", "echo", {"type": "object", "properties": {"x": {"type": "integer"}},
                                                    "required": ["x"], "additionalProperties": False},
                           lambda a: {"x": a["x"]}))
    registry.register(Tool("publish", "نشر", "publish", {"type": "object", "properties": {"story": {"type": "string"}},
                                                          "required": ["story"]},
                           lambda a: {"published": a["story"]}, irreversible=True))
    return registry


def test_schema_validation_and_audit(tmp_path):
    registry = _registry(tmp_path)
    assert registry.call("echo", {"x": 3}, actor="agent")["result"] == {"x": 3}
    bad = registry.call("echo", {"x": "three", "extra": 1}, actor="agent")
    assert bad["code"] == "INVALID_ARGUMENTS"
    assert registry.call("nope", {}, actor="agent")["code"] == "UNKNOWN_TOOL"
    outcomes = [e["outcome"] for e in registry.audit.entries()]
    assert outcomes == ["refused", "refused", "ok"]


def test_irreversible_tools_need_a_fresh_human_token(tmp_path):
    clock = Clock()
    registry = _registry(tmp_path, clock)
    args = {"story": "golden_fish"}
    assert registry.call("publish", args, actor="agent")["code"] == "CONFIRMATION_REQUIRED"
    with pytest.raises(Exception):
        registry.tokens.mint("publish", args, human="agent")  # the agent cannot mint
    token = registry.tokens.mint("publish", args, human="ui:abcd")
    assert registry.call("publish", {"story": "other"}, actor="agent", confirmation_token=token)["code"] == "TOKEN_MISMATCH"
    assert registry.call("publish", args, actor="agent", confirmation_token=token)["ok"] is True
    assert registry.call("publish", args, actor="agent", confirmation_token=token)["code"] == "TOKEN_USED"
    late = registry.tokens.mint("publish", args, human="ui:abcd")
    clock.now += 601
    assert registry.call("publish", args, actor="agent", confirmation_token=late)["code"] == "TOKEN_EXPIRED"
    assert registry.call("publish", args, actor="agent", confirmation_token="forged")["code"] == "TOKEN_INVALID"


def test_audit_redacts_secrets(tmp_path):
    registry = _registry(tmp_path)
    registry.register(Tool("set_key", "مفتاح", "key", {"type": "object"}, lambda a: {"ok": True}))
    registry.call("set_key", {"api_key": "sk-123", "name": "x"}, actor="ui:1")
    assert "sk-123" not in json.dumps(registry.audit.entries())
