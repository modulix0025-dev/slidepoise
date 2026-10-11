"""``python -m mxstudio.update`` / ``mxstudio-cli.exe update …``.

Operator / release commands::

    keygen  --out-private FILE            new Ed25519 pair; private half only to FILE (never stdout)
    manifest --version V --base-url URL --online EXE [--full EXE] --out FILE
    sign    --manifest IN --out OUT       key from $MXS_UPDATE_SIGNING_KEY or --key-file
    verify  --manifest FILE [--pubkey B64]... [--assets-dir DIR]
    embed   [--repo OWNER/NAME] [--pubkey B64]   write trust.json at build time

App commands (JSON on stdout and/or ``--out``)::

    check [--url URL] | status | download | stage | consent [--no] | apply | rollback | launch
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import manifest as mf
from . import signing
from . import trust as trust_mod
from .cliout import emit
from .download import verify_file
from .errors import UpdateError
from .state import UpdateManager


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mxstudio update")
    sub = p.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("keygen")
    k.add_argument("--out-private", required=True)
    m = sub.add_parser("manifest")
    m.add_argument("--version", required=True)
    m.add_argument("--base-url", required=True)
    m.add_argument("--online", required=True)
    m.add_argument("--full")
    m.add_argument("--tag")
    m.add_argument("--notes-ar", default="")
    m.add_argument("--notes-en", default="")
    m.add_argument("--out", required=True)
    s = sub.add_parser("sign")
    s.add_argument("--manifest", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--key-file")
    v = sub.add_parser("verify")
    v.add_argument("--manifest", required=True)
    v.add_argument("--pubkey", action="append", default=[])
    v.add_argument("--assets-dir")
    e = sub.add_parser("embed")
    e.add_argument("--repo")
    e.add_argument("--pubkey", action="append", default=[])
    e.add_argument("--trust-file")
    for name in ("check", "status", "download", "stage", "consent", "apply", "rollback", "launch"):
        a = sub.add_parser(name)
        a.add_argument("--json", action="store_true")
        a.add_argument("--out")
        if name == "check":
            a.add_argument("--url")
        if name == "consent":
            a.add_argument("--no", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return _run(args)
    except UpdateError as err:
        emit({"ok": False, "error": err.to_dict()}, out=getattr(args, "out", None))
        return 1


def _run(args: argparse.Namespace) -> int:
    if args.cmd == "keygen":
        target = Path(args.out_private)
        if target.exists():
            raise UpdateError("exists", "الملف موجود بالفعل — مش هنكتب فوقه.", f"{target} exists; refusing to overwrite.")
        private_b64, public_b64 = signing.generate_keypair()
        target.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as handle:
            handle.write(private_b64 + "\n")
        emit({"ok": True, "public_key": public_b64, "key_id": signing.key_id(public_b64),
              "private_key_file": str(target),
              "next_ar": "حط المفتاح الخاص في سر الـCI MXS_UPDATE_SIGNING_KEY وامسح الملف؛ والمفتاح العام في المتغيّر MXS_UPDATE_PUBLIC_KEY.",
              "next_en": "Store the private key as CI secret MXS_UPDATE_SIGNING_KEY and delete the file; "
                         "store the public key as repository variable MXS_UPDATE_PUBLIC_KEY."})
        return 0
    if args.cmd == "manifest":
        files = {"online": Path(args.online)}
        if args.full:
            files["full"] = Path(args.full)
        manifest = mf.build(args.version, args.base_url, files, tag=args.tag, notes_ar=args.notes_ar,
                            notes_en=args.notes_en)
        Path(args.out).write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        emit({"ok": True, "manifest": args.out, "version": manifest["version"]})
        return 0
    if args.cmd == "sign":
        key = Path(args.key_file).read_text(encoding="ascii") if args.key_file else os.environ.get("MXS_UPDATE_SIGNING_KEY", "")
        manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        signed = signing.sign_manifest(manifest, key)
        Path(args.out).write_text(json.dumps(signed, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        emit({"ok": True, "out": args.out, "key_id": signed["signature"]["key_id"]})
        return 0
    if args.cmd == "verify":
        manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        keys = args.pubkey or trust_mod.load().public_keys
        kid = signing.verify_manifest(manifest, keys)
        hosts = tuple({h for h in trust_mod.load().allowed_hosts} | {"github.com"})
        mf.validate(manifest, allowed_hosts=hosts)
        checked = []
        if args.assets_dir:
            for asset in manifest["assets"].values():
                verify_file(Path(args.assets_dir) / asset["name"], asset["sha256"], asset["size"])
                checked.append(asset["name"])
        emit({"ok": True, "key_id": kid, "version": manifest["version"], "assets_verified": checked})
        return 0
    if args.cmd == "embed":
        path = Path(args.trust_file) if args.trust_file else None
        trust = trust_mod.load(path)
        if args.repo:
            trust.release_repo = args.repo
            trust.manifest_url = trust_mod.stable_manifest_url(args.repo)
        for key in [*args.pubkey, *filter(None, [os.environ.get("MXS_UPDATE_PUBLIC_KEY", "").strip()])]:
            trust.public_keys[signing.key_id(key)] = key
        written = trust_mod.save(trust, path)
        emit({"ok": True, "trust_file": str(written), "key_ids": sorted(trust.public_keys),
              "manifest_url": trust.manifest_url})
        return 0

    manager = UpdateManager()
    if args.cmd == "check":
        result = manager.check(args.url)
    elif args.cmd == "status":
        result = manager.state() | {"history": manager.history(),
                                    "rollback_target": (manager.rollback_target() or {}).get("version")}
    elif args.cmd == "download":
        result = manager.download()
    elif args.cmd == "stage":
        result = manager.stage()
    elif args.cmd == "consent":
        result = manager.consent(not args.no)
    elif args.cmd == "apply":
        result = {"started": manager.apply()} | manager.state()
    elif args.cmd == "rollback":
        result = {"started": manager.rollback()} | manager.state()
    else:  # launch
        result = {"exit_for_installer": manager.launch_hook()} | manager.state()
    emit(result, out=args.out)
    return 0 if not result.get("error") else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
