"""One licence gate for every asset that could reach print (fonts, shapes, icons, images, model weights).

Driven by catalog/licence_policy.json (operator decision D13). Unknown licences
are refused; CC-BY-4.0 is allowed only with a credits entry.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

POLICY = Path(__file__).resolve().parents[1] / "catalog" / "licence_policy.json"
_ALIASES = {
    "cc0": "CC0-1.0", "cc0-1.0": "CC0-1.0", "public domain": "PDM", "pd": "PDM", "pdm": "PDM",
    "mit": "MIT", "isc": "ISC", "bsd-2-clause": "BSD-2-Clause", "bsd-3-clause": "BSD-3-Clause",
    "apache-2.0": "Apache-2.0", "apache 2.0": "Apache-2.0", "apache2": "Apache-2.0",
    "ofl": "OFL-1.1", "ofl-1.1": "OFL-1.1", "cc-by-4.0": "CC-BY-4.0", "cc by 4.0": "CC-BY-4.0", "by": None,
    "cc-by-sa-4.0": "CC-BY-SA-4.0", "cc by-sa 4.0": "CC-BY-SA-4.0", "cc-by-sa-3.0": "CC-BY-SA-3.0",
    "cc-by-nc-4.0": "CC-BY-NC-4.0", "cc by-nc 4.0": "CC-BY-NC-4.0", "cc-by-nc-sa-4.0": "CC-BY-NC-SA-4.0",
    "cc-by-nd-4.0": "CC-BY-ND-4.0", "cc-by-nc-nd-4.0": "CC-BY-NC-ND-4.0", "unlicense": "Unlicense",
    "cc-by-3.0": "CC-BY-3.0", "mpl-2.0": "MPL-2.0",
}


@lru_cache(maxsize=1)
def policy() -> dict:
    return json.loads(POLICY.read_text(encoding="utf-8"))


def normalise(licence: str | None) -> str:
    raw = (licence or "").strip()
    key = raw.lower().replace("_", "-")
    if key in _ALIASES and _ALIASES[key]:
        return _ALIASES[key]
    if re.search(r"personal|non[- ]?commercial|\bnc\b", key):
        return "personal-use" if "personal" in key else "CC-BY-NC-4.0"
    return raw or "UNKNOWN"


def print_decision(licence: str | None, *, has_credit: bool = False) -> dict:
    """{"allowed", "needs_credits", "licence", "reason_ar", "reason_en"} for print use."""
    spdx = normalise(licence)
    data = policy()
    if spdx in data["print_asset_pending_operator"]:
        return {"allowed": False, "needs_credits": False, "licence": spdx,
                "reason_ar": "الترخيص ده مستني قرارك قبل ما يدخل الطباعة.", "reason_en": "licence awaits the operator"}
    if spdx not in data["print_asset_allowlist"]:
        return {"allowed": False, "needs_credits": False, "licence": spdx,
                "reason_ar": "الترخيص ده مش مسموح في منتج مطبوع ومتباع.",
                "reason_en": "licence not allowed in a printed, sold product"}
    needs = spdx in data["print_asset_requires_credits"]
    if needs and not has_credit:
        return {"allowed": False, "needs_credits": True, "licence": spdx,
                "reason_ar": "مسموح بس لازم يتكتب اسم صاحبه في صفحة الشكر.", "reason_en": "allowed only with a credits entry"}
    return {"allowed": True, "needs_credits": needs, "licence": spdx, "reason_ar": "مسموح.", "reason_en": "allowed"}
