"""``python -m mxstudio.kit`` is non-interactive and answers JSON; the root travels in argv-free form too."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from mxstudio.proc import run_hidden

REPO = Path(__file__).resolve().parents[3]


def _cli(*args, env):
    res = run_hidden([sys.executable, "-m", "mxstudio.kit", *args], env={"PYTHONPATH": str(REPO), **env},
                     timeout=120, cwd=REPO)
    return res.returncode, json.loads(res.stdout.decode("utf-8"))


def test_cli_discover_plan_apply_revert_cycle(replica, kit_home, standin_libs):
    facts = replica()
    env = {"MXS_KIT_HOME": str(kit_home), "MXS_PROJECT_ROOT": str(facts["root"]), "MXS_MXLIBS_DIR": str(standin_libs),
           "MXS_HOME": str(kit_home.parent / "mxs_home")}
    code, found = _cli("discover", env=env)  # root from MXS_PROJECT_ROOT: no Arabic path in argv
    assert code == 0 and found["systems"]["OM"]["status"] == "found" and "المشروع" in found["root"]
    code, verified = _cli("verify", env=env)
    assert code == 0 and verified["counts"] == {"ok": len(verified["anchors"])}
    code, plan = _cli("plan", "--patch", "P-PREFLIGHT2", env=env)
    row = plan["patches"][0]
    assert code == 0 and row["status"] == "ready" and len(row["confirm_code"]) == 10
    code, refused = _cli("apply", "--patch", "P-PREFLIGHT2", "--no-tests", env=env)
    assert code == 2 and refused["reason"] == "confirmation_required"
    code, applied = _cli("apply", "--patch", "P-PREFLIGHT2", "--no-tests", "--confirm", row["confirm_code"], env=env)
    assert code == 0 and applied["result"] == "applied"
    code, status = _cli("status", env=env)
    assert {r["id"]: r["status"] for r in status["patches"]}["P-PREFLIGHT2"] == "applied"
    code, reverted = _cli("revert", "--patch", "P-PREFLIGHT2", env=env)
    assert code == 0 and reverted["byte_identical"] is True


def test_cli_blocked_patch_exits_2_with_named_blockers(replica, kit_home, standin_libs):
    facts = replica({"om_preflight_signature"})
    env = {"MXS_KIT_HOME": str(kit_home), "MXS_PROJECT_ROOT": str(facts["root"]), "MXS_MXLIBS_DIR": str(standin_libs),
           "MXS_HOME": str(kit_home.parent / "mxs_home")}
    code, res = _cli("apply", "--patch", "P-PREFLIGHT2", "--confirm", "x", "--no-tests", env=env)
    assert code == 2 and res["reason"] == "blocked"
    assert res["blockers"][0]["anchor"] == "OM.printing.preflight.run"


def test_cli_pack_build_and_import(replica, kit_home, tmp_path):
    facts = replica()
    env = {"MXS_KIT_HOME": str(kit_home), "MXS_PROJECT_ROOT": str(facts["root"]),
           "MXS_HOME": str(kit_home.parent / "mxs_home"), "MODULEX_HMAC_SECRET": "cli-pack-secret"}
    doc = {"contract": "mag/v1/m7", "schema_version": 1, "produced_by": {"app": "Studio", "version": "0.8.0"},
           "created_at": "2026-10-11T12:00:00Z", "story_key": "moon_trip",
           "roles": {"dedication": [{"font_id": "mx-amiri", "display_name_ar": "أميري", "price_tokens": 5}]}}
    (tmp_path / "doc.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    pack = tmp_path / "mag-pack-fonts.zip"
    code, _ = _cli("pack-build", "--kind", "m7", "--document", str(tmp_path / "doc.json"), "--id", "fonts-1",
                       "--out", str(pack), env=env)
    assert code == 0 and pack.is_file()
    code, imported = _cli("pack-import", "--pack", str(pack), "--system", "OM", env=env)
    assert code == 0 and imported["status"] == "candidate"
    assert (facts["om"] / "mag_candidates" / "m7").is_dir()
    code, again = _cli("pack-import", "--pack", str(pack), "--system", "OM", env={**env, "MODULEX_HMAC_SECRET": "x"})
    assert code == 2 and "signature mismatch" in again["reason"]
