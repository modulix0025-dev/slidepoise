"""Fetch the Arabic title/name fonts of every type theme into a test folder (CI step; tests never use the network).

    python tools/fetch_test_fonts.py [--out workspace/test-fonts] [--all]

Files come from catalog/fonts/catalog.json (google/fonts at a pinned commit) and are verified against the pinned
sha256 before they are kept. Default: the families used as ar_title / ar_name / ar_dedication by any theme (the
fonts the hamza-name text proof must pass with); --all: every family any theme uses (the no-substitute export proof).
Tests look for the folder in MXS_TEST_FONTS or workspace/test-fonts and skip when it is missing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TITLE_ROLES = ("ar_title", "ar_name", "ar_dedication")


def _get(url: str, attempts: int = 8) -> bytes:
    import time  # noqa: PLC0415
    import urllib.error  # noqa: PLC0415
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310 - pinned https URL
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 502, 503) or attempt == attempts - 1:
                raise
            time.sleep(min(60, 3 * 2 ** attempt))
    raise RuntimeError("unreachable")


def families(all_roles: bool) -> set[str]:
    themes = json.loads((ROOT / "catalog" / "fonts" / "type_themes.json").read_text(encoding="utf-8"))["themes"]
    return {v for t in themes for k, v in t.items()
            if isinstance(v, str) and (k in TITLE_ROLES or (all_roles and k.startswith(("ar_", "en_"))))}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "workspace" / "test-fonts"))
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    catalog = {f["family"]: f for f in json.loads((ROOT / "catalog" / "fonts" / "catalog.json").read_text("utf-8"))["families"]}
    wanted = sorted(families(args.all))
    fetched, kept = 0, 0
    for family in wanted:
        for item in catalog[family]["files"]:
            target = out / item["file"]
            if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == item["sha256"]:
                kept += 1
                continue
            data = _get(item["url"])
            if hashlib.sha256(data).hexdigest() != item["sha256"]:
                print(f"sha256 mismatch for {item['url']}", file=sys.stderr)
                return 1
            target.write_bytes(data)
            fetched += 1
    (out / "FAMILIES.json").write_text(json.dumps(wanted, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"families": len(wanted), "fetched": fetched, "kept": kept, "out": str(out)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
