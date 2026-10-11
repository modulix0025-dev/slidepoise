"""Doctor: checks report facts with a «إصلاح» per red line; fakes for Windows/registry/ports/HTTP;
a real Arabic-path round-trip through a child process; fixers never act without consent."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from mxstudio.update import payloads
from mxstudio.doctor import FIXERS, DoctorContext, checks, fixers, run_all, summary
from mxstudio.doctor.checks import child_roundtrip
from mxstudio.firstrun import office

FONTS = Path(__file__).resolve().parents[1] / "fixtures" / "fonts"
WV2 = checks.WEBVIEW2_GUID


def ok_run(cmd, env=None, timeout=None, **_):
    """Fake mxstudio.proc.run_hidden: emulates the Python child and Node for the Arabic round-trip."""
    env = env or {}
    if "--child-roundtrip" in cmd:
        old = os.environ.get("MXS_DOCTOR_RT_PATH")
        os.environ["MXS_DOCTOR_RT_PATH"] = env["MXS_DOCTOR_RT_PATH"]
        try:
            child_roundtrip()
        finally:
            if old is None:
                os.environ.pop("MXS_DOCTOR_RT_PATH")
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
    if "MXS_DOCTOR_RT_PATH" in env:  # node step
        src = Path(env["MXS_DOCTOR_RT_PATH"])
        src.with_name("رد نود.txt").write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return SimpleNamespace(returncode=0, stdout=b"v22.23.3 function", stderr=b"")


def make_ctx(tmp_path, **over) -> DoctorContext:
    app = tmp_path / "Programs" / "ModuleX Magazine Studio"
    (app / "node" / "node_modules" / "pptxgenjs").mkdir(parents=True)
    (app / "node" / "node_modules" / "jszip").mkdir(parents=True)
    (app / "node" / "node.exe").write_bytes(b"MZ")
    shutil.copytree(FONTS / "amiri", app / "fonts" / "amiri")
    (app / "offline" / "shapes" / "iconify" / "noto").mkdir(parents=True)
    (app / "offline" / "shapes" / "iconify" / "noto" / "icons.json").write_text('{"prefix": "noto"}', encoding="utf-8")
    ws = tmp_path / "المشروع" / "ModuleX_MagazineStudio_Data"
    ws.mkdir(parents=True)
    home = tmp_path / "home"
    home.mkdir()
    registry = {
        ("HKCR", r"PowerPoint.Application\CurVer"): "PowerPoint.Application.16",
        ("HKLM", rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{WV2}"): "130.0.2849.80",
    }
    settings = {"digits": "arabic_indic", "providers": {
        "text_vision": {"kind": "openai_compatible", "base_url": "http://gpu.local:8000/v1", "enabled": True},
        "image": {"kind": "comfyui", "base_url": "http://gpu.local:8188", "enabled": True}}}
    values = dict(settings=settings, workspace=ws, home=home, app_dir=app, platform="win32", frozen=False, run=ok_run,
                  connect=lambda host, port, timeout: True, http_get=lambda url, timeout: 200,
                  reg_read=lambda hive, key, value="": registry.get((hive, key)) if value in ("", "pv") else None,
                  disk_free=lambda path: 200 * 1024**3, which=lambda name: None)
    values.update(over)
    return DoctorContext(**values)


def by_id(results):
    return {r["id"]: r for r in results}


def test_all_green_with_fakes(tmp_path):
    results = run_all(make_ctx(tmp_path))
    assert [r["id"] for r in results] == checks.check_ids()
    bad = [r for r in results if not r["ok"]]
    assert bad == [], bad
    assert summary(results) == {"ok": True, "red": [], "warn": [], "count": len(results)}
    for r in results:
        assert set(r) == {"id", "ok", "ar", "en", "fix_id", "level", "details"}
        assert r["ar"] and r["en"]
    assert by_id(results)["office"]["details"]["engine"] == "powerpoint"
    assert by_id(results)["arabic_path"]["details"]["steps"] == {"write_read": True, "child_python": True,
                                                                 "child_node": True}


def test_every_red_line_has_an_existing_fixer(tmp_path):
    ctx = make_ctx(tmp_path, reg_read=lambda *a, **k: None, connect=lambda *a: False, http_get=lambda *a: 0,
                   disk_free=lambda p: 10 * 1024**2, run=lambda *a, **k: SimpleNamespace(returncode=1, stdout=b"", stderr=b"x"))
    shutil.rmtree(ctx.app_dir)
    shutil.rmtree(ctx.workspace)
    results = run_all(ctx)
    red = [r for r in results if r["level"] == "red"]
    assert {r["id"] for r in red} >= {"node", "office", "fonts", "webview2", "providers", "system_om", "system_console",
                                      "system_store", "workspace", "disk", "arabic_path"}
    for r in red:
        assert r["ok"] is False and r["fix_id"] in FIXERS, r
    assert by_id(results)["office"]["fix_id"] == "install_libreoffice"
    assert by_id(results)["webview2"]["fix_id"] == "install_webview2"


def test_arabic_path_negative_control(tmp_path):
    def broken_child(cmd, env=None, **_):
        if "--child-roundtrip" in cmd:  # child sees a mangled path: writes nothing where expected
            return SimpleNamespace(returncode=2, stdout=b"", stderr=b"FileNotFoundError")
        return ok_run(cmd, env=env)
    ctx = make_ctx(tmp_path, run=broken_child)
    result = checks.check_arabic_path(ctx)
    assert result.ok is False and result.fix_id == "arabic_path_help"
    assert result.details["steps"]["child_python"] is False
    assert not list(ctx.workspace.glob(".doctor/مسار_عربي_*"))  # the probe folder is cleaned up either way


def test_arabic_path_real_child_process(tmp_path):
    """The real thing: mxstudio.proc.run_hidden → python -m mxstudio.doctor --child-roundtrip, path in env."""
    from mxstudio import proc
    ctx = make_ctx(tmp_path, run=proc.run_hidden, platform=os.sys.platform,
                   which=shutil.which)
    shutil.rmtree(ctx.app_dir / "node")  # use system node if any; otherwise the node step is not run
    result = checks.check_arabic_path(ctx)
    assert result.ok, result.details
    assert result.details["steps"]["child_python"] is True
    assert not list(ctx.workspace.glob(".doctor/مسار_عربي_*"))


def test_office_engine_detection(tmp_path):
    ctx = make_ctx(tmp_path, reg_read=lambda *a, **k: None)
    assert checks.check_office(ctx).fix_id == "install_libreoffice"
    soffice = office.libreoffice_target(ctx) / "PFiles" / "LibreOffice" / "program" / "soffice.exe"
    soffice.parent.mkdir(parents=True)
    soffice.write_bytes(b"MZ")
    result = checks.check_office(ctx)
    assert result.ok and result.details["engine"] == "libreoffice" and result.details["soffice"] == str(soffice)


def test_operator_systems_are_probed_by_port(tmp_path):
    seen = []

    def connect(host, port, timeout):
        seen.append((host, port))
        return port == 6060
    results = by_id(run_all(make_ctx(tmp_path, connect=connect), only=["system_om", "system_console", "system_store"]))
    assert sorted(seen) == [("127.0.0.1", 6060), ("127.0.0.1", 8000), ("127.0.0.1", 8200)]
    assert results["system_console"]["ok"] and not results["system_om"]["ok"] and not results["system_store"]["ok"]
    assert results["system_om"]["fix_id"] == "show_system_help"


def test_providers_none_enabled_is_a_warning_not_red(tmp_path):
    ctx = make_ctx(tmp_path, settings={"providers": {"x": {"enabled": False}}})
    r = checks.check_providers(ctx)
    assert r.ok and r.level == "warn"
    probes = []
    ctx = make_ctx(tmp_path / "b", http_get=lambda url, t: probes.append(url) or 503)
    r = checks.check_providers(ctx)
    assert not r.ok and r.fix_id == "open_providers"
    assert sorted(probes) == ["http://gpu.local:8000/v1/models", "http://gpu.local:8188/system_stats"]


def test_workspace_inside_program_dir_is_red_when_installed(tmp_path):
    ctx = make_ctx(tmp_path, frozen=True)
    ctx.workspace = ctx.app_dir / "data"
    ctx.workspace.mkdir()
    r = checks.check_workspace(ctx)
    assert not r.ok and r.fix_id == "create_workspace"


@pytest.mark.parametrize("free,level", [(10 * 1024**3, "ok"), (3 * 1024**3, "warn"), (100 * 1024**2, "red")])
def test_disk_thresholds(tmp_path, free, level):
    assert checks.check_disk(make_ctx(tmp_path, disk_free=lambda p: free)).level == level


def test_fonts_without_arabic_coverage_is_red(tmp_path):
    ctx = make_ctx(tmp_path)
    shutil.rmtree(ctx.app_dir / "fonts")
    (ctx.app_dir / "fonts").mkdir()
    (ctx.app_dir / "fonts" / "broken.ttf").write_bytes(b"not a font")
    r = checks.check_fonts(ctx)
    assert not r.ok and r.fix_id == "fetch_fonts"


def test_webview2_skipped_off_windows(tmp_path):
    assert checks.check_webview2(make_ctx(tmp_path, platform="linux")).level == "skip"


def test_crashing_check_becomes_a_red_line(tmp_path, monkeypatch):
    def boom(ctx):
        raise RuntimeError("x")
    monkeypatch.setattr(checks, "CHECKS", [boom, *checks.CHECKS[1:]])
    r = run_all(make_ctx(tmp_path), only=["python"])[0]
    assert r["id"] == "python" and not r["ok"] and r["fix_id"] in FIXERS


def test_cli_writes_json_report(tmp_path, monkeypatch):
    from mxstudio import doctor
    monkeypatch.setenv("MXS_HOME", str(tmp_path / "h"))
    monkeypatch.setenv("MXS_WORKSPACE", str(tmp_path / "مساحة"))
    out = tmp_path / "تقرير" / "doctor.json"
    code = doctor.main(["--json", "--only", "python,disk,pypdfium2", "--out", str(out)])
    report = json.loads(out.read_text(encoding="utf-8"))
    assert [c["id"] for c in report["checks"]] == ["python", "pypdfium2", "disk"]
    assert code == (0 if report["summary"]["ok"] else 1)


# ---------------------------------------------------------------- fixers
def test_fixer_create_workspace(tmp_path):
    ctx = make_ctx(tmp_path)
    shutil.rmtree(ctx.workspace)
    assert fixers.run_fix("create_workspace", ctx)["ok"]
    assert (ctx.workspace / "stories").is_dir() and checks.check_workspace(ctx).ok


def _lo_manifest(monkeypatch, sha="TO-PIN", size=None):
    """The real downloads.json with the LibreOffice entry set to ``sha`` (TO-PIN = the unpinned state)."""
    import copy
    real = payloads.load()
    data = copy.deepcopy(real)
    data["entries"]["libreoffice_msi"].update(sha256=sha, size=size)
    if sha == "TO-PIN":
        data["entries"]["libreoffice_msi"]["version"] = "TO-PIN"
    monkeypatch.setattr(payloads, "load", lambda path=None: data)
    return data


def test_fixer_libreoffice_refuses_unpinned_download(tmp_path, monkeypatch):
    _lo_manifest(monkeypatch)
    ctx = make_ctx(tmp_path, reg_read=lambda *a, **k: None)
    result = fixers.run_fix("install_libreoffice", ctx)
    assert result["ok"] is False and result["code"] == "unpinned" and "TO-PIN" in result["ar"]


def _offline_msi(ctx, data=b"msi", monkeypatch=None):
    import hashlib
    if monkeypatch is not None:  # pin the entry to these bytes, as a pinned Full build would
        _lo_manifest(monkeypatch, hashlib.sha256(data).hexdigest(), len(data))
    msi = ctx.app_dir / "offline" / "libreoffice" / "LibreOffice_Win_x86-64.msi"
    msi.parent.mkdir(parents=True)
    msi.write_bytes(data)
    record = {"entries": {"libreoffice_msi": {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}}}
    (ctx.app_dir / "offline" / "offline_manifest.json").write_text(json.dumps(record), encoding="utf-8")
    return msi


def test_fixer_libreoffice_admin_extract_without_admin(tmp_path, monkeypatch):
    calls = []

    def run(cmd, env=None, timeout=None, **_):
        calls.append(cmd)
        target = Path(next(p for p in cmd if p.startswith("TARGETDIR=")).split("=", 1)[1])
        (target / "PFiles" / "LibreOffice" / "program").mkdir(parents=True)
        (target / "PFiles" / "LibreOffice" / "program" / "soffice.exe").write_bytes(b"MZ")
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
    ctx = make_ctx(tmp_path, reg_read=lambda *a, **k: None, run=run)
    msi = _offline_msi(ctx, monkeypatch=monkeypatch)
    result = fixers.run_fix("install_libreoffice", ctx)
    assert result["ok"] and result["method"] == "msi_admin_extract"
    assert calls[0][:4] == ["msiexec", "/a", str(msi), "/qn"]
    assert checks.check_office(ctx).ok


def test_fixer_libreoffice_asks_before_uac_and_elevates_only_with_consent(tmp_path, monkeypatch):
    ctx = make_ctx(tmp_path, reg_read=lambda *a, **k: None,
                   run=lambda *a, **k: SimpleNamespace(returncode=1603, stdout=b"", stderr=b""))
    _offline_msi(ctx, monkeypatch=monkeypatch)
    elevated = []
    result = office.install_libreoffice(ctx, elevate=elevated.append)
    assert result["ok"] is False and result["needs_consent"] and result["consent_kind"] == "uac"
    assert "UAC" in result["ar"] and "مدير" in result["ar"] and elevated == []
    soffice = tmp_path / "pf" / "soffice.exe"

    def elevate(cmd):
        elevated.append(cmd)
        soffice.parent.mkdir(parents=True)
        soffice.write_bytes(b"MZ")
        return 0
    ctx.which = lambda name: str(soffice) if soffice.exists() and name == "soffice" else None
    result = office.install_libreoffice(ctx, consent_elevation=True, elevate=elevate)
    assert result["ok"] and result["method"] == "msi_per_machine"
    assert elevated[-1][:2] == ["msiexec", "/i"] and "ALLUSERS=1" in elevated[-1]


def test_fixer_webview2_refuses_unsigned_bootstrapper(tmp_path, server):
    server.add("https://go.microsoft.com/fwlink/p/?LinkId=2124703", b"not signed")
    ran = []

    def run(cmd, env=None, timeout=None, **_):
        ran.append(cmd)
        return SimpleNamespace(returncode=3 if cmd[0] == "powershell.exe" else 0, stdout=b"", stderr=b"")
    ctx = make_ctx(tmp_path, run=run, transport=server)
    result = fixers.run_fix("install_webview2", ctx)
    assert result["ok"] is False and "مايكروسوفت" in result["ar"]
    assert len(ran) == 1 and ran[0][0] == "powershell.exe"  # the bootstrapper itself never ran
    assert not any("MicrosoftEdgeWebview2Setup" in part for part in ran[0])  # path travels in env, not argv


def test_instruction_fixers_never_claim_success(tmp_path):
    ctx = make_ctx(tmp_path)
    for fix_id in ("show_system_help", "arabic_path_help", "reinstall_app", "free_disk", "open_providers"):
        result = fixers.run_fix(fix_id, ctx)
        assert result["ok"] is False and result["ar"] and result["en"]
    assert fixers.run_fix("nope", ctx)["ok"] is False
