"""Font licence ledger: one written decision per catalog family.

Rules (OFL-1.1 and Apache-2.0 as read from the files at the pinned commit):

* OFL: bundling with the Studio, embedding (subsets) in PDF/PPTX and selling
  the *documents* are allowed; selling the font files by themselves is not
  (OFL §1). Every copy ships with ``OFL.txt``.
* A Modified Version (variable-font instance, rename, merge, subset made for
  redistribution) must not use a declared Reserved Font Name (OFL §3): when
  the family declares any RFN the Office build is renamed ``MX Kids <id> …``
  and keeps the OFL. Subsets embedded in a PDF/PPTX are document use.
* Apache-2.0: ships with ``LICENSE.txt`` (+ ``NOTICE`` when the upstream has
  one — recorded as a fact); modified files carry a change notice (§4b).
* Embedding follows OS/2 ``fsType``: 0 installable and 8 editable allow PDF
  and PPTX embedding; 4 preview&print allows PDF only; bit 1 (restricted) or
  bit 9 (bitmap only) refuse embedding.
* Selling fonts alone is never done, whatever the licence (operator policy).
"""
from __future__ import annotations

import json
from pathlib import Path

from mxstudio.fonts.catalog import Catalog, Finding
from mxstudio.fonts.paths import LEDGER_JSON
from mxstudio.fonts.rfn import renamed_family, rfn_conflicts

SCHEMA = "mx.fonts.licence_ledger/1"


def embedding_permission(fs_type: int) -> dict:
    """What OS/2 fsType allows for document embedding."""
    restricted = bool(fs_type & 0x0002)
    bitmap_only = bool(fs_type & 0x0200)
    preview_print = bool(fs_type & 0x0004)
    if restricted or bitmap_only:
        return {"fsType": fs_type, "pdf": False, "pptx": False, "subsetting": not fs_type & 0x0100,
                "reason": "restricted_licence_embedding" if restricted else "bitmap_embedding_only"}
    return {"fsType": fs_type, "pdf": True, "pptx": not preview_print or bool(fs_type & 0x0008),
            "subsetting": not fs_type & 0x0100,
            "reason": {0: "installable", 8: "editable"}.get(fs_type & 0x000E, "preview_and_print")}


def ledger_entry(fam: dict) -> dict:
    licence = fam["licence"]
    rfns = list(dict.fromkeys(fam.get("reserved_font_names", [])))
    embeds = [embedding_permission(int(f["fsType"])) for f in fam["files"]]
    embed_pdf = all(e["pdf"] for e in embeds)
    embed_pptx = all(e["pptx"] for e in embeds)
    ship = [fam["licence_file"]["file"]] + ([fam["notice_file"]["file"]] if fam.get("notice_file") else [])
    if licence == "OFL-1.1":
        sell_alone = {"allowed": False, "rule": "OFL §1: the Font Software may not be sold by itself"}
        modified = {"allowed": True, "keep_licence": "OFL-1.1", "rename_required": bool(rfns),
                    "renamed_family": renamed_family(fam["id"], fam["family"], rfns) if rfns else None,
                    "rule": ("OFL §3: a Modified Version may not use the Reserved Font Name(s) "
                             + ", ".join(f"«{r}»" for r in rfns)) if rfns else
                            "OFL §3/§5: modified versions stay under OFL; no RFN declared, name may be kept"}
    elif licence == "Apache-2.0":
        sell_alone = {"allowed": False, "rule": "operator policy: fonts are never sold as products"}
        modified = {"allowed": True, "keep_licence": "Apache-2.0", "rename_required": False, "renamed_family": None,
                    "rule": "Apache-2.0 §4: ship LICENSE (+NOTICE if any); modified files carry a change notice"}
    else:
        sell_alone = {"allowed": False, "rule": "licence not allowed"}
        modified = {"allowed": False, "keep_licence": licence, "rename_required": False, "renamed_family": None,
                    "rule": "licence not in the print allowlist"}
    allowed = licence in ("OFL-1.1", "Apache-2.0")
    decision = ("refuse" if not allowed or not embed_pdf else
                "bundle_embed_rename_modified_builds" if modified["rename_required"] else "bundle_embed")
    return {
        "id": fam["id"], "family": fam["family"], "licence": licence,
        "licence_file": fam["licence_file"], "notice_file": fam.get("notice_file"),
        "notice_upstream": "present" if fam.get("notice_file") else ("absent_at_pinned_commit"
                                                                      if licence == "Apache-2.0" else "n/a"),
        "reserved_font_names": rfns,
        "bundle_with_studio": {"allowed": allowed, "ship_with": ship},
        "embed_in_documents": {"pdf": embed_pdf, "pptx": embed_pptx,
                               "fsType": sorted({e["fsType"] for e in embeds}),
                               "reason": sorted({e["reason"] for e in embeds})},
        "sell_documents": {"allowed": allowed and embed_pdf},
        "sell_font_alone": sell_alone,
        "modified_build": modified,
        "decision": decision,
    }


