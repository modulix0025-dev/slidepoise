"""Where the Studio keeps things.

* program: ``%LOCALAPPDATA%\\Programs\\ModuleX Magazine Studio`` (installed by NSIS, outside
  ``C:\\المشروع`` so an agent with project access cannot modify the program);
* app state (settings, secrets, queue, audit): ``%LOCALAPPDATA%\\ModuleX\\MagazineStudio``;
* workspace (stories, art, templates, packs): ``C:\\المشروع\\ModuleX_MagazineStudio_Data``
  by default, changeable in Settings.

Every location can be overridden with an environment variable, which is how tests and
the cloud run the same code.
"""
from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path
from typing import Any

APP_NAME = "ModuleX Magazine Studio"
APP_VERSION = "0.2.0"
PROJECT_ROOT_DEFAULT = Path("C:/المشروع") if sys.platform == "win32" else Path.home() / "modulex-project"


def app_home() -> Path:
    env = os.environ.get("MXS_HOME")
    if env:
        return Path(env)
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ModuleX" / "MagazineStudio"
    return Path.home() / ".local" / "share" / "modulex-magazine-studio"


def project_root() -> Path:
    return Path(os.environ.get("MXS_PROJECT_ROOT") or PROJECT_ROOT_DEFAULT)


def default_workspace() -> Path:
    return Path(os.environ.get("MXS_WORKSPACE") or project_root() / "ModuleX_MagazineStudio_Data")


DEFAULT_SETTINGS: dict[str, Any] = {
    "ui_language": "ar",
    "theme": "day",
    "workspace": None,  # None -> default_workspace()
    "project_root": None,
    "digits": "arabic_indic",
    "page": {"bleed_mm": 3.0, "safe_mm": 5.0, "dpi": 300},
    "providers": {
        # D13: free, open-weight defaults. Paid APIs are possible but off until the operator adds them.
        "text_vision": {"kind": "openai_compatible", "base_url": "", "model": "Qwen/Qwen3-VL-8B-Instruct",
                        "enabled": False},
        "image": {"kind": "comfyui", "base_url": "", "workflow": "qwen_image", "enabled": False},
    },
    "budget": {"per_job_usd": 2.0, "per_day_usd": 10.0},
    "agent": {"mode": "suggest_only"},  # becomes "full" only after model qualification passes
    "discovery": {"openverse": True, "wikimedia": True, "iconify": True},
}


class Settings:
    """JSON settings file with defaults; thread-safe; unknown keys are kept."""

    def __init__(self, path: Path | None = None):
        self.path = path or app_home() / "settings.json"
        self._lock = threading.Lock()

    def load(self) -> dict[str, Any]:
        with self._lock:
            data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.is_file() else {}
        return _merge(DEFAULT_SETTINGS, data)

    def update(self, patch: dict[str, Any]) -> dict[str, Any]:
        current = self.load()
        merged = _merge(current, patch)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)
        return merged

    def workspace(self) -> Path:
        configured = self.load().get("workspace")
        return Path(configured) if configured else default_workspace()


def _merge(base: dict, patch: dict) -> dict:
    out = dict(base)
    for key, value in (patch or {}).items():
        out[key] = _merge(out[key], value) if isinstance(value, dict) and isinstance(out.get(key), dict) else value
    return out
