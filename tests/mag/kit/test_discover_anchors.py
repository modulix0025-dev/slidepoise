"""Discovery by marker files and anchor verification on Arabic-path replicas — incl. negative controls."""
from __future__ import annotations

import pytest
from kit_helpers import tree_digest

from mxstudio.kit.anchors import by_id, extract_def, verify
from mxstudio.kit.apply import plan
from mxstudio.kit.discover import discover


def test_discover_finds_every_system_under_arabic_root(replica):
    facts = replica()
    found = discover(facts["root"])
    assert "المشروع" in found["root"]
    assert {k: v["status"] for k, v in found["systems"].items()} == {
        "OM": "found", "Console": "found", "Store": "found", "Orchestrator": "found"}
    assert found["systems"]["OM"]["run_tests_bat"] and found["systems"]["Console"]["run_tests_bat"]
    names = {c["path"] for c in found["contract_copies"]}
    assert "OrderManagement/modulex_core/modulex_signing.py" in names
    assert "ModuleX_Console/execution_console/services/pptx_to_pdf.py" in names


def test_discover_partial_and_absent(replica):
    facts = replica()
    (facts["om"] / "app" / "editor" / "deck.py").unlink()
    found = discover(facts["root"])
    assert found["systems"]["OM"]["status"] == "partial"
    assert found["systems"]["OM"]["markers"]["app/editor/deck.py"] is False
    assert discover(facts["root"] / "nowhere")["systems"]["OM"]["status"] == "absent"


def test_all_anchors_verify_on_a_faithful_replica(replica):
    facts = replica()
    res = verify(discover(facts["root"]))
    bad = [a for a in res["anchors"] if a["status"] != "ok"]
    assert bad == []
    anchors = by_id(res)
    assert anchors["OM.app_object"]["extra"]["var"] == "app"
    assert anchors["Console.app_object"]["file"] == "execution_console/server.py"
    assert anchors["Console.story_contracts"]["extra"]["approvals_log_present"] is True


def test_extract_def_is_line_ending_and_trailing_space_insensitive():
    src = "def f(a):\r\n    return a   \r\n\r\nX = 1\r\n"
    assert extract_def(src, "f") == "def f(a):\n    return a"
    assert extract_def(src, "g") is None


MUTATION_EXPECTATIONS = [
    ("om_replace_in_paragraph_body", "OM.story_engine.replace_in_paragraph", "mismatch", {"P-RECEIVERS": "ready"}),
    ("om_generate_story_signature", "OM.story_engine.generate_story", "mismatch", {}),
    ("om_deck_constant", "OM.editor.deck.constants", "mismatch", {"P-TEXTFIT": "blocked"}),
    ("om_deck_apply_signature", "OM.editor.deck.signatures", "mismatch",
     {"P-TEXTFIT": "blocked", "P-SAFEZONE": "blocked", "P-PREVIEW": "blocked", "P-PROOF": "blocked"}),
    ("om_preflight_signature", "OM.printing.preflight.run", "mismatch", {"P-PREFLIGHT2": "blocked"}),
    ("console_deck_picture_slots", "Console.magazine_pptx.deck_picture_slots", "mismatch", {}),
    ("om_two_apps", "OM.app_object", "mismatch",
     {"P-SAFEZONE": "blocked", "P-PREVIEW": "blocked", "P-PROOF": "blocked", "P-RECEIVERS": "blocked",
      "P-TEXTFIT": "ready"}),
    ("om_signing_behaviour", "OM.signing.sha", "operator_updated", {"P-RECEIVERS": "blocked"}),
]


@pytest.mark.parametrize("mutation,anchor_id,status,patch_status", MUTATION_EXPECTATIONS)
def test_mutated_anchor_is_reported_and_blocks_its_patches(replica, mutation, anchor_id, status, patch_status):
    facts = replica({mutation})
    before = tree_digest(facts["root"])
    anchors = by_id(verify(discover(facts["root"])))
    assert anchors[anchor_id]["status"] == status
    others = [a for a, v in anchors.items() if v["status"] != "ok" and a != anchor_id]
    assert others == []
    rows = {r["id"]: r for r in plan(facts["root"])["patches"]}
    for pid, want in patch_status.items():
        assert rows[pid]["status"] == want, (pid, rows[pid].get("blockers"))
        if want == "blocked":
            assert any(b.get("anchor") == anchor_id for b in rows[pid]["blockers"])
            assert "confirm_code" not in rows[pid]
    assert tree_digest(facts["root"]) == before  # verification and planning never write


def test_verbatim_mismatch_records_a_unified_diff(replica):
    facts = replica({"om_replace_in_paragraph_body"})
    a = by_id(verify(discover(facts["root"])))["OM.story_engine.replace_in_paragraph"]
    assert "-    simple_found = False" in a["diff"] and "+    simple_found = None" in a["diff"]


def test_operator_updated_contract_with_same_behaviour_is_accepted_and_reported(replica):
    facts = replica({"console_pptx_to_pdf_comment"})
    a = by_id(verify(discover(facts["root"])))["Console.pptx_to_pdf.sha"]
    assert a["status"] == "operator_updated"
    assert a["extra"]["behaviour"]["verdict"] == "same_pdf_stats"
    assert a["extra"]["behaviour"]["known_answers_pass"] == 5


def test_operator_updated_contract_with_different_behaviour_is_flagged(replica):
    facts = replica({"console_pptx_to_pdf_behaviour"})
    a = by_id(verify(discover(facts["root"])))["Console.pptx_to_pdf.sha"]
    assert a["status"] == "operator_updated"
    assert a["extra"]["behaviour"]["verdict"] == "DIFFERENT_PDF_STATS"


def test_signing_drift_runs_the_five_vectors(replica):
    facts = replica({"om_signing_behaviour"})
    a = by_id(verify(discover(facts["root"])))["OM.signing.sha"]
    assert a["extra"]["behaviour"]["vectors_pass"] == 0
    assert a["extra"]["behaviour"]["verdict"] == "DIFFERENT_SIGNING"


def test_app_file_override_resolves_two_app_modules(replica):
    facts = replica({"om_two_apps"})
    found = discover(facts["root"])
    anchors = by_id(verify(found, overrides={"app_files": {"OM": "app/main.py"}}))
    assert anchors["OM.app_object"]["status"] == "ok"
    assert anchors["OM.app_object"]["file"] == "app/main.py"
