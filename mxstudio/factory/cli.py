"""`python -m mxstudio factory demo --out <dir>` — build and validate the demo story end to end (JSON report)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from mxstudio.factory.demo_story import moon_star_story
from mxstudio.factory.service import build_and_validate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mxstudio factory")
    parser.add_argument("command", choices=["demo"])
    parser.add_argument("--out", type=Path, default=Path("factory_demo"))
    parser.add_argument("--no-export", action="store_true")
    args = parser.parse_args(argv)
    result = build_and_validate(moon_star_story(), args.out, export=not args.no_export)
    summary = {"ok": result["validation"]["ok"], "contact_sheet": result["contact_sheet"],
               "variants": {k: {"ok": v["ok"], "findings": [f["code"] for f in v["findings"]],
                                "engine": v["facts"].get("export", {}).get("engine")}
                            for k, v in result["validation"]["variants"].items()}}
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0 if summary["ok"] else 1
