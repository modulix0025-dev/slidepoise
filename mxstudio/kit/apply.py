"""Plan, apply, revert and report status of Kit patches on the operator's trees.

Rules enforced (brief §6.11):
* a patch applies only when every anchor it depends on verified (``ok``; a contract file the
  operator updated is accepted only when its behaviour comparison says "same_*");
* only with the per-patch confirmation code shown by ``plan`` (non-interactive CLI: ``--confirm``);
* frozen files are never touched: refused by path at plan time and hashed before/after every write;
* every modified file is backed up in ``<system>\\_backup_mag_<patch>_<date>\\`` (never in ``static``);
  a manifest records sha256 before/after; ``revert`` restores byte-identical originals and refuses
  when a file drifted; patches sharing a file revert in LIFO order (``--cascade`` does it for you);
* idempotent: applying an applied patch is a no-op; markers without a Kit record block the patch;
* the target system's own ``RUN_TESTS.bat`` runs before/after when present; a new failure rolls back.
"""
from __future__ import annotations

import difflib
import json
import os
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

from ._util import (
    FROZEN_NAMES,
    FROZEN_RELPATHS,
    inside_static,
    is_frozen,
    kit_home,
    log_event,
    now_iso,
    read_json,
    sha256_bytes,
    sha256_file,
    today_stamp,
    walk_files,
    write_json,
)
from .anchors import by_id, verify
from .discover import SYSTEM_BY_KEY, discover, system_dir
from .patches import PATCHES, UNWIRED_FLAGS
from .patches.base import Patch, PatchError, has_markers, insert_hook, payload_files, remove_hook

TestRunner = Callable[[Path], dict]


# ---------------------------------------------------------------- state ----

def _state_path() -> Path:
    return kit_home() / "state.json"


def load_state() -> dict:
    return read_json(_state_path(), None) or {"version": 1, "roots": {}}


def save_state(state: dict) -> None:
    write_json(_state_path(), state)


def _root_state(state: dict, root: Path) -> dict:
    return state["roots"].setdefault(str(Path(root).resolve()), {"seq": 0, "patches": {}})


# ---------------------------------------------------------------- context ----

def build_context(root: Path | str | None = None, overrides: dict | None = None) -> dict:
    found = discover(root)
    verified = verify(found, overrides=overrides)
    return {"root": Path(found["root"]), "found": found, "verified": verified, "anchors": by_id(verified),
            "overrides": overrides or {}}


def _sysdir(ctx: dict, system: str) -> Path:
    d = system_dir(ctx["found"], system)
    if d is None:
        raise PatchError(f"system {system} not found under {ctx['root']}")
    return d


def anchor_gate(patch: Patch, ctx: dict) -> tuple[list[dict], list[dict]]:
    blockers, warnings = [], []
    for aid in patch.anchors:
        a = ctx["anchors"].get(aid) or {"id": aid, "status": "unknown"}
        if a["status"] == "ok":
            continue
        behaviour = (a.get("extra") or {}).get("behaviour")
        rows = behaviour if isinstance(behaviour, list) else [behaviour] if behaviour else []
        if a["status"] == "operator_updated" and rows and all(str(r.get("verdict", "")).startswith("same_")
                                                               for r in rows):
            warnings.append({"anchor": aid, "status": a["status"], "note": "operator updated it; behaviour identical"})
            continue
        blockers.append({"anchor": aid, "status": a["status"], "file": a.get("file"),
                         "expected": a.get("expected"), "found": a.get("found"), "diff": a.get("diff")})
    return blockers, warnings


def _hook_target(hook, ctx: dict) -> tuple[str, dict]:
    if hook.file == "@app_object":
        a = ctx["anchors"].get(f"{hook.system}.app_object") or {}
        if a.get("status") != "ok":
            raise PatchError(f"{hook.system}: FastAPI app module not anchored")
        return a["file"], {"app_var": a["extra"]["var"]}
    return hook.file, {}


