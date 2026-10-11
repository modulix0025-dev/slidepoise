"""The Kit as Studio tools: applying or reverting a patch needs a human token AND the plan's confirm code."""
from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from mxstudio.agent.tools import ToolRegistry
from mxstudio.kit import api, jobs
from mxstudio.worker import JobQueue


def _state(tmp_path):
    return SimpleNamespace(tools=ToolRegistry(tmp_path / "tools.sqlite3"), queue=JobQueue(tmp_path / "q.sqlite3"))


def test_kit_tools_gate_irreversible_steps_on_a_human_token(replica, tmp_path, monkeypatch):
    facts = replica()
    root = str(facts["root"])
    monkeypatch.setenv("MXS_PROJECT_ROOT", root)
    monkeypatch.setattr("mxstudio.kit.apply.default_test_runner", lambda _r: {"ran": False, "reason": "test"})
    state = _state(tmp_path)
    app = FastAPI()
    api.register(app, state)
    specs = {s["name"]: s for s in state.tools.specs()}
    assert specs["kit.apply"]["irreversible"] and specs["kit.revert"]["irreversible"]
    assert not specs["kit.plan"]["irreversible"]
    plan = state.tools.call("kit.plan", {"root": root, "patch": "P-PREFLIGHT2"}, actor="agent")
    code = plan["result"]["patches"][0]["confirm_code"]
    args = {"root": root, "patch": "P-PREFLIGHT2", "confirm_code": code}
    refused = state.tools.call("kit.apply", args, actor="agent")
    assert refused["ok"] is False and refused["code"] == "CONFIRMATION_REQUIRED"
    token = state.tools.tokens.mint("kit.apply", args, "ui:operator")
    done = state.tools.call("kit.apply", args, actor="ui:operator", confirmation_token=token)
    assert done["ok"] and done["result"]["result"] == "applied"
    again = state.tools.call("kit.apply", args, actor="ui:operator", confirmation_token=token)
    assert again["code"] == "TOKEN_USED"
    summary = TestClient(app).get("/api/kit/summary").json()
    assert {r["id"]: r["status"] for r in summary["facts"]["patches"]}["P-PREFLIGHT2"] == "applied"
    rev_args = {"root": root, "patch": "P-PREFLIGHT2"}
    token = state.tools.tokens.mint("kit.revert", rev_args, "ui:operator")
    assert state.tools.call("kit.revert", rev_args, actor="ui:operator",
                            confirmation_token=token)["result"]["byte_identical"] is True


def test_long_steps_are_queued_for_the_worker(tmp_path, kit_home):
    state = _state(tmp_path)
    api.register(FastAPI(), state)
    res = state.tools.call("kit.report", {"root": str(tmp_path / "nowhere")}, actor="agent")
    assert res["ok"] and res["result"]["job"]["kind"] == "kit.report"
    assert set(jobs.HANDLERS) == {"kit.proofs", "kit.report"}
