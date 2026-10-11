"""First-run wizard: workspace → providers → discovery → doctor, persisted in settings."""
from __future__ import annotations

import json

import pytest

from mxstudio.config import Settings
from mxstudio.firstrun.wizard import STEPS, Wizard, WizardError, fingerprint


class FakeStore:
    def __init__(self):
        self.secrets = {}

    def put(self, name, secret):
        self.secrets[name] = secret
        return fingerprint(secret)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("MXS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("MXS_PROJECT_ROOT", str(tmp_path / "المشروع"))
    monkeypatch.delenv("MXS_WORKSPACE", raising=False)
    return tmp_path


def _wizard(env, **kw):
    kw.setdefault("discover", lambda: {"available": True, "result": {"systems": ["OM", "Console", "Store"]}})
    kw.setdefault("doctor", lambda: [{"id": "python", "ok": True, "level": "ok"},
                                     {"id": "office", "ok": False, "level": "red"}])
    kw.setdefault("program_dir", env / "Programs" / "ModuleX Magazine Studio")
    return Wizard(Settings(env / "home" / "settings.json"), **kw)


def test_steps_order_and_default_arabic_workspace(env):
    w = _wizard(env)
    state = w.state()
    assert state["steps"] == list(STEPS) == ["workspace", "providers", "discovery", "doctor"]
    assert state["step"] == "workspace" and w.needed()
    assert state["workspace_default"].endswith("المشروع/ModuleX_MagazineStudio_Data") or \
        state["workspace_default"].endswith("المشروع\\ModuleX_MagazineStudio_Data")
    state = w.submit("workspace", {})
    ws = env / "المشروع" / "ModuleX_MagazineStudio_Data"
    assert state["step"] == "providers" and (ws / "stories").is_dir()
    assert Settings(env / "home" / "settings.json").workspace() == ws


def test_full_run_persists_across_restarts(env):
    store = FakeStore()
    _wizard(env, secret_store=store).submit("workspace", {"path": str(env / "مساحة عمل")})
    # app restarted: a fresh Wizard resumes at the next step
    w = _wizard(env, secret_store=store)
    assert w.state()["step"] == "providers"
    w.submit("providers", {"text_vision": {"base_url": "http://gpu:8000/v1", "enabled": True, "api_key": "sk-secret-123"}})
    w.submit("discovery")
    state = w.submit("doctor")
    assert state["done"] and state["step"] == "done" and not w.needed()
    assert state["doctor"]["red"] == ["office"]  # red lines are recorded, not hidden
    assert state["discovery"]["available"] is True
    assert state["providers"]["key_fingerprints"] == {"text_vision": fingerprint("sk-secret-123")}
    raw = (env / "home" / "settings.json").read_text(encoding="utf-8")
    assert "sk-secret-123" not in raw  # the key went to the store only
    assert store.secrets == {"provider:text_vision": "sk-secret-123"}
    assert json.loads(raw)["providers"]["text_vision"]["base_url"] == "http://gpu:8000/v1"


def test_key_without_secret_store_is_refused_not_written(env):
    w = _wizard(env)
    w.submit("workspace", {"path": str(env / "ws")})
    with pytest.raises(WizardError) as info:
        w.submit("providers", {"image": {"api_key": "plain-key"}})
    assert info.value.code == "no_secret_store"
    assert "plain-key" not in (env / "home" / "settings.json").read_text(encoding="utf-8")


@pytest.mark.parametrize("path,code", [
    ("relative/path", "workspace_relative"),
    ("", "workspace_empty"),
])
def test_workspace_validation_negative_controls(env, path, code):
    w = _wizard(env)
    with pytest.raises(WizardError) as info:
        w.validate_workspace(path)
    assert info.value.code == code and info.value.ar


def test_workspace_inside_program_dir_is_refused(env):
    w = _wizard(env)
    with pytest.raises(WizardError) as info:
        w.submit("workspace", {"path": str(env / "Programs" / "ModuleX Magazine Studio" / "data")})
    assert info.value.code == "workspace_in_program"
    assert w.state()["step"] == "workspace"


def test_order_skip_back_reset(env):
    w = _wizard(env)
    with pytest.raises(WizardError):
        w.submit("doctor")  # out of order
    with pytest.raises(WizardError):
        w.skip("workspace")  # mandatory
    w.submit("workspace", {"path": str(env / "ws")})
    assert w.skip("providers")["step"] == "discovery"
    assert w.skip("discovery")["skipped"] == ["providers", "discovery"]
    with pytest.raises(WizardError):
        w.skip("doctor")
    back = w.back()
    assert back["step"] == "discovery" and back["skipped"] == ["providers"]
    reset = w.reset()
    assert reset["step"] == "workspace" and reset["completed"] == [] and not reset["done"]


def test_discovery_without_kit_is_honest_and_skippable(env):
    w = Wizard(Settings(env / "home" / "settings.json"), program_dir=env / "p",
               doctor=list)
    w.submit("workspace", {"path": str(env / "ws")})
    w.skip("providers")
    state = w.submit("discovery")
    assert state["step"] == "doctor"
    assert "available" in state["discovery"]


def test_cli_workspace_from_env(env, monkeypatch, capsys):
    from mxstudio.firstrun import main
    monkeypatch.setenv("MXS_FIRSTRUN_WORKSPACE", str(env / "من البيئة"))
    assert main(["workspace"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["step"] == "providers" and out["workspace"].endswith("من البيئة")
    assert main(["skip", "workspace"]) == 1
    assert "not_skippable" in capsys.readouterr().out
