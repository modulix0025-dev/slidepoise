"""Apply / revert / idempotency / frozen files / backups / LIFO / tests rollback — on Arabic-path replicas."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from kit_helpers import ok_runner, tree_digest

from mxstudio.kit import apply as kit
from mxstudio.kit._util import inside_static, is_frozen
from mxstudio.kit.patches import PATCHES
from mxstudio.kit.patches.base import Hook, Patch, PatchError, has_markers, insert_hook, remove_hook

FROZEN = ["OrderManagement/app/utils/config.py", "OrderManagement/app/editor/deck_pdf.py",
          "OrderManagement/modulex_core/modulex_signing.py", "OrderManagement/app/static/js/ui-utils.js",
          "ModuleX_Console/execution_console/modulex_signing.py", "ModuleXOrchestrator/contrib/modulex_signing.py"]


def _code(root, pid):
    row = next(r for r in kit.plan(root)["patches"] if r["id"] == pid)
    assert row["status"] == "ready", row.get("blockers")
    return row["confirm_code"]


def _apply(root, pid, runner=ok_runner):
    return kit.apply_patch(pid, root=root, confirm=_code(root, pid), test_runner=runner)


def _frozen(root):
    return {rel: tree_digest(root).get(rel) for rel in FROZEN}


@pytest.mark.parametrize("pid", list(PATCHES))
def test_each_patch_applies_and_reverts_byte_identically(replica, pid):
    facts = replica()
    root = facts["root"]
    before = tree_digest(root)
    frozen_before = _frozen(root)
    res = _apply(root, pid)
    assert res["result"] == "applied", res
    assert res["frozen_unchanged"] and _frozen(root) == frozen_before
    modified = [f for f in res["files"] if f["action"] == "modify"]
    assert modified, "every patch has at least one hook"
    for f in modified:
        text = (root / f["project_path"]).read_text(encoding="utf-8")
        assert has_markers(text, pid)
        assert "MODULEX_MAG" in text and PATCHES[pid].flag in text
        assert Path(f["backup"]).read_bytes() and "_backup_mag_" + pid in f["backup"]
    for b in res["backup_dirs"]:
        assert not inside_static(Path(b).relative_to(root).as_posix())
        manifest = json.loads((Path(b) / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["patch"] == pid and manifest["frozen"]["unchanged"]
    assert any(f["action"] == "add" for f in res["files"])
    assert tree_digest(root) != before
    rev = kit.revert_patch(pid, root=root)
    assert rev["result"] == "reverted" and rev["byte_identical"] and rev["added_files_removed"]
    assert tree_digest(root) == before
    assert _frozen(root) == frozen_before


def test_apply_is_idempotent(replica):
    root = replica()["root"]
    assert _apply(root, "P-TEXTFIT")["result"] == "applied"
    snapshot = tree_digest(root)
    again = kit.apply_patch("P-TEXTFIT", root=root, confirm="anything", test_runner=ok_runner)
    assert again["result"] == "already_applied"
    assert tree_digest(root) == snapshot
    assert kit.revert_patch("P-TEXTFIT", root=root)["result"] == "reverted"
    assert kit.revert_patch("P-TEXTFIT", root=root)["result"] == "not_applied"


def test_reapply_after_revert_gets_a_new_backup_folder(replica):
    root = replica()["root"]
    first = _apply(root, "P-PREFLIGHT2")
    kit.revert_patch("P-PREFLIGHT2", root=root)
    second = _apply(root, "P-PREFLIGHT2")
    assert second["result"] == "applied"
    assert first["backup_dirs"] != second["backup_dirs"]
    assert second["backup_dirs"][0].endswith("_2")


def test_confirmation_is_required_and_bound_to_the_plan(replica):
    root = replica()["root"]
    before = tree_digest(root)
    res = kit.apply_patch("P-TEXTFIT", root=root, confirm="0000000000", test_runner=ok_runner)
    assert res["result"] == "refused" and res["reason"] == "confirmation_required"
    assert "confirm_code" not in res
    assert kit.apply_patch("P-TEXTFIT", root=root, test_runner=ok_runner)["reason"] == "confirmation_required"
    assert tree_digest(root) == before


def test_dry_run_writes_nothing_and_shows_the_hook(replica):
    root = replica()["root"]
    before = tree_digest(root)
    res = kit.apply_patch("P-TEXTFIT", root=root, dry_run=True)
    assert res["result"] == "dry_run"
    assert any("+    # >>> MODULEX_MAG P-TEXTFIT >>>" in d for d in res["diffs"])
    assert tree_digest(root) == before


def test_blocked_patch_never_writes(replica):
    facts = replica({"om_deck_constant"})
    before = tree_digest(facts["root"])
    res = kit.apply_patch("P-TEXTFIT", root=facts["root"], confirm="x", test_runner=ok_runner)
    assert res["result"] == "refused" and res["reason"] == "blocked"
    assert res["blockers"][0]["anchor"] == "OM.editor.deck.constants"
    assert res["blockers"][0]["found"]["MIN_DPI"] == 96
    assert tree_digest(facts["root"]) == before


def test_markers_without_a_kit_record_block(replica):
    facts = replica()
    deck = facts["om"] / "app/editor/deck.py"
    deck.write_text(deck.read_text(encoding="utf-8") + "\n# >>> MODULEX_MAG P-TEXTFIT >>>\n# <<< MODULEX_MAG P-TEXTFIT <<<\n",
                    encoding="utf-8")
    row = next(r for r in kit.plan(facts["root"])["patches"] if r["id"] == "P-TEXTFIT")
    assert row["status"] == "blocked"
    assert "markers present" in json.dumps(row["blockers"])


def test_shared_file_reverts_in_lifo_order_or_cascades(replica):
    root = replica()["root"]
    assert _apply(root, "P-SAFEZONE")["result"] == "applied"
    assert _apply(root, "P-PROOF")["result"] == "applied"  # same app/main.py, new confirm code
    pristine_main = (Path(kit.load_state()["roots"][str(root.resolve())]["patches"]["P-SAFEZONE"]["manifest"]
                          ["files"][0]["backup"])).read_bytes()
    refused = kit.revert_patch("P-SAFEZONE", root=root)
    assert refused["result"] == "refused" and refused["later"] == ["P-PROOF"]
    done = kit.revert_patch("P-SAFEZONE", root=root, cascade=True)
    assert done["result"] == "reverted" and done["cascade"][0]["patch"] == "P-PROOF"
    assert (root / "OrderManagement/app/main.py").read_bytes() == pristine_main


def test_drift_after_patch_refuses_revert(replica):
    root = replica()["root"]
    _apply(root, "P-TEXTFIT")
    deck = root / "OrderManagement/app/editor/deck.py"
    deck.write_text(deck.read_text(encoding="utf-8").replace("MAX_LINES = 30", "MAX_LINES = 31"), encoding="utf-8")
    drifted = tree_digest(root)
    res = kit.revert_patch("P-TEXTFIT", root=root)
    assert res["result"] == "refused" and res["reason"] == "drift"
    assert tree_digest(root) == drifted
    status = {r["id"]: r for r in kit.status(root)["patches"]}
    assert status["P-TEXTFIT"]["status"] == "applied_drifted"


def test_revert_by_marker_removal_when_only_our_block_differs(replica):
    root = replica()["root"]
    res = _apply(root, "P-PREFLIGHT2")
    backup = Path(res["files"][0]["backup"]) if res["files"][0]["action"] == "modify" else \
        Path(next(f for f in res["files"] if f["action"] == "modify")["backup"])
    backup.unlink()  # backup lost: the marker-removal path must still restore the exact original
    target = root / "OrderManagement/app/printing/preflight.py"
    rev = kit.revert_patch("P-PREFLIGHT2", root=root)
    assert rev["result"] == "reverted" and rev["byte_identical"]
    assert not has_markers(target.read_text(encoding="utf-8"), "P-PREFLIGHT2")


def test_failing_system_tests_roll_back(replica):
    root = replica()["root"]
    before = tree_digest(root)
    calls = []

    def runner(system_root):
        calls.append(system_root)
        return {"ran": True, "returncode": 0 if len(calls) == 1 else 1, "tail": "boom"}

    res = _apply(root, "P-TEXTFIT", runner)
    assert res["result"] == "rolled_back_tests_failed" and res["restored"]
    assert tree_digest(root) == before
    assert kit.plan(root)["patches"][0]["status"] == "ready"


def test_preexisting_test_failure_does_not_roll_back(replica):
    root = replica()["root"]
    res = _apply(root, "P-TEXTFIT", lambda _r: {"ran": True, "returncode": 1, "tail": "already red"})
    assert res["result"] == "applied"
    assert res["tests"]["baseline"]["OM"]["returncode"] == 1


def test_crlf_files_keep_crlf_and_revert_exactly(replica):
    facts = replica(crlf_deck=True)
    root = facts["root"]
    before = tree_digest(root)
    _apply(root, "P-TEXTFIT")
    data = (root / "OrderManagement/app/editor/deck.py").read_bytes()
    assert b"# >>> MODULEX_MAG P-TEXTFIT >>>\r\n" in data and b"\n" not in data.replace(b"\r\n", b"")
    kit.revert_patch("P-TEXTFIT", root=root)
    assert tree_digest(root) == before


def test_missing_vendored_lib_blocks_textfit(replica, monkeypatch, tmp_path):
    root = replica()["root"]
    monkeypatch.setenv("MXS_MXLIBS_DIR", str(tmp_path / "empty"))
    row = next(r for r in kit.plan(root)["patches"] if r["id"] == "P-TEXTFIT")
    assert row["status"] == "blocked" and "mxlibs not shipped" in json.dumps(row["blockers"])


def test_tampered_vendored_lib_blocks(replica, standin_libs):
    root = replica()["root"]
    (standin_libs / "mx_preflight2" / "__init__.py").write_text("tampered = True\n", encoding="utf-8")
    row = next(r for r in kit.plan(root)["patches"] if r["id"] == "P-PREFLIGHT2")
    assert row["status"] == "blocked" and "differs from MANIFEST.json" in json.dumps(row["blockers"])


def test_vendored_lib_is_copied_verbatim_with_its_manifest(replica, standin_libs):
    root = replica()["root"]
    _apply(root, "P-TEXTFIT")
    dst = root / "OrderManagement/app/mag_textfit/vendor/mx_textfit"
    assert (dst / "MANIFEST.json").read_bytes() == (standin_libs / "mx_textfit/MANIFEST.json").read_bytes()
    assert (dst / "__init__.py").read_bytes() == (standin_libs / "mx_textfit/__init__.py").read_bytes()


def test_frozen_paths_are_recognised_and_never_patchable(replica):
    for rel in FROZEN:
        assert is_frozen(rel), rel
    assert is_frozen("OrderManagement\\app\\utils\\config.py")
    assert not is_frozen("OrderManagement/app/editor/deck.py")
    facts = replica()
    evil = Patch("P-EVIL", "MODULEX_MAG_EVIL", "x", "x", "x", (), (Hook("OM", "app/utils/config.py", "module_end",
                                                                       'if False:\n    pass\n'),), ())
    ctx = kit.build_context(facts["root"])
    with pytest.raises(PatchError, match="frozen"):
        kit.compute_changes(evil, ctx)


def test_backup_and_payload_paths_never_inside_static():
    assert inside_static("OrderManagement/app/static/_backup_mag_P-X_20260101")
    assert inside_static("OrderManagement\\Static\\x.js")
    assert not inside_static("OrderManagement/_backup_mag_P-X_20260101/app/main.py")


def test_hook_engine_inserts_after_docstring_and_removes_exactly():
    src = b'def apply(a, b):\n    """Doc\n    string."""\n    return a + b\n\n\nX = 1\n'
    hook = Hook("OM", "f.py", "func_start:apply", 'if __import__("os").environ.get("F", "0") == "1":\n    a = -a\n')
    out = insert_hook(src, hook, "P-T", {})
    lines = out.decode().splitlines()
    assert lines[3] == "    # >>> MODULEX_MAG P-T >>>" and lines[-4] == "    return a + b"
    assert remove_hook(out, "P-T") == src
    with pytest.raises(PatchError, match="already present"):
        insert_hook(out, hook, "P-T", {})
    with pytest.raises(PatchError, match="exactly one"):
        insert_hook(src, Hook("OM", "f.py", "func_start:nope", "pass\n"), "P-T", {})


def test_hook_engine_keeps_bom_and_module_end_before_main_guard():
    src = "﻿import os\n\nif __name__ == \"__main__\":\n    print(1)\n".encode()
    out = insert_hook(src, Hook("OM", "m.py", "module_end", "pass\n"), "P-M", {})
    assert out.startswith(b"\xef\xbb\xbf")
    text = out.decode("utf-8-sig")
    assert text.index("# <<< MODULEX_MAG P-M <<<") < text.index("if __name__")
    assert remove_hook(out, "P-M") == src
