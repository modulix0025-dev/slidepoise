"""``python -m mxstudio.kit <command>`` — non-interactive, JSON on stdout.

Commands: discover · verify · probe · plan · apply · revert · status · proofs · report ·
pack-build · pack-import. Exit codes: 0 done, 2 refused/blocked (named reason in the JSON), 1 error.
Nothing irreversible happens without ``--confirm <code>`` from ``plan`` (per patch).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _overrides(args) -> dict:
    app_files = {}
    for item in args.app_file or []:
        system, _, rel = item.partition("=")
        if system and rel:
            app_files[system] = rel.replace("\\", "/")
    return {"app_files": app_files} if app_files else {}


def _emit(obj: Any) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, indent=1, default=str) + "\n")


def _secret() -> str | None:
    from . import _vendor

    return _vendor.signing().resolve_secret_from_env()[0]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="mxstudio kit", description="ModuleX Magazine Studio Integration Kit")
    ap.add_argument("--root", help="project root (default: the Studio setting, C:\\المشروع)")
    ap.add_argument("--app-file", action="append", metavar="SYSTEM=RELPATH",
                    help="pin the FastAPI app module of a system when discovery finds several")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("discover")
    sub.add_parser("verify")
    p = sub.add_parser("probe")
    p.add_argument("--no-network", action="store_true")
    p.add_argument("--base-name", action="append", default=[])
    p = sub.add_parser("plan")
    p.add_argument("--patch", action="append")
    p = sub.add_parser("apply")
    p.add_argument("--patch", required=True)
    p.add_argument("--confirm")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-tests", action="store_true")
    p = sub.add_parser("revert")
    p.add_argument("--patch", required=True)
    p.add_argument("--cascade", action="store_true")
    sub.add_parser("status")
    p = sub.add_parser("proofs")
    p.add_argument("--engines", default="powerpoint,soffice")
    p.add_argument("--limit", type=int)
    p.add_argument("--story")
    p.add_argument("--no-story", action="store_true")
    p = sub.add_parser("report")
    p.add_argument("--out")
    p.add_argument("--no-network", action="store_true")
    p = sub.add_parser("pack-build")
    p.add_argument("--kind", required=True, choices=["m1", "m2", "m6", "m7"])
    p.add_argument("--document", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--file", action="append", default=[], metavar="NAME=PATH")
    p.add_argument("--out", required=True)
    p = sub.add_parser("pack-import")
    p.add_argument("--pack", required=True)
    p.add_argument("--system", required=True, choices=["OM", "Console"])
    args = ap.parse_args(argv)

    try:
        return _run(args)
    except Exception as exc:  # noqa: BLE001 - the CLI always answers in JSON
        _emit({"result": "error", "error": f"{exc.__class__.__name__}: {exc}"})
        return 1


def _run(args) -> int:
    from . import apply as kit_apply
    from .anchors import verify
    from .discover import discover, system_dir

    root = args.root
    if args.cmd == "discover":
        _emit(discover(root))
        return 0
    if args.cmd == "verify":
        res = verify(discover(root), overrides=_overrides(args))
        _emit(res)
        return 0 if all(a["status"] in ("ok",) or a.get("severity") == "info" for a in res["anchors"]) else 2
    if args.cmd == "probe":
        from .probe import DEFAULT_BASE_NAMES, probe

        _emit(probe(discover(root), base_names=tuple(DEFAULT_BASE_NAMES) + tuple(args.base_name),
                    network=not args.no_network))
        return 0
    if args.cmd == "plan":
        _emit(kit_apply.plan(root, overrides=_overrides(args), patch_ids=args.patch))
        return 0
    if args.cmd == "apply":
        res = kit_apply.apply_patch(args.patch, root=root, confirm=args.confirm, dry_run=args.dry_run,
                                    run_tests=not args.no_tests, overrides=_overrides(args))
        _emit(res)
        return 0 if res["result"] in ("applied", "already_applied", "dry_run") else 2
    if args.cmd == "revert":
        res = kit_apply.revert_patch(args.patch, root=root, cascade=args.cascade)
        _emit(res)
        return 0 if res["result"] in ("reverted", "not_applied") else 2
    if args.cmd == "status":
        _emit(kit_apply.status(root))
        return 0
    if args.cmd == "proofs":
        from .proofs import run_proofs

        res = run_proofs(root, engines=args.engines, limit=args.limit, story=args.story, run_story=not args.no_story)
        _emit({"result": res["result"], "dir": res["dir"], "signature": res["signature"],
               "steps": {k: v.get("status", "") if isinstance(v, dict) else v
                         for k, v in res["report"]["steps"].items()}})
        return 0
    if args.cmd == "report":
        from .report import build_report

        _emit(build_report(root, out_dir=Path(args.out) if args.out else None,
                           probe_kwargs={"network": not args.no_network}))
        return 0
    if args.cmd == "pack-build":
        from mxstudio.receivers.packs import build_pack

        from . import _vendor

        secret = _secret()
        if not secret:
            _emit({"result": "refused", "reason": "no shared secret in MODULEX_HMAC_SECRET (or legacy names)"})
            return 2
        files = {}
        for item in args.file:
            name, _, path = item.partition("=")
            files[name] = Path(path).read_bytes()
        doc = json.loads(Path(args.document).read_text(encoding="utf-8"))
        data = build_pack(args.kind, doc, secret=secret, signing=_vendor.signing(), pack_id=args.id, files=files)
        Path(args.out).write_bytes(data)
        _emit({"result": "ok", "path": args.out, "bytes": len(data)})
        return 0
    if args.cmd == "pack-import":
        from mxstudio.receivers.packs import import_pack
        from mxstudio.receivers.store import CandidateStore

        from . import _vendor

        found = discover(root)
        sdir = system_dir(found, args.system)
        secret = _secret()
        if sdir is None or not secret:
            _emit({"result": "refused", "reason": "system not found or no shared secret"})
            return 2
        status, body = import_pack(Path(args.pack).read_bytes(), secret=secret, signing=_vendor.signing(),
                                   store=CandidateStore(sdir / "mag_candidates"))
        _emit({"result": "ok" if body.get("ok") else "refused", "http_status": status, **body})
        return 0 if body.get("ok") else 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