def compute_changes(patch: Patch, ctx: dict) -> list[dict]:
    """Every file the patch would write, with before/after bytes. Raises :class:`PatchError`."""
    changes: dict[tuple[str, str], dict] = {}
    for hook in patch.hooks:
        sdir = _sysdir(ctx, hook.system)
        rel, hctx = _hook_target(hook, ctx)
        key = (hook.system, rel)
        if key not in changes:
            path = sdir / rel
            if not path.is_file():
                raise PatchError(f"{hook.system}/{rel}: missing")
            data = path.read_bytes()
            changes[key] = {"system": hook.system, "path": rel, "action": "modify", "before": data, "after": data}
        changes[key]["after"] = insert_hook(changes[key]["after"], hook, patch.id, hctx)
    for payload in patch.payloads:
        sdir = _sysdir(ctx, payload.system)
        for rel, data in payload_files(payload, ctx).items():
            path = sdir / rel
            if path.exists():
                if path.is_file() and path.read_bytes() == data:
                    raise PatchError(f"{payload.system}/{rel}: already present without a Kit record")
                raise PatchError(f"{payload.system}/{rel}: exists with different content")
            changes[(payload.system, rel)] = {"system": payload.system, "path": rel, "action": "add",
                                              "before": None, "after": data}
    out = []
    for ch in changes.values():
        project_rel = f"{SYSTEM_BY_KEY[ch['system']].folder}/{ch['path']}"
        if is_frozen(project_rel):
            raise PatchError(f"{project_rel}: frozen operator file — never touched")
        if ch["action"] == "add" and inside_static(ch["path"]):
            raise PatchError(f"{project_rel}: payload may not live inside a static folder")
        ch["project_path"] = project_rel
        out.append(ch)
    return out


def confirm_code(patch: Patch, ctx: dict, changes: list[dict]) -> str:
    material = {"patch": patch.id,
                "anchors": {aid: (ctx["anchors"].get(aid) or {}).get("status") for aid in patch.anchors},
                "changes": sorted((c["project_path"], sha256_bytes(c["before"]) if c["before"] is not None else None,
                                   sha256_bytes(c["after"])) for c in changes)}
    return sha256_bytes(json.dumps(material, sort_keys=True).encode("utf-8"))[:10]


def _diff(ch: dict) -> str:
    if ch["action"] == "add":
        return f"+ {ch['project_path']} ({len(ch['after'])} bytes, sha256 {sha256_bytes(ch['after'])[:16]}…)"
    a = ch["before"].decode("utf-8", "replace").splitlines()
    b = ch["after"].decode("utf-8", "replace").splitlines()
    return "\n".join(difflib.unified_diff(a, b, f"a/{ch['project_path']}", f"b/{ch['project_path']}", lineterm="",
                                          n=2))


def evaluate(patch: Patch, ctx: dict, rs: dict, *, with_diffs: bool = False) -> tuple[dict, list[dict]]:
    entry = rs["patches"].get(patch.id) or {}
    base = {"id": patch.id, "flag": patch.flag, "title_ar": patch.title_ar, "title_en": patch.title_en,
            "summary_en": patch.summary_en, "systems": list(patch.systems), "notes": list(patch.notes)}
    if entry.get("active"):
        drift = []
        for f in entry["manifest"]["files"]:
            cur = sha256_file(ctx["root"] / f["project_path"])
            if cur != f["sha_after"]:
                drift.append({"path": f["project_path"], "expected": f["sha_after"], "found": cur})
        return {**base, "status": "applied_drifted" if drift else "applied", "drift": drift,
                "applied_at": entry["manifest"]["applied_at"], "backup_dirs": entry["manifest"]["backup_dirs"]}, []
    blockers, warnings = anchor_gate(patch, ctx)
    for hook in patch.hooks:
        try:
            rel, _ = _hook_target(hook, ctx)
            path = _sysdir(ctx, hook.system) / rel
            if path.is_file() and has_markers(path.read_bytes().decode("utf-8", "replace"), patch.id):
                blockers.append({"reason": f"{hook.system}/{rel}: {patch.id} markers present without a Kit record"})
        except PatchError:
            pass
    changes: list[dict] = []
    if not blockers:
        try:
            changes = compute_changes(patch, ctx)
        except PatchError as exc:
            blockers.append({"reason": str(exc)})
    if blockers:
        return {**base, "status": "blocked", "blockers": blockers, "warnings": warnings}, []
    out = {**base, "status": "ready", "warnings": warnings, "confirm_code": confirm_code(patch, ctx, changes),
           "files": [{"path": c["project_path"], "action": c["action"],
                      "sha_before": sha256_bytes(c["before"]) if c["before"] is not None else None,
                      "sha_after": sha256_bytes(c["after"])} for c in changes]}
    if with_diffs:
        out["diffs"] = [_diff(c) for c in changes if c["action"] == "modify"]
    return out, changes


