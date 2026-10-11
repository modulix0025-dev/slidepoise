"""On-Device Proof Runner (LibreOffice stands in for PowerPoint here) and the redacted device report."""
from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from kit_helpers import tree_digest

from mxstudio.kit import _keys
from mxstudio.kit._util import log_event
from mxstudio.kit.proofs import run_proofs, verify_report
from mxstudio.kit.report import build_report, redact


def test_proofs_with_libreoffice_and_a_real_generate_story_dry_run(replica, tmp_path):
    if not shutil.which("soffice"):
        pytest.skip("LibreOffice is required for the export proof")
    facts = replica()
    before = tree_digest(facts["root"])
    res = run_proofs(facts["root"], engines="soffice", out_dir=tmp_path / "proofs")
    steps = res["report"]["steps"]
    assert steps["export"]["templates"] == 2
    exp = next(r for r in steps["export"]["results"] if r["template"].startswith("الصدق"))
    assert exp["status"] == "exported", exp
    assert exp["engine"] == "soffice" and exp["has_text"] and exp["font_objects"] > 0
    assert exp["picture_slots"] == {"1": 1} or exp["picture_slots"] == {1: 1}
    assert any(f["id"] == "typeface_not_in_pdf" and "Blabeloo  MagdySoliman" in f["typefaces"]
               for f in exp["findings"])
    assert steps["export"]["templates_untouched"]
    story = steps["generate_story"]
    assert story["status"] == "ran" and story["templates_untouched"], story
    assert story["analysis"][0]["child_name_hits"] >= 2
    # the lam-alef ligature form of the name survives OM's two steps: a real finding, not a guess
    assert any(f["id"] == "base_name_left_after_generate" for f in story["findings"])
    assert tree_digest(facts["root"]) == before
    assert verify_report(Path(res["dir"]))


def test_proof_signature_negative_control(tmp_path, kit_home):
    body = json.dumps({"kind": "mag_device_proofs", "x": 1}).encode()
    sig = _keys.sign(body)
    assert _keys.verify(body, sig)
    assert not _keys.verify(body.replace(b"1", b"2"), sig)
    other = dict(sig, public_key=_keys.public_hex(__import__(
        "cryptography.hazmat.primitives.asymmetric.ed25519", fromlist=["x"]).Ed25519PrivateKey.generate()))
    assert not _keys.verify(body, other)
    assert _keys.sign(body)["public_key"] == sig["public_key"]  # one persistent key per user


def test_export_failure_is_recorded_by_name(replica, tmp_path):
    facts = replica()

    def runner(cmd, **kw):
        if "mxstudio.kit._export_child" in cmd:
            out = {"ok": False, "error": "no converter could turn the deck into a text-bearing PDF",
                   "attempts": [{"engine": "powerpoint", "error": "not registered"}]}
            return SimpleNamespace(returncode=2, stdout=json.dumps(out).encode(), stderr=b"")
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    res = run_proofs(facts["root"], runner=runner, limit=1, run_story=False, out_dir=tmp_path / "p")
    row = res["report"]["steps"]["export"]["results"][0]
    assert row["status"] == "failed" and row["attempts"][0]["engine"] == "powerpoint"
    assert res["report"]["steps"]["preflight_v2"]["status"] == "skipped"


def test_redaction_rules():
    text = ("اياد - الصدق مع الأرنب (AR) [A5] — ModuleX.pptx order_83178d43-aaaa-bbbb B7F49373 "
            "83178d43-1111-2222-3333-444455556666 a.b@kidx.com 01012345678 sha 2920eb32048e2866")
    out = redact(text, ("sekret-value",))
    for gone in ("اياد", "order_83178d43", "B7F49373", "83178d43-1111", "a.b@kidx.com", "01012345678"):
        assert gone not in out, gone
    assert "<child> - الصدق مع الأرنب (AR) [A5]" in out and "2920eb32048e2866" in out


def test_device_report_has_no_secrets_and_no_customer_data(replica, tmp_path, monkeypatch):
    facts = replica()
    secret = "sekret-value-xyz-123"
    monkeypatch.setenv("MODULEX_HMAC_SECRET", secret)
    log_event("planted", note=f"{secret} اياد - الصدق مع الأرنب (AR) [A5].pptx order_83178d43-1111 B7F49373")
    runner = lambda cmd, **kw: SimpleNamespace(returncode=1, stdout=b"", stderr=b"")
    res = build_report(facts["root"], out_dir=tmp_path / "out",
                       probe_kwargs={"network": False, "runner": runner})
    path = Path(res["path"])
    assert path.name.startswith("MAG_DEVICE_REPORT_") and path.suffix == ".zip"
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        assert {"discover.json", "anchors.json", "probe.json", "patches.json", "README.txt",
                "logs/kit.log.jsonl"} <= names
        blob = "\n".join(z.read(n).decode("utf-8", "replace") for n in names)
    for forbidden in (secret, "اياد - الصدق", "order_83178d43", "B7F49373"):
        assert forbidden not in blob, forbidden
    assert "الصدق مع الأرنب" in blob  # story names are not customer data
    anchors = json.loads(zipfile.ZipFile(path).read("anchors.json"))
    assert anchors["counts"] == {"ok": len(anchors["anchors"])}


def test_report_refuses_when_a_secret_survives(replica, tmp_path, monkeypatch):
    """Negative control: a secret shorter than the redaction floor is caught by the final scan."""
    facts = replica()
    monkeypatch.setattr("mxstudio.kit.report.redact", lambda text, secrets=(): text)
    log_event("planted", note="the-secret-value")
    with pytest.raises(RuntimeError, match="secret survived"):
        build_report(facts["root"], out_dir=tmp_path / "o", include_probe=False, extra_secrets=("the-secret-value",))
