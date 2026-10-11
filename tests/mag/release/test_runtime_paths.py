"""Renderer, Node and post-processor resolution in a source checkout and in the frozen app layout."""
from __future__ import annotations

import sys
from pathlib import Path

from mxstudio import runtime_paths


def test_source_checkout_paths():
    assert runtime_paths.renderer_script().is_file()
    assert runtime_paths.python_for_scripts() == sys.executable
    assert runtime_paths.renderer_env()["PYTHON"] == sys.executable


def test_frozen_layout_uses_bundled_node_modules_and_cli(tmp_path, monkeypatch):
    app = tmp_path / "ModuleX Magazine Studio"
    (app / "node" / "node_modules").mkdir(parents=True)
    (app / "node" / "node").write_text("")
    (app / "node" / "node.exe").write_text("")
    (app / "mxstudio-cli").write_text("")
    (app / "mxstudio-cli.exe").write_text("")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(app / "ModuleX Magazine Studio.exe"))
    monkeypatch.delenv("MXS_NODE", raising=False)
    monkeypatch.delenv("MXS_NODE_MODULES", raising=False)
    assert Path(runtime_paths.node_executable()).parent == app / "node"
    assert Path(runtime_paths.python_for_scripts()).name.startswith("mxstudio-cli")
    assert runtime_paths.renderer_env()["NODE_PATH"] == str(app / "node" / "node_modules")


def test_cli_runs_only_scripts_of_the_packaged_skill(tmp_path, capsys):
    outside = tmp_path / "evil.py"
    outside.write_text("raise SystemExit(7)")
    assert runtime_paths.run_packaged_script([str(outside)]) is None  # not ours: normal dispatch refuses it
    assert runtime_paths.run_packaged_script(["doctor"]) is None
    script = runtime_paths.skill_dir() / "runtime" / "scripts" / "postprocess_pptx.py"
    assert runtime_paths.run_packaged_script([str(script), "--help"]) == 0
    assert "metadata" in capsys.readouterr().out