# ---------------------------------------------------------------- helpers ----

def frozen_hashes(root: Path) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for rel in FROZEN_RELPATHS:
        p = Path(root) / rel
        if p.is_file():
            out[rel] = sha256_file(p)
    for p in walk_files(Path(root), names=FROZEN_NAMES, max_depth=8):
        out[p.relative_to(root).as_posix()] = sha256_file(p)
    return out


def default_test_runner(system_root: Path) -> dict:
    bat = Path(system_root) / "RUN_TESTS.bat"
    if not bat.is_file():
        return {"ran": False, "reason": "no RUN_TESTS.bat"}
    if sys.platform != "win32":
        return {"ran": False, "reason": "RUN_TESTS.bat needs Windows — pending on-device run"}
    from mxstudio.proc import run_hidden

    try:
        res = run_hidden(["cmd.exe", "/d", "/c", "RUN_TESTS.bat"], cwd=system_root, timeout=3600)
    except Exception as exc:  # noqa: BLE001
        return {"ran": True, "returncode": None, "error": str(exc)}
    tail = (res.stdout or b"")[-4000:].decode("utf-8", "replace")
    return {"ran": True, "returncode": res.returncode, "tail": tail}


def _unique_backup(sdir: Path, pid: str) -> Path:
    base = sdir / f"_backup_mag_{pid}_{today_stamp()}"
    cand, n = base, 2
    while cand.exists():
        cand = base.with_name(f"{base.name}_{n}")
        n += 1
    return cand


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".mag_tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _created_dirs(root: Path, changes: list[dict]) -> list[str]:
    created: set[str] = set()
    for ch in changes:
        if ch["action"] != "add":
            continue
        p = (root / ch["project_path"]).parent
        while not p.exists() and p != root:
            created.add(p.relative_to(root).as_posix())
            p = p.parent
    return sorted(created, key=lambda s: (s.count("/"), s))


def _remove_created_dirs(root: Path, dirs: list[str]) -> None:
    for rel in sorted(dirs, key=lambda s: -s.count("/")):
        d = root / rel
        if not d.is_dir():
            continue
        for cache in sorted(d.rglob("__pycache__"), key=lambda p: -len(p.parts)):
            if cache.is_dir() and all(f.suffix in (".pyc", ".pyo") for f in cache.iterdir()):
                shutil.rmtree(cache)
        try:
            d.rmdir()
        except OSError:
            pass


def _restore(root: Path, manifest: dict) -> tuple[bool, list[dict], list[tuple[str, Path, bytes | None]]]:
    """Pre-check every file, then (if all clean) restore. Returns (ok, problems, actions)."""
    actions: list[tuple[str, Path, bytes | None]] = []
    problems = []
    for f in manifest["files"]:
        path = root / f["project_path"]
        cur = sha256_file(path)
        if f["action"] == "modify":
            if cur == f["sha_before"]:
                continue
            restored = None
            if cur == f["sha_after"]:
                backup = Path(f["backup"])
                data = backup.read_bytes() if backup.is_file() else None
                if data is not None and sha256_bytes(data) == f["sha_before"]:
                    restored = data
            if restored is None and cur is not None:
                stripped = remove_hook(path.read_bytes(), manifest["patch"])
                if sha256_bytes(stripped) == f["sha_before"]:
                    restored = stripped
            if restored is not None:
                actions.append(("write", path, restored))
                continue
            problems.append({"path": f["project_path"], "problem": "file changed since the patch (or backup lost)",
                             "expected": f["sha_after"], "found": cur})
        else:
            if cur is None:
                continue
            if cur == f["sha_after"]:
                actions.append(("delete", path, None))
            else:
                problems.append({"path": f["project_path"], "problem": "added file was modified", "found": cur})
    if problems:
        return False, problems, []
    for kind, path, data in actions:
        if kind == "write":
            _atomic_write(path, data)
        else:
            path.unlink()
    _remove_created_dirs(root, manifest.get("created_dirs", []))
    return True, [], actions


# ---------------------------------------------------------------- public API ----

