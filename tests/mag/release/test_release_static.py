"""Static release rules: ASCII-only scripts, quoted start titles, no js_api, windowed exes only,
no forbidden components, children only via mxstudio.proc, and the release workflow's shape."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
INSTALLER = ROOT / "installer"
OWNED_PACKAGES = [ROOT / "mxstudio" / p for p in ("update", "doctor", "firstrun")]
WORKFLOW = ROOT / ".github" / "workflows" / "mag-release.yml"
SCRIPT_SUFFIXES = {".bat", ".cmd", ".ps1", ".wsb"}


def _scripts():
    return sorted(p for p in INSTALLER.rglob("*") if p.suffix.lower() in SCRIPT_SUFFIXES)


def test_there_are_scripts_to_check():
    names = {p.name for p in _scripts()}
    assert {"build_windows.ps1", "MagazineStudio.wsb", "sandbox_logon.cmd", "sandbox_proof.ps1",
            "standard_user_proof.ps1"} <= names


@pytest.mark.parametrize("path", _scripts(), ids=lambda p: p.name)
def test_scripts_are_ascii_only(path):
    data = path.read_bytes()
    bad = [i for i, b in enumerate(data) if b > 0x7F]
    assert not bad, f"{path.name}: non-ASCII byte at offset {bad[0]}"


def test_ascii_check_negative_control(tmp_path):
    sample = tmp_path / "x.cmd"
    sample.write_text('echo "المشروع"', encoding="utf-8")
    assert any(b > 0x7F for b in sample.read_bytes())


def test_cmd_files_use_crlf_and_quoted_start_titles():
    for path in _scripts():
        if path.suffix.lower() not in (".bat", ".cmd"):
            continue
        data = path.read_bytes()
        assert b"\n" not in data.replace(b"\r\n", b""), f"{path.name} must use CRLF"
        for line in data.decode("ascii").splitlines():
            if re.match(r"\s*start\b", line, re.IGNORECASE):
                assert re.match(r'\s*start\s+"[^"]*"', line, re.IGNORECASE), f"unquoted start title: {line}"


def test_no_js_api_anywhere_in_the_app():
    offenders = []
    for path in [*(ROOT / "mxstudio").rglob("*.py"), *INSTALLER.rglob("*.py"), *INSTALLER.rglob("*.spec")]:
        if re.search(r"\bjs_api\s*=", path.read_text(encoding="utf-8")):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_pyinstaller_spec_builds_two_windowed_exes_without_forbidden_parts():
    spec = (INSTALLER / "pyinstaller" / "MagazineStudio.spec").read_text(encoding="utf-8")
    assert "console=False" in spec and "console=True" not in spec
    assert 'name=APP_NAME' in spec and 'name="mxstudio-cli"' in spec and 'APP_NAME = "ModuleX Magazine Studio"' in spec
    assert "COLLECT(" in spec and "onefile" not in spec.lower()
    assert '("X utf8", None, "OPTION")' in spec
    assert '"pdf2image"' in spec  # Poppler wrapper excluded; pypdfium2 rasterises
    reqs = (INSTALLER / "pyinstaller" / "requirements-windows.txt").read_text(encoding="utf-8").lower()
    pins = [l.split("==")[0] for l in reqs.splitlines() if l and not l.startswith("#")]
    for needed in ("pyinstaller", "pywebview", "opencv-python-headless", "pillow", "numpy", "python-pptx", "lxml",
                   "uharfbuzz", "fonttools", "pypdf", "pikepdf", "pypdfium2", "coloraide", "pyclipper", "vtracer"):
        assert needed in pins, needed
    assert all("==" in l for l in reqs.splitlines() if l and not l.startswith("#"))
    policy = json.loads((ROOT / "catalog" / "licence_policy.json").read_text(encoding="utf-8"))
    banned = [pat for comp in policy["banned_components"] for pat in comp["patterns"]]
    for pattern in banned:
        assert pattern not in spec.lower() and pattern not in reqs, pattern
    for pattern in ("poppler", "pdf2image"):
        assert not any(pattern in pin for pin in pins), pattern


def test_owned_packages_start_children_only_through_proc():
    for package in OWNED_PACKAGES:
        for path in package.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            assert not re.search(r"^\s*(import subprocess|from subprocess\b)", text, re.MULTILINE), path
            assert "os.system(" not in text and "os.popen(" not in text and "Popen(" not in text, path


def test_entry_points_dispatch_and_gui_defaults_to_open():
    import importlib.util
    import sys
    here = INSTALLER / "pyinstaller"
    sys.path.insert(0, str(here))
    try:
        spec = importlib.util.spec_from_file_location("entry_cli", here / "entry_cli.py")
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        assert set(cli.OWN) == {"doctor", "update", "firstrun"}
        gui_src = (here / "entry_gui.py").read_text(encoding="utf-8")
        assert 'argv = ["open"]' in gui_src and 'argv = ["shutdown"]' in gui_src
    finally:
        sys.path.remove(str(here))


def test_wsb_maps_folders_and_runs_logon_command():
    wsb = (INSTALLER / "windows_sandbox" / "MagazineStudio.wsb").read_text(encoding="ascii")
    assert "<LogonCommand>" in wsb and "sandbox_logon.cmd" in wsb
    assert "<ReadOnly>true</ReadOnly>" in wsb and "<ReadOnly>false</ReadOnly>" in wsb
    proof = (INSTALLER / "windows_sandbox" / "sandbox_proof.ps1").read_text(encoding="ascii")
    assert '"/S"' in proof and "uninstall.exe" in proof and "keep-me.txt" in proof and "doctor" in proof


# ---------------------------------------------------------------- workflow
def _jobs(path: Path) -> dict[str, str]:
    """Split a workflow into {job id: job text} without needing PyYAML (2-space job keys under `jobs:`)."""
    text = path.read_text(encoding="utf-8")
    body = text.split("\njobs:\n", 1)[1]
    jobs: dict[str, str] = {}
    current = None
    for line in body.splitlines():
        match = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if match:
            current = match.group(1)
            jobs[current] = ""
        elif current:
            jobs[current] += line + "\n"
    return jobs


@pytest.fixture(scope="module")
def jobs():
    return _jobs(WORKFLOW)


def test_release_workflow_jobs_and_runners(jobs):
    assert set(jobs) >= {"version", "tests", "build-app", "offline-payload", "installers", "smoke-windows",
                         "standard-user-proof", "release"}
    assert "runs-on: windows-latest" in jobs["build-app"] and "build_windows.ps1" in jobs["build-app"]
    assert "runs-on: ubuntu-latest" in jobs["installers"]
    assert "runs-on: windows-latest" in jobs["smoke-windows"]
    assert re.search(r"needs: \[version, build-app, offline-payload\]", jobs["installers"])
    assert re.search(r"needs: \[version, installers, smoke-windows\]", jobs["release"])
    assert "apt-get install -y nsis" in jobs["installers"] and "-DFLAVOUR=full" in jobs["installers"]
    assert "sandbox_proof.ps1" in jobs["smoke-windows"] and "-Ci" in jobs["smoke-windows"]
    assert "standard_user_proof.ps1" in jobs["standard-user-proof"]


def test_release_publishes_sums_stable_names_and_signed_manifest(jobs):
    release = jobs["release"]
    assert "SHA256SUMS" in release
    assert "ModuleX-MagazineStudio-Setup.exe" in release and "ModuleX-MagazineStudio-Setup-Full.exe" in release
    assert "mxstudio.update sign" in release and "latest.json" in release and "make_latest" in release


def test_signing_secret_only_in_release_job_and_never_echoed(jobs):
    for name, job in jobs.items():
        if name != "release":
            assert "secrets.MXS_UPDATE_SIGNING_KEY" not in job, name
    assert "secrets.MXS_UPDATE_SIGNING_KEY" in jobs["release"]
    assert not re.search(r"echo[^\n]*\$\{?MXS_UPDATE_SIGNING_KEY", WORKFLOW.read_text(encoding="utf-8"))


def test_signpath_step_is_optional_and_free_only(jobs):
    block = jobs["installers"].split("signpath/github-action-submit-signing-request", 1)
    assert len(block) == 2 and "if: ${{ vars.SIGNPATH_ORGANIZATION_ID != '' }}" in block[0].rsplit("- name:", 1)[1]
    text = WORKFLOW.read_text(encoding="utf-8").lower()
    for banned in ("inno", "iscc", "signtool", "pfx", "certificate_password"):
        assert banned not in text, banned


def test_mag_ci_installer_job_builds_both_flavours():
    job = _jobs(ROOT / ".github" / "workflows" / "mag-ci.yml")["installer"]
    assert "for flavour in online full" in job and "tests/mag/release" in job


def test_phase_docs_are_bilingual():
    for name in ("CLEAN_INSTALL_RUNBOOK_AR_EN.md", "PHASE_12_NOTES.md"):
        text = (ROOT / "docs" / "mag" / "phase-12" / name).read_text(encoding="utf-8")
        assert re.search(r"[؀-ۿ]{3,}", text) and re.search(r"[A-Za-z]{5,}", text), name


def test_standard_user_proof_never_counts_1601_as_a_pass():
    # a batch logon cannot reach Windows Installer as a standard user: recorded, never turned into "ok"
    text = (ROOT / "installer" / "windows_sandbox" / "standard_user_proof.ps1").read_text(encoding="ascii")
    assert '"not_provable_batch_logon"' in text
    assert "$ok = $ok -and ($Result.msi -eq \"ok\")" in text
    assert "setup_exit -eq 0" in text  # the Studio's own per-user install always decides


def _step_script(job: str, name: str) -> str:
    """The `run: |` block of the step whose name starts with `name` (no PyYAML: the project avoids it)."""
    lines = job.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip().startswith(f"- name: {name}"))
    run = next(i for i in range(start + 1, len(lines)) if lines[i].strip() == "run: |")
    indent = len(lines[run + 1]) - len(lines[run + 1].lstrip())
    script = []
    for line in lines[run + 1:]:
        if line.strip() and len(line) - len(line.lstrip()) < indent:
            break
        script.append(line[indent:])
    return "\n".join(script) + "\n"


@pytest.mark.skipif(sys.platform == "win32" or not __import__("shutil").which("bash"),
                    reason="the release job runs this bash step on ubuntu")
def test_signed_latest_json_step_runs_from_a_clean_checkout(tmp_path):
    """Run the release job's real «Signed latest.json» script, as CI does: cwd = a checkout where mxstudio
    is NOT importable through any path but the checkout itself (0.2.0's first publish failed exactly there)."""
    import os
    import subprocess
    from mxstudio.update import signing
    step = {"run": _step_script(_jobs(WORKFLOW)["release"], "Signed latest.json")}
    checkout = tmp_path / "checkout"
    release = checkout / "workspace" / "release"
    release.mkdir(parents=True)
    (checkout / "mxstudio").symlink_to(ROOT / "mxstudio", target_is_directory=True)
    (release / "ModuleX-MagazineStudio-Setup-9.9.9.exe").write_bytes(os.urandom(4096))
    (release / "ModuleX-MagazineStudio-Setup-9.9.9-Full.exe").write_bytes(os.urandom(8192))
    private, public = signing.generate_keypair()
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env.update(GITHUB_WORKSPACE=str(checkout), MXS_UPDATE_SIGNING_KEY=private, MXS_UPDATE_PUBLIC_KEY=public,
               REPO="o/r", TAG="mxs-v9.9.9", VERSION="9.9.9", RUNNER_TEMP=str(tmp_path))
    done = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", step["run"]], cwd=str(checkout), env=env,
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stdout + done.stderr
    assert '"ok": true' in done.stdout and "::error" not in done.stdout
    assert private not in done.stdout + done.stderr  # annotations never carry the key
    signed = json.loads((release / "latest.json").read_text(encoding="utf-8"))
    assert signing.verify_manifest(signed, {signing.key_id(public): public}) == signing.key_id(public)
    # a secret that is not the pinned key is named as such
    other, _ = signing.generate_keypair()
    (release / "latest.json").unlink()
    env.update(MXS_UPDATE_SIGNING_KEY=other, MXS_UPDATE_PUBLIC_KEY="")
    bad = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", step["run"]], cwd=str(checkout), env=env,
                         capture_output=True, text=True, timeout=120)
    assert bad.returncode == 1 and "the secret is a different key" in bad.stdout
