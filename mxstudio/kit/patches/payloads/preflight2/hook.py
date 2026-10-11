"""Wrap OM ``printing.preflight.run`` so its result also carries the ``mx_preflight2`` findings.

The original ``run`` is called first with the exact same arguments; its result object is
returned (mutated by appending). If the result shape is unknown it is returned unchanged and
the findings are attached under ``mag_preflight2`` when possible — never a silent drop.
A blocking finding (``ok: false``) flips ``result["ok"]`` to False; the print service decides.
"""
from __future__ import annotations

import functools
import sys
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any


def load_lib():
    vendor = Path(__file__).resolve().parent / "vendor"
    if str(vendor) not in sys.path:
        sys.path.insert(0, str(vendor))
    import mx_preflight2

    return mx_preflight2


def profile_from(kwargs: dict) -> dict:
    """mx_preflight2 profile from preflight.run's own keyword arguments and OM's defaults (bleed 0 mm)."""
    profile = {"size": kwargs.get("magazine_size", "A4"), "bleed_mm": float(kwargs.get("bleed_mm", Decimal(0))),
               "expected_pages": kwargs.get("expected_pages")}
    if kwargs.get("max_bytes"):
        profile["max_bytes"] = int(kwargs["max_bytes"])
    return profile


def run_v2(path, kwargs: dict, lib=None) -> dict:
    try:
        lib = lib or load_lib()
        res = lib.run(str(path), profile_from(kwargs))
        return res if isinstance(res, dict) else {"ok": False, "checks": [], "warnings": ["unexpected result"]}
    except Exception as exc:  # noqa: BLE001 - a broken check is a named finding, not a crash
        return {"ok": False, "warnings": [],
                "checks": [{"id": "mag_preflight2_error", "ok": False, "detail": f"{exc.__class__.__name__}: {exc}"}]}


def append_checks(result: Any, v2: dict) -> Any:
    checks = [dict(c, source="mx_preflight2") if isinstance(c, dict) else {"detail": c, "source": "mx_preflight2"}
              for c in v2.get("checks", [])]
    if isinstance(result, dict):
        if isinstance(result.get("checks"), list):
            result["checks"].extend(checks)
        else:
            result["mag_preflight2"] = {"checks": checks}
        if v2.get("warnings"):
            if isinstance(result.get("warnings"), list):
                result["warnings"].extend(v2["warnings"])
            else:
                result.setdefault("mag_preflight2", {})["warnings"] = list(v2["warnings"])
        if "ok" in result and not v2.get("ok", True):
            result["ok"] = False
        return result
    if isinstance(getattr(result, "checks", None), list):
        result.checks.extend(checks)
        if hasattr(result, "ok") and not v2.get("ok", True):
            try:
                result.ok = False
            except Exception:  # noqa: BLE001
                pass
        return result
    try:
        result.mag_preflight2 = {"checks": checks, "ok": v2.get("ok")}
    except Exception:  # noqa: BLE001
        pass
    return result


def wrap_run(run: Callable, lib=None) -> Callable:
    @functools.wraps(run)
    def run_with_preflight2(path, *args, **kwargs):
        result = run(path, *args, **kwargs)
        return append_checks(result, run_v2(path, kwargs, lib))

    run_with_preflight2.__mag_wrapped__ = run
    return run_with_preflight2
