"""Where the renderer, Node and a Python for the post-processor live — source checkout or installed app.

Source checkout: `<repo>/slidepoise/runtime/js/scene_to_pptx.mjs`, `node` on PATH, this Python.
Installed (PyInstaller one-folder, installer/pyinstaller/MagazineStudio.spec):
  <app>/_internal/skill/slidepoise/runtime/js/scene_to_pptx.mjs
  <app>/node/node.exe and <app>/node/node_modules (pptxgenjs is loaded with createRequire, so NODE_PATH works)
  the post-processor runs through `mxstudio-cli.exe <script.py> …` (see `run_packaged_script`).
Overrides: MXS_NODE, MXS_NODE_MODULES.
"""
from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    return Path(sys.executable).resolve().parent if frozen() else REPO


def skill_dir() -> Path:
    candidates = (REPO / "slidepoise", REPO / "skill" / "slidepoise", app_dir() / "_internal" / "skill" / "slidepoise")
    for candidate in candidates:
        if (candidate / "runtime" / "js" / "scene_to_pptx.mjs").is_file():
            return candidate
    return REPO / "slidepoise"


def renderer_script() -> Path:
    return skill_dir() / "runtime" / "js" / "scene_to_pptx.mjs"


def node_executable() -> str:
    if os.environ.get("MXS_NODE"):
        return os.environ["MXS_NODE"]
    bundled = app_dir() / "node" / ("node.exe" if os.name == "nt" else "node")
    return str(bundled) if bundled.is_file() else "node"


def python_for_scripts() -> str:
    """An interpreter that can run the skill's .py scripts: this Python, or the CLI exe when frozen."""
    if not frozen():
        return sys.executable
    cli = app_dir() / ("mxstudio-cli.exe" if os.name == "nt" else "mxstudio-cli")
    return str(cli if cli.is_file() else sys.executable)


def renderer_env() -> dict[str, str]:
    env = {"PYTHON": python_for_scripts()}
    modules = os.environ.get("MXS_NODE_MODULES") or str(app_dir() / "node" / "node_modules")
    if Path(modules).is_dir():
        env["NODE_PATH"] = modules
    return env


def run_packaged_script(argv: list[str]) -> int | None:
    """`mxstudio-cli.exe <script.py> args…` runs a script of the packaged skill (and nothing else).

    Returns None when argv[0] is not such a script, so the normal command dispatch continues.
    """
    if not argv or not argv[0].endswith(".py"):
        return None
    script = Path(argv[0]).resolve()
    root = skill_dir().resolve()
    if root not in script.parents or not script.is_file():
        return None
    saved = sys.argv
    sys.argv = [str(script), *argv[1:]]
    try:
        runpy.run_path(str(script), run_name="__main__")
    except SystemExit as exc:
        return int(exc.code or 0) if not isinstance(exc.code, str) else 1
    finally:
        sys.argv = saved
    return 0
