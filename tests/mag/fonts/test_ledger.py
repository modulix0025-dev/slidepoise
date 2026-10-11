"""Licence ledger: one decision per family; OFL RFN ⇒ rename for modified builds; fonts never sold alone."""
from __future__ import annotations

import copy

from mxstudio.fonts.ledger import build_ledger, embedding_permission, validate_ledger


def test_committed_ledger_matches_catalog(committed, catalog):
    ledger = committed["font_license_ledger"]
    assert validate_ledger(ledger, catalog) == []
    assert ledger == build_ledger(catalog)  # regenerated output is byte-for-byte what is committed
    assert ledger["counts"]["families"] == 214
    assert ledger["counts"]["rename_required"] == 83


def test_decisions_follow_the_licences(committed):
    by = {e["family"]: e for e in committed["font_license_ledger"]["families"]}
    assert by["Lexend"]["modified_build"]["rename_required"] and by["Lexend"]["modified_build"]["renamed_family"] == "MX Kids F056"
    assert by["Amiri"]["decision"] == "bundle_embed" and not by["Amiri"]["modified_build"]["rename_required"]
    assert by["Chewy"]["licence"] == "Apache-2.0" and by["Chewy"]["bundle_with_studio"]["ship_with"] == ["LICENSE.txt"]
    assert by["Chewy"]["notice_upstream"] == "absent_at_pinned_commit"
    assert by["Frijole"]["embed_in_documents"] == {"pdf": True, "pptx": True, "fsType": [8], "reason": ["editable"]}
    assert all(not e["sell_font_alone"]["allowed"] for e in by.values())
    assert all(e["sell_documents"]["allowed"] for e in by.values())


def test_embedding_permission_reads_fstype():
    assert embedding_permission(0)["pptx"] and embedding_permission(8)["pptx"]
    assert embedding_permission(4) == {"fsType": 4, "pdf": True, "pptx": False, "subsetting": True,
                                       "reason": "preview_and_print"}
    assert not embedding_permission(2)["pdf"]
    assert not embedding_permission(0x0200)["pdf"]


def test_negative_control_ledger_missing_a_family_fails(committed, catalog):
    ledger = copy.deepcopy(committed["font_license_ledger"])
    ledger["families"] = [e for e in ledger["families"] if e["family"] != "Tajawal"]
    findings = validate_ledger(ledger, catalog)
    assert [(f.finding, f.subject) for f in findings] == [("ledger_family_missing", "F028 Tajawal")]


def test_negative_control_ledger_rules_can_fail(committed, catalog):
    ledger = copy.deepcopy(committed["font_license_ledger"])
    by = {e["family"]: e for e in ledger["families"]}
    by["Lexend"]["modified_build"]["rename_required"] = False
    by["Reem Kufi"]["modified_build"]["renamed_family"] = "MX Kids Josefin Sans"
    by["Nunito"]["sell_font_alone"]["allowed"] = True
    by["Frijole"]["embed_in_documents"]["pptx"] = False
    by["Chewy"]["bundle_with_studio"]["ship_with"] = []
    found = {f.finding for f in validate_ledger(ledger, catalog)}
    assert {"ledger_rfn_without_rename", "ledger_rename_uses_rfn", "ledger_sells_font_alone",
            "ledger_embedding_mismatch", "ledger_licence_not_shipped"} <= found