def build_ledger(catalog: Catalog) -> dict:
    entries = [ledger_entry(fam) for fam in catalog.families]
    return {
        "schema": SCHEMA, "commit": catalog.commit,
        "counts": {"families": len(entries),
                   "decisions": {d: sum(e["decision"] == d for e in entries)
                                 for d in sorted({e["decision"] for e in entries})},
                   "rename_required": sum(e["modified_build"]["rename_required"] for e in entries)},
        "families": entries,
    }


def validate_ledger(ledger: dict, catalog: Catalog) -> list[Finding]:
    findings: list[Finding] = []
    add = lambda f, s, d: findings.append(Finding(f, s, d))  # noqa: E731
    entries = {}
    for entry in ledger.get("families", []):
        if entry.get("family") in entries:
            add("ledger_duplicate_family", entry.get("family", "?"), "")
        entries[entry.get("family")] = entry
    for fam in catalog.families:
        subject = f"{fam['id']} {fam['family']}"
        entry = entries.pop(fam["family"], None)
        if entry is None:
            add("ledger_family_missing", subject, "no licence decision for a catalog family")
            continue
        if entry.get("licence") != fam["licence"]:
            add("ledger_licence_mismatch", subject, f"{entry.get('licence')} != {fam['licence']}")
        if entry.get("licence_file", {}).get("sha256") != fam["licence_file"]["sha256"]:
            add("ledger_licence_file_mismatch", subject, "licence file sha256 differs from the catalog")
        ship = entry.get("bundle_with_studio", {}).get("ship_with", [])
        if fam["licence_file"]["file"] not in ship:
            add("ledger_licence_not_shipped", subject, f"{fam['licence_file']['file']} not in ship_with")
        rfns = fam.get("reserved_font_names", [])
        build = entry.get("modified_build", {})
        if bool(rfns) and not build.get("rename_required"):
            add("ledger_rfn_without_rename", subject, f"RFN {rfns} declared but rename not required")
        if build.get("rename_required"):
            new = build.get("renamed_family") or ""
            if not new or rfn_conflicts(new, rfns):
                add("ledger_rename_uses_rfn", subject, f"renamed family {new!r} still uses {rfns}")
        if entry.get("sell_font_alone", {}).get("allowed"):
            add("ledger_sells_font_alone", subject, "selling the font by itself is never allowed")
        expected = ledger_entry(fam)
        if entry.get("embed_in_documents") != expected["embed_in_documents"]:
            add("ledger_embedding_mismatch", subject, "embedding decision does not follow fsType")
        if entry.get("decision") != expected["decision"]:
            add("ledger_decision_mismatch", subject, f"{entry.get('decision')} != {expected['decision']}")
    for extra in sorted(entries):
        add("ledger_family_not_in_catalog", str(extra), "")
    return findings


def load_ledger(path: Path = LEDGER_JSON) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> int:
    from mxstudio.fonts.build_catalog import write_json
    from mxstudio.fonts.catalog import default_catalog
    ledger = build_ledger(default_catalog())
    problems = validate_ledger(ledger, default_catalog())
    if problems:
        raise SystemExit("\n".join(f"{p.finding}: {p.subject} {p.detail}" for p in problems))
    write_json(ledger, LEDGER_JSON)
    print(json.dumps(ledger["counts"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
