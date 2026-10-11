"""Read-only probe facts on replicas: template anatomy and code points, fonts, accounts, health, licences."""
from __future__ import annotations

import json
from types import SimpleNamespace

from kit_helpers import tree_digest

from mxstudio.kit.discover import discover
from mxstudio.kit.probe import classify_model, health, name_occurrences, probe, process_owners, typeface_visibility


def _fake_runner(responses):
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        for key, out in responses.items():
            if key in " ".join(cmd):
                if isinstance(out, Exception):
                    raise out
                return SimpleNamespace(returncode=0, stdout=out.encode("utf-8"), stderr=b"")
        return SimpleNamespace(returncode=1, stdout=b"", stderr=b"")

    run.calls = calls
    return run


RUNNER = _fake_runner({"fc-list": "Amiri\nDejaVu Sans\n", "powershell": json.dumps(
    [{"port": 8000, "pid": 10, "name": "python.exe", "exe": "C:\\x\\python.exe", "user": "PC\\operator"}])})


def test_probe_is_read_only_and_reports_template_anatomy(replica):
    facts = replica()
    before = tree_digest(facts["root"])
    res = probe(discover(facts["root"]), runner=RUNNER, http_get=lambda url: 404)
    assert tree_digest(facts["root"]) == before
    files = {f["file"]: f for f in res["templates"]["files"]}
    boy = files["الصدق مع الأرنب a5.pptx"]
    assert boy["slide_size_cm"] == [14.8, 21.0]
    assert boy["slide_count"] == 3 and boy["hidden_slides"] == [3]
    assert boy["picture_slots"] == {1: 1}
    assert boy["slides"][0]["p_sp"] >= 3 and boy["slides"][0]["rtl_paragraphs"] == 1
    assert "Blabeloo  MagdySoliman" in boy["typefaces"]  # two spaces kept
    assert 18.0 in boy["slides"][0]["sizes_pt"]


def test_name_codepoints_expose_the_lam_alef_ligature(replica):
    facts = replica()
    res = probe(discover(facts["root"]), runner=RUNNER, network=False)
    boy = next(f for f in res["templates"]["files"] if f["file"].startswith("الصدق"))
    lig = [o for o in boy["name_occurrences"] if o["lam_alef_ligature"]]
    assert len(lig) == 1
    assert lig[0]["codepoints"][0] == "U+FEF9" and lig[0]["prefix"] == "ل"
    assert lig[0]["literal_match"] is False  # OM's STEP 1 would miss it -> needs a replacements entry
    assert boy["lam_alef_ligatures"][0]["char"] == "U+FEF9"
    split = [o for o in boy["name_occurrences"] if not o["single_run"]]
    assert split and split[0]["literal_match"] is True and split[0]["runs"] == [0, 1]
    girl = next(f for f in res["templates"]["files"] if f["file"].startswith("honesty"))
    pref = [o for o in girl["name_occurrences"] if o["prefix"] == "ل"]
    assert pref and pref[0]["original"] == "لجيداء" and pref[0]["literal_match"] is True


def test_name_occurrences_negative_control():
    assert name_occurrences(["ذهب محمد إلى البحر"], "إياد") == []
    hits = name_occurrences(["وأيادي"], "إياد")
    assert hits and hits[0]["inside_longer_word"] is True  # flagged, not silently counted as the name


def test_fonts_visibility_is_exact():
    fonts = {"available": True, "families": {"Blabeloo  MagdySoliman": ["user"], "Amiri": ["machine"]}}
    rows = {r["typeface"]: r for r in typeface_visibility(["Blabeloo  MagdySoliman", "Blabeloo MagdySoliman",
                                                           "Amiri", "+mn-cs"], fonts)}
    assert rows["Blabeloo  MagdySoliman"]["installed"] and rows["Blabeloo  MagdySoliman"]["user_scope_only"]
    assert rows["Blabeloo MagdySoliman"]["installed"] is False  # one space is a different font
    assert "+mn-cs" not in rows


def test_process_owner_probe_through_injected_runner():
    res = process_owners(RUNNER)
    assert res["method"] == "powershell-cim" and res["listeners"][0]["user"] == "PC\\operator"
    assert "powershell" in RUNNER.calls[-1][0]
    fallback = _fake_runner({"powershell": RuntimeError("no ps"), "tasklist": '"Image Name","PID","User Name"\n'
                                                                             '"python.exe","42","PC\\svc_om"\n'})
    res = process_owners(fallback)
    assert res["method"] == "tasklist" and res["processes"][0]["user"] == "PC\\svc_om"


def test_health_probe_records_status_per_system():
    res = health(lambda url: 200 if url.endswith(":8000/health") else 404)
    assert res["OM"]["healthy_path"] == "/health" and res["Console"]["healthy_path"] is None

    def down(url):
        raise ConnectionError("refused")

    assert health(down)["Store"]["up"] is False


def test_model_licence_probe_flags_flux_dev_and_names_free_alternatives(replica):
    facts = replica()
    res = probe(discover(facts["root"]), runner=RUNNER, network=False)["model_licences"]
    flagged = {r["file"]: r for r in res["non_commercial"]}
    assert set(flagged) == {"flux1-dev-kontext_fp8_scaled.safetensors", "flux1-dev.safetensors"}
    assert "Qwen-Image-Edit-2511" in flagged["flux1-dev-kontext_fp8_scaled.safetensors"]["free_alternative"]
    ok = {r["file"]: r for r in res["references"] if r["commercial_use"]}
    assert set(ok) == {"qwen_image_edit_2511_fp8.safetensors", "flux1-schnell.safetensors"}
    assert "report only" in res["action"]
    assert classify_model("mystery_model.safetensors")["commercial_use"] is None


def test_editor_routes_and_qa_presence(replica):
    facts = replica()
    res = probe(discover(facts["root"]), runner=RUNNER, network=False)
    assert any(r["file"] == "app/main.py" for r in res["editor"]["api_editor_refs"])
    assert res["qa"]["qc_agent.py"] == ["execution_console/qc_agent.py"]
    assert res["health"] == {"skipped": "network disabled"}
