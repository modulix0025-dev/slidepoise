"""Collect the Full (offline) installer payload listed in installer/downloads.json.

Every entry whose ``flavours.full`` is ``bundled`` is downloaded (resumable) and verified
against its pinned sha256 into ``<out>/<offline_path>``; ``<out>/offline_manifest.json``
records what is inside.

Strict by default: an entry still marked TO-PIN fails the build. With ``--allow-unpinned``
(manual release dispatch only) an entry with a real URL but no pinned hash is downloaded and
its *computed* sha256 is recorded with ``"pinned": false`` (printed so the operator can pin
it); an entry whose URL itself is TO-PIN is recorded as ``missing``. Nothing is ever
reported as pinned when it was not.

    python installer/fetch_offline_payload.py --out workspace/offline [--allow-unpinned]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mxstudio.update import payloads
from mxstudio.update.download import download, urllib_transport


def _unpinned_download(url: str, dest: Path) -> tuple[str, int]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    digest, size = hashlib.sha256(), 0
    response = urllib_transport(url, 0)
    with open(dest, "wb") as handle:
        for block in response.chunks:
            handle.write(block)
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--manifest", default=str(ROOT / "installer" / "downloads.json"))
    parser.add_argument("--allow-unpinned", action="store_true")
    args = parser.parse_args(argv)
    manifest = payloads.load(Path(args.manifest))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    record: dict = {"schema": "mxs-offline/1", "entries": {}}
    failed = []
    for name, item in manifest["entries"].items():
        if (item.get("flavours") or {}).get("full") != "bundled":
            continue
        dest = out / item["offline_path"]
        if payloads.is_pinned(item):
            download(item["url"], dest, sha256=item["sha256"], size=item.get("size"))
            record["entries"][name] = {"file": item["offline_path"], "sha256": item["sha256"],
                                       "size": dest.stat().st_size, "pinned": True, "status": "bundled"}
            print(f"bundled {name}: {item['sha256']}")
            continue
        if not args.allow_unpinned:
            failed.append(name)
            continue
        if payloads.TO_PIN in item["url"]:
            record["entries"][name] = {"file": item["offline_path"], "pinned": False, "status": "missing",
                                       "reason": "url is TO-PIN"}
            print(f"MISSING {name}: url is TO-PIN; the Full installer will not contain it")
            continue
        sha, size = _unpinned_download(item["url"], dest)
        record["entries"][name] = {"file": item["offline_path"], "sha256": sha, "size": size, "pinned": False,
                                   "status": "bundled_unpinned"}
        print(f"UNPINNED {name}: computed sha256 {sha} size {size} -- pin it in installer/downloads.json")
    if failed:
        print("refusing to build the Full payload; still TO-PIN: " + ", ".join(failed), file=sys.stderr)
        return 1
    (out / "offline_manifest.json").write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
