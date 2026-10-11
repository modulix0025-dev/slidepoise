"""The operator's Windows rules, enforced statically over everything the Studio ships."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SHIPPED_PY = [p for p in (ROOT / "mxstudio").rglob("*.py") if "__pycache__" not in p.parts]
ALLOWED_SUBPROCESS = {ROOT / "mxstudio" / "proc.py"}


def test_children_only_through_proc():
    offenders = []
    for path in SHIPPED_PY:
        if path in ALLOWED_SUBPROCESS:
            continue
        text = path.read_text(encoding="utf-8")
        if re.search(r"\bsubprocess\.(run|Popen|call|check_call|check_output)\b|\bos\.system\(|\bos\.popen\(", text):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == [], f"use mxstudio.proc.run_hidden/spawn_hidden instead: {offenders}"


def test_no_pywebview_js_api_anywhere():
    for base in ("mxstudio", "installer"):
        for path in (ROOT / base).rglob("*"):
            if path.is_file() and path.suffix in {".py", ".js", ".nsi", ".spec", ".ps1"} and path.name != Path(__file__).name:
                text = path.read_text(encoding="utf-8", errors="replace")
                assert not re.search(r"js_api\s*=|js_api\s*:", text), path


def test_window_options_pin():
    from mxstudio.shell.launcher import window_options
    options = window_options("http://127.0.0.1:1234/")
    assert "js_api" not in options and options["url"].startswith("http://127.0.0.1:")


def test_batch_files_are_ascii_and_start_titles_quoted():
    for path in ROOT.rglob("*"):
        if path.suffix.lower() in {".bat", ".cmd"} and "node_modules" not in path.parts:
            data = path.read_bytes()
            assert all(b < 128 for b in data), f"{path} is not ASCII-only"
            for line in data.decode("ascii").splitlines():
                if re.match(r"\s*start\b", line, re.I):
                    assert re.match(r'\s*start\s+"[^"]*"', line, re.I), f"unquoted start title: {line}"


def test_child_processes_get_no_window_and_utf8(monkeypatch):
    import mxstudio.proc as proc
    monkeypatch.setattr(sys, "platform", "win32")
    assert proc.creation_flags() == 0x08000000
    env = proc.child_env({"MX_PPTX_SRC": r"C:\المشروع\قالب.pptx"})
    assert env["PYTHONUTF8"] == "1" and env["MX_PPTX_SRC"].endswith("قالب.pptx")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX spot-check of the same helper")
def test_run_hidden_passes_arabic_paths_through_env(tmp_path):
    import mxstudio.proc as proc
    target = tmp_path / "المشروع" / "ملف.txt"
    target.parent.mkdir()
    target.write_text("سلام", encoding="utf-8")
    code = "import os,pathlib;print(pathlib.Path(os.environ['MX_PATH']).read_text(encoding='utf-8'))"
    out = proc.run_hidden([sys.executable, "-c", code], env={"MX_PATH": str(target)})
    assert out.returncode == 0 and out.stdout.decode("utf-8").strip() == "سلام"
