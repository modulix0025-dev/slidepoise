"""Customer proof approval {version, timestamp, sha256} bound to the exact PDF bytes.

Binding order: (1) a public ``print_service`` function from ``BIND_FUNCTIONS`` if the device has
one (called with keyword arguments only); (2) otherwise a sidecar ``<pdf>.proof_approval.json``
beside the PDF that the print portal reads with :func:`status`. An approval is valid only while
the PDF's sha256 equals the approved sha256 (any later edit invalidates it automatically).
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
from pathlib import Path
from typing import Any

BIND_FUNCTIONS = ("record_proof_approval", "attach_proof_approval", "bind_proof_approval")
SUFFIX = ".proof_approval.json"


def sidecar(pdf: Path) -> Path:
    return Path(str(pdf) + SUFFIX)


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def record(pdf: Path, *, version: str, order_ref: str, print_service: Any = None, actor: str = "customer") -> dict:
    rec = {"version": str(version), "timestamp": _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat(),
           "sha256": _sha(pdf), "actor": actor, "pdf": Path(pdf).name}
    bound = "sidecar"
    for name in BIND_FUNCTIONS:
        fn = getattr(print_service, name, None) if print_service is not None else None
        if callable(fn):
            fn(order_ref=order_ref, approval=dict(rec), actor=actor)
            bound = f"print_service.{name}"
            break
    rec["bound_via"] = bound
    tmp = sidecar(pdf).with_name(sidecar(pdf).name + ".tmp")
    tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, sidecar(pdf))
    return rec


def status(pdf: Path) -> dict:
    side = sidecar(pdf)
    if not side.is_file():
        return {"approved": False, "valid": False, "reason": "no approval"}
    rec = json.loads(side.read_text(encoding="utf-8"))
    current = _sha(pdf) if Path(pdf).is_file() else None
    valid = current == rec.get("sha256")
    return {"approved": True, "valid": valid, "record": rec,
            "reason": "ok" if valid else "the PDF changed after approval"}
