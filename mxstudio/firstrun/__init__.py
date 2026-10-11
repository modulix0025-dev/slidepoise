"""First run: the wizard backend (workspace → providers → discovery → doctor) and the Office engine.

CLI (``python -m mxstudio.firstrun`` / ``mxstudio-cli.exe firstrun``), JSON on stdout and/or ``--out``::

    status                          current wizard state
    workspace [--path P]            P, else $MXS_FIRSTRUN_WORKSPACE, else the default (C:\\المشروع\\…)
    skip STEP | back | reset
    discovery | doctor              run that step
    office [--consent]              make an Office engine available (PowerPoint or LibreOffice)

Imports are lazy: ``mxstudio.doctor`` imports ``firstrun.office`` and the wizard imports the doctor.
"""
from __future__ import annotations

import argparse
import os
from typing import Any


def main(argv: list[str] | None = None) -> int:
    from mxstudio.update.cliout import emit

    from .wizard import Wizard, WizardError

    parser = argparse.ArgumentParser(prog="mxstudio firstrun")
    parser.add_argument("cmd", nargs="?", default="status",
                        choices=["status", "workspace", "skip", "back", "reset", "discovery", "doctor", "office"])
    parser.add_argument("step", nargs="?")
    parser.add_argument("--path")
    parser.add_argument("--consent", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    wizard = Wizard()
    result: dict[str, Any]
    try:
        if args.cmd == "status":
            result = wizard.state()
        elif args.cmd == "workspace":
            result = wizard.submit("workspace", {"path": args.path or os.environ.get("MXS_FIRSTRUN_WORKSPACE")})
        elif args.cmd == "skip":
            result = wizard.skip(args.step or "")
        elif args.cmd == "back":
            result = wizard.back()
        elif args.cmd == "reset":
            result = wizard.reset()
        elif args.cmd in ("discovery", "doctor"):
            result = wizard.submit(args.cmd)
        else:
            from mxstudio.doctor import DoctorContext

            from .office import install_libreoffice
            result = install_libreoffice(DoctorContext.default(), consent_elevation=args.consent)
    except WizardError as err:
        emit({"ok": False, "error": err.to_dict()}, out=args.out)
        return 1
    emit(result, out=args.out)
    return 0 if result.get("ok", True) else 1
