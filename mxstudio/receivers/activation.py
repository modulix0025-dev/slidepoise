"""M1 activation through OM's own ``story_engine.add_story()`` / ``update_story()`` — never a direct registry write.

Rules:
* runs only after the operator's confirmation (checked by the caller/router);
* arguments are mapped **by parameter name** from the candidate onto the device's real
  signature (``inspect.signature``); a required parameter the candidate cannot fill blocks
  activation with a named list — nothing is guessed;
* template files are copied into the templates folder only if absent; an existing file with
  a different sha256 blocks (never overwritten);
* rollback = the previous registry entry (OM's own update path) + the files this call added,
  which are listed in the result so the Kit can remove them byte-identically.
"""
from __future__ import annotations

import hashlib
import inspect
import shutil
from pathlib import Path
from typing import Any


def flat_args(doc: dict, size: str) -> dict[str, Any]:
    size_doc = doc["variants"][size]
    out: dict[str, Any] = {"display_name": doc["display_name"], "size": size, "story_key": doc["story_key"]}
    for lang in ("ar", "en"):
        for gender in ("male", "female"):
            v = (size_doc.get(lang) or {}).get(gender)
            if v:
                out[f"{lang}_{gender}_file"] = v["file"]
                out[f"{lang}_{gender}_base"] = v["base_name"]
    for key in ("characters_count", "extra_characters", "figure_prompt_male", "figure_prompt_female",
                "logo_config", "replacements_additions"):
        if key in doc:
            out[key] = doc[key]
    if "replacements_additions" in doc:
        out.setdefault("replacements", doc["replacements_additions"])
    return out


def plan_call(fn, available: dict[str, Any]) -> dict[str, Any]:
    sig = inspect.signature(fn)
    kwargs, missing, unused = {}, [], set(available)
    for name, param in sig.parameters.items():
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            continue
        if name in available:
            kwargs[name] = available[name]
            unused.discard(name)
        elif param.default is inspect.Parameter.empty:
            missing.append(name)
    return {"function": fn.__name__, "kwargs": kwargs, "missing": missing, "not_accepted": sorted(unused)}


def activate_template_set(doc: dict, candidate_dir: Path, *, story_engine: Any, templates_dir: Path) -> dict:
    mode = doc.get("mode", "add")
    fn = getattr(story_engine, "update_story" if mode == "update" else "add_story", None)
    if fn is None:
        return {"ok": False, "status": "blocked", "reason": f"story_engine has no {mode}_story()"}
    sizes = sorted(doc["variants"])
    takes_size = "size" in inspect.signature(fn).parameters
    if len(sizes) > 1 and not takes_size:
        return {"ok": False, "status": "blocked",
                "reason": "candidate has several sizes but the device's function takes no `size` — "
                          "mapping pending on-device review"}
    plans = [plan_call(fn, flat_args(doc, size)) for size in sizes]
    missing = sorted({m for p in plans for m in p["missing"]})
    if missing:
        return {"ok": False, "status": "blocked", "reason": "required parameters not in the candidate",
                "missing": missing, "plans": plans}
    files_dir = Path(candidate_dir) / "files"
    added: list[str] = []
    templates_dir = Path(templates_dir)
    for src in sorted(files_dir.iterdir()) if files_dir.is_dir() else []:
        dst = templates_dir / src.name
        if dst.exists():
            if hashlib.sha256(dst.read_bytes()).hexdigest() != hashlib.sha256(src.read_bytes()).hexdigest():
                for name in added:
                    (templates_dir / name).unlink(missing_ok=True)
                return {"ok": False, "status": "blocked",
                        "reason": f"{src.name} already exists in the templates folder with different bytes"}
            continue
        shutil.copyfile(src, dst)
        added.append(src.name)
    results = []
    try:
        for plan in plans:
            results.append(repr(fn(**plan["kwargs"]))[:200])
    except Exception as exc:  # noqa: BLE001 - report OM's own refusal by name
        for name in added:
            (templates_dir / name).unlink(missing_ok=True)
        return {"ok": False, "status": "refused_by_om", "reason": f"{exc.__class__.__name__}: {exc}",
                "plans": plans}
    return {"ok": True, "status": "activated", "function": fn.__name__, "calls": len(plans),
            "added_template_files": added, "om_results": results}
