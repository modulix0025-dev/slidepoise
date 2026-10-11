"""Background-worker handlers for the Kit's long steps (proof runner, device report)."""
from __future__ import annotations

from pathlib import Path


def _proofs(payload: dict) -> dict:
    from .proofs import run_proofs

    res = run_proofs(payload.get("root"), engines=payload.get("engines") or "powerpoint,soffice",
                     limit=payload.get("limit"), story=payload.get("story"))
    return {"dir": res["dir"], "signature": res["signature"],
            "steps": {k: (v.get("status") if isinstance(v, dict) else v) for k, v in res["report"]["steps"].items()}}


def _report(payload: dict) -> dict:
    from .report import build_report

    out = payload.get("out")
    return build_report(payload.get("root"), out_dir=Path(out) if out else None)


HANDLERS = {"kit.proofs": _proofs, "kit.report": _report}