def plan(root: Path | str | None = None, *, overrides: dict | None = None, patch_ids: list[str] | None = None,
         with_diffs: bool = True) -> dict:
    ctx = build_context(root, overrides)
    rs = _root_state(load_state(), ctx["root"])
    rows = [evaluate(PATCHES[pid], ctx, rs, with_diffs=with_diffs)[0] for pid in (patch_ids or list(PATCHES))]
    return {"root": str(ctx["root"]), "patches": rows, "unwired_flags": UNWIRED_FLAGS,
            "anchor_counts": ctx["verified"]["counts"]}


def apply_patch(pid: str, *, root: Path | str | None = None, confirm: str | None = None, dry_run: bool = False,
                run_tests: bool = True, test_runner: TestRunner | None = None, overrides: dict | None = None) -> dict:
    if pid not in PATCHES:
        return {"result": "error", "reason": f"unknown patch {pid}"}
    patch = PATCHES[pid]
    ctx = build_context(root, overrides)
    root_p = ctx["root"]
    state = load_state()
    rs = _root_state(state, root_p)
    ev, changes = evaluate(patch, ctx, rs, with_diffs=dry_run)
    if ev["status"] in ("applied", "applied_drifted"):
        return {"result": "already_applied", **ev}
    if ev["status"] != "ready":
        log_event("apply_refused", patch=pid, blockers=ev.get("blockers"))
        return {"result": "refused", "reason": "blocked", **ev}
    if dry_run:
        return {"result": "dry_run", **ev}
    if confirm != ev["confirm_code"]:
        ev.pop("confirm_code", None)
        return {"result": "refused", "reason": "confirmation_required",
                "message_ar": "لازم موافقة المشغّل على الباتش ده: شغّل plan وخد كود التأكيد.",
                "message_en": "Operator confirmation required: run `plan` and pass its confirm code.", **ev}
    runner = test_runner or default_test_runner
    sysdirs = {s: _sysdir(ctx, s) for s in patch.systems}
    frozen_before = frozen_hashes(root_p)
    baseline = {s: runner(d) for s, d in sysdirs.items()} if run_tests else {}
    backups: dict[str, Path] = {}
    for s, d in sysdirs.items():
        if any(c["system"] == s and c["action"] == "modify" for c in changes):
            b = _unique_backup(d, pid)
            if inside_static(b.relative_to(root_p).as_posix()):
                return {"result": "refused", "reason": f"backup would be inside a static folder: {b}"}
            backups[s] = b
    created = _created_dirs(root_p, changes)
    files = []
    for c in changes:
        row = {"system": c["system"], "path": c["path"], "project_path": c["project_path"], "action": c["action"],
               "sha_before": sha256_bytes(c["before"]) if c["before"] is not None else None,
               "sha_after": sha256_bytes(c["after"])}
        if c["action"] == "modify":
            bpath = backups[c["system"]] / c["path"]
            bpath.parent.mkdir(parents=True, exist_ok=True)
            bpath.write_bytes(c["before"])
            if sha256_file(bpath) != row["sha_before"]:
                raise PatchError(f"backup verification failed for {c['project_path']}")
            row["backup"] = str(bpath)
        files.append(row)
    manifest = {"patch": pid, "flag": patch.flag, "applied_at": now_iso(), "root": str(root_p),
                "confirm_code": ev["confirm_code"], "backup_dirs": [str(b) for b in backups.values()],
                "files": files, "created_dirs": created, "anchors": {a: (ctx["anchors"].get(a) or {}).get("status")
                                                                      for a in patch.anchors}}
    for c in changes:
        _atomic_write(root_p / c["project_path"], c["after"])
    bad = [f["project_path"] for f in files if sha256_file(root_p / f["project_path"]) != f["sha_after"]]
    frozen_after = frozen_hashes(root_p)
    if bad or frozen_after != frozen_before:
        _restore(root_p, manifest)
        return {"result": "error", "reason": "post-write verification failed", "bad": bad,
                "frozen_changed": frozen_after != frozen_before}
    manifest["frozen"] = {"before": frozen_before, "after": frozen_after, "unchanged": True}
    after_tests = {s: runner(d) for s, d in sysdirs.items()} if run_tests else {}
    manifest["tests"] = {"baseline": baseline, "after": after_tests}
    regressed = [s for s, r in after_tests.items() if r.get("ran") and r.get("returncode") not in (0, None)
                 and not (baseline.get(s, {}).get("ran") and baseline[s].get("returncode") not in (0, None))]
    if regressed:
        ok, problems, _ = _restore(root_p, manifest)
        log_event("apply_rolled_back", patch=pid, systems=regressed)
        return {"result": "rolled_back_tests_failed", "systems": regressed, "restored": ok, "problems": problems,
                "tests": manifest["tests"]}
    rs["seq"] += 1
    rs["patches"][pid] = {"active": True, "seq": rs["seq"], "manifest": manifest}
    save_state(state)
    for b in backups.values():
        write_json(b / "manifest.json", manifest)
    log_event("applied", patch=pid, files=[f["project_path"] for f in files])
    return {"result": "applied", "patch": pid, "flag": patch.flag, "flag_default": "0 (off)",
            "files": files, "backup_dirs": manifest["backup_dirs"], "tests": manifest["tests"],
            "frozen_unchanged": True}


