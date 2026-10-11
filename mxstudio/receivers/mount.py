"""Device-side mount helper, called from the P-RECEIVERS hook only when MODULEX_MAG_RECEIVERS=1.

Reads ``mag_config.json`` written beside this package by the Kit at apply time:
``{"system", "kinds", "system_root_up", "signing_module", "store_dir", "story_engine_module",
"templates_dir"}`` — every path relative to the system root. The signing module is the system's
own ``modulex_signing.py`` (sha-verified by the Kit's anchor); the secret is resolved by that
module's own ``resolve_secret_from_env()``.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
from pathlib import Path
from typing import Any

from .activation import activate_template_set
from .routers import build_router
from .signing_gate import SignedRequestGate
from .store import CandidateStore

HERE = Path(__file__).resolve().parent


def load_config(package_dir: Path = HERE) -> dict[str, Any]:
    return json.loads((package_dir / "mag_config.json").read_text(encoding="utf-8"))


def system_root(cfg: dict, package_dir: Path = HERE) -> Path:
    root = package_dir
    for _ in range(int(cfg.get("system_root_up", 2))):
        root = root.parent
    return root


def load_signing(cfg: dict, root: Path):
    path = root / cfg["signing_module"]
    spec = importlib.util.spec_from_file_location("_mx_mag_modulex_signing", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build(cfg: dict, root: Path, *, signing=None, secret_resolver=None, guard=None, now=None,
          story_engine=None):
    signing = signing or load_signing(cfg, root)
    gate = SignedRequestGate(signing, secret_resolver, guard=guard, now=now)
    store = CandidateStore(root / cfg.get("store_dir", "mag_candidates"))
    activator = None
    if "m1" in cfg["kinds"] and cfg.get("story_engine_module"):
        def activator(doc: dict, cdir: Path) -> dict:
            engine = story_engine or importlib.import_module(cfg["story_engine_module"])
            return activate_template_set(doc, cdir, story_engine=engine,
                                         templates_dir=root / cfg.get("templates_dir", "story_templates"))
    return build_router(kinds=tuple(cfg["kinds"]), gate=gate, store=store, activator=activator,
                        system=cfg.get("system", ""))


def mount(app, *, package_dir: Path = HERE) -> None:
    cfg = load_config(package_dir)
    app.include_router(build(cfg, system_root(cfg, package_dir)))
