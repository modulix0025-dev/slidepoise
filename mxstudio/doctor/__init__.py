"""Doctor: environment checks with a «إصلاح» action per red line.

Checks (ids): python, node, office (PowerPoint or LibreOffice), pypdfium2, fonts, webview2,
providers, system_om (8000), system_console (6060), system_store (8200), workspace, disk,
arabic_path (write/read + child process + Node, paths via env).

CLI (``python -m mxstudio.doctor`` / ``mxstudio-cli.exe doctor``)::

    doctor [--json] [--out FILE] [--only id,id]   run checks (exit 1 if any red line)
    doctor --fix FIX_ID [--consent] [--out FILE]  run one fixer
    doctor --child-roundtrip                      internal: Arabic-path child step
"""
from __future__ import annotations

import argparse
import sys

from .checks import CHECKS, CheckResult, child_roundtrip, run_all, summary
from .context import DoctorContext
from .fixers import FIXERS, run_fix


def main(argv: list[str] | None = None) -> int:
    from mxstudio.update.cliout import emit

    parser = argparse.ArgumentParser(prog="mxstudio doctor")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out")
    parser.add_argument("--only")
    parser.add_argument("--fix")
    parser.add_argument("--consent", action="store_true")
    parser.add_argument("--child-roundtrip", action="store_true")
    args = parser.parse_args(argv)
    if args.child_roundtrip:
        return child_roundtrip()
    if args.fix:
        result = run_fix(args.fix, consent=args.consent)
        emit(result, out=args.out)
        return 0 if result.get("ok") else 1
    results = run_all(only=args.only.split(",") if args.only else None)
    report = {"summary": summary(results), "checks": results,
              "python": sys.version.split()[0], "frozen": bool(getattr(sys, "frozen", False))}
    if args.json or args.out:
        emit(report, out=args.out)
    else:
        lines = [f"{ {'ok': '✔', 'skip': '–', 'warn': '!'}.get(r['level'], '✘')} {r['ar']} · {r['en']}"
                 for r in results]
        emit(report, as_json=False, text="\n".join(lines))
    return 0 if report["summary"]["ok"] else 1


__all__ = ["CHECKS", "FIXERS", "CheckResult", "DoctorContext", "main", "run_all", "run_fix", "summary"]