def revert_patch(pid: str, *, root: Path | str | None = None, cascade: bool = False) -> dict:
    root_p = Path(root) if root else Path(discover(None)["root"])
    state = load_state()
    rs = _root_state(state, root_p)
    entry = rs["patches"].get(pid)
    if not entry or not entry.get("active"):
        return {"result": "not_applied", "patch": pid}
    mine = {f["project_path"] for f in entry["manifest"]["files"]}
    later = sorted(((other, e) for other, e in rs["patches"].items()
                    if other != pid and e.get("active") and e["seq"] > entry["seq"]
                    and mine & {f["project_path"] for f in e["manifest"]["files"]}),
                   key=lambda t: -t[1]["seq"])
    if later and not cascade:
        return {"result": "refused", "reason": "later patches share files — revert them first (or --cascade)",
                "later": [o for o, _ in later]}
    cascaded = []
    for other, _ in later:
        res = revert_patch(other, root=root_p, cascade=True)
        cascaded.append(res)
        if res["result"] != "reverted":
            return {"result": "refused", "reason": f"cascade revert of {other} failed", "cascade": cascaded}
        state = load_state()
        rs = _root_state(state, root_p)
        entry = rs["patches"][pid]
    frozen_before = frozen_hashes(root_p)
    ok, problems, _ = _restore(root_p, entry["manifest"])
    if not ok:
        log_event("revert_refused", patch=pid, problems=problems)
        return {"result": "refused", "reason": "drift", "problems": problems,
                "message_ar": "في ملفات اتغيّرت بعد الباتش؛ مش هرجّع حاجة من غير مراجعة.",
                "message_en": "Files changed after the patch; nothing was reverted."}
    frozen_after = frozen_hashes(root_p)
    verified = all(sha256_file(root_p / f["project_path"]) == f["sha_before"]
                   for f in entry["manifest"]["files"] if f["action"] == "modify")
    removed = all(not (root_p / f["project_path"]).exists()
                  for f in entry["manifest"]["files"] if f["action"] == "add")
    entry["active"] = False
    entry["reverted_at"] = now_iso()
    save_state(state)
    log_event("reverted", patch=pid)
    return {"result": "reverted", "patch": pid, "byte_identical": verified, "added_files_removed": removed,
            "frozen_unchanged": frozen_before == frozen_after, "cascade": cascaded,
            "backup_dirs_kept": entry["manifest"]["backup_dirs"]}


def status(root: Path | str | None = None) -> dict:
    ctx = build_context(root)
    rs = _root_state(load_state(), ctx["root"])
    rows = []
    for pid, patch in PATCHES.items():
        ev, _ = evaluate(patch, ctx, rs)
        entry = rs["patches"].get(pid) or {}
        rows.append({"id": pid, "flag": patch.flag, "status": ev["status"], "flag_value_here":
                     os.environ.get(patch.flag, "0"), "reverted_at": entry.get("reverted_at"),
                     "drift": ev.get("drift"), "blockers": len(ev.get("blockers", []))})
    return {"root": str(ctx["root"]), "patches": rows}


def manifests(root: Path | str) -> list[dict]:
    rs = _root_state(load_state(), Path(root))
    return [dict(e["manifest"], active=e.get("active"), reverted_at=e.get("reverted_at"))
            for e in rs["patches"].values()]
