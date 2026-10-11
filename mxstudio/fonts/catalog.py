"""Load and validate the font catalog DB (``catalog/fonts/catalog.json``).

Rules enforced by :func:`validate_catalog` (each failure is a named finding):

* pinned to the google/fonts commit in :mod:`mxstudio.fonts.paths`; every
  file URL is the raw URL of that commit with percent-encoded segments;
* exactly the appendix families (same ids, family names and directories), no
  duplicates;
* every file carries a sha256, every family a licence file with sha256, and
  the licence is one the print policy allows (OFL-1.1 / Apache-2.0);
* flags agree with the files (COLOR ⇔ colour tables, VAR ⇔ fvar, RFN ⇔
  declared reserved names).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from mxstudio.fonts.build_catalog import read_appendix
from mxstudio.fonts.paths import APPENDIX_TSV, CATALOG_JSON, LICENCE_POLICY, PINNED_COMMIT, raw_url

_SHA = re.compile(r"^[0-9a-f]{64}$")
FONT_LICENCES = {"OFL-1.1", "Apache-2.0"}


@dataclass(frozen=True)
class Finding:
    finding: str
    subject: str
    detail: str

    def as_dict(self) -> dict:
        return {"finding": self.finding, "subject": self.subject, "detail": self.detail}


class Catalog:
    """Read-only view of catalog.json with lookups by id and by exact family name."""

    def __init__(self, data: dict):
        self.data = data
        self.families: list[dict] = data["families"]
        self._by_id = {fam["id"]: fam for fam in self.families}
        self._by_family = {fam["family"]: fam for fam in self.families}

    @property
    def commit(self) -> str:
        return self.data["source"]["commit"]

    def by_id(self, font_id: str) -> dict | None:
        return self._by_id.get(font_id)

    def by_family(self, family: str) -> dict | None:
        """Exact family name (the catalog's names are the google/fonts names)."""
        return self._by_family.get(family)

    def __contains__(self, family: str) -> bool:
        return family in self._by_family

    def __len__(self) -> int:
        return len(self.families)

    def colour_families(self) -> list[str]:
        return sorted(fam["family"] for fam in self.families if fam["is_colour"])


def load_catalog(path: Path = CATALOG_JSON) -> Catalog:
    return Catalog(json.loads(Path(path).read_text(encoding="utf-8")))


@lru_cache(maxsize=1)
def default_catalog() -> Catalog:
    return load_catalog()


def _allowed_licences() -> set[str]:
    policy = json.loads(LICENCE_POLICY.read_text(encoding="utf-8"))
    return set(policy["print_asset_allowlist"]) & FONT_LICENCES


def validate_catalog(data: dict, *, tsv: Path = APPENDIX_TSV) -> list[Finding]:
    findings: list[Finding] = []
    add = lambda f, s, d: findings.append(Finding(f, s, d))  # noqa: E731
    commit = data.get("source", {}).get("commit")
    if commit != PINNED_COMMIT:
        add("catalog_commit_not_pinned", "catalog", f"{commit} != {PINNED_COMMIT}")
    allowed = _allowed_licences()
    expected = {row["id"]: row for row in read_appendix(tsv)}
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    for fam in data.get("families", []):
        subject = f"{fam.get('id')} {fam.get('family')}"
        if fam.get("id") in seen_ids:
            add("catalog_duplicate_id", subject, fam.get("id", ""))
        if fam.get("family") in seen_names:
            add("catalog_duplicate_family", subject, fam.get("family", ""))
        seen_ids.add(fam.get("id"))
        seen_names.add(fam.get("family"))
        row = expected.get(fam.get("id"))
        if row is None:
            add("catalog_family_not_in_appendix", subject, "id not in the appendix")
        elif (row["family"], row["repo_dir"]) != (fam.get("family"), fam.get("repo_dir")):
            add("catalog_family_mismatch", subject, f"appendix says {row['family']} @ {row['repo_dir']}")
        if fam.get("licence") not in allowed:
            add("catalog_licence_not_allowed", subject, str(fam.get("licence")))
        licence_file = fam.get("licence_file") or {}
        if not _SHA.match(licence_file.get("sha256", "")):
            add("catalog_licence_file_missing", subject, "no licence file sha256")
        files = fam.get("files") or []
        if not files:
            add("catalog_family_without_files", subject, "")
        for item in files:
            if not _SHA.match(item.get("sha256", "")):
                add("catalog_file_without_sha256", subject, item.get("file", "?"))
            if item.get("url") != raw_url(fam.get("repo_dir", ""), item.get("file", ""), commit or PINNED_COMMIT):
                add("catalog_file_url_not_pinned", subject, item.get("url", ""))
        colour = any(item.get("color_tables") for item in files)
        variable = any(item.get("variable") for item in files)
        flags = set(fam.get("flags", []))
        if colour != ("COLOR" in flags) or colour != bool(fam.get("is_colour")):
            add("catalog_colour_flag_wrong", subject, f"tables={colour} flags={sorted(flags)}")
        if variable != ("VAR" in flags):
            add("catalog_variable_flag_wrong", subject, f"fvar={variable} flags={sorted(flags)}")
        if bool(fam.get("reserved_font_names")) != ("RFN" in flags):
            add("catalog_rfn_flag_wrong", subject, f"rfn={fam.get('reserved_font_names')}")
    for missing in sorted(set(expected) - seen_ids):
        add("catalog_family_missing", f"{missing} {expected[missing]['family']}", "in the appendix, not the catalog")
    return findings
