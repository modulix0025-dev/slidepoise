"""Update state machine: check → download (resume) → verify → stage → consent → apply on next launch
→ applied / failed, and one-click rollback with the kept previous installer."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from mxstudio.update import manifest as mf
from mxstudio.update import signing
from mxstudio.update.errors import UpdateError
from mxstudio.update.state import SILENT_ARGS, UpdateManager, installer_name

BASE = "https://github.com/o/r/releases/download"


class Spawned(list):
    def __call__(self, cmd):
        self.append(cmd)


def _publish(server, keypair, version: str, payload: bytes, *, tamper_after_sign: bool = False) -> dict:
    private, _ = keypair
    name = installer_name(version)
    url = f"{BASE}/mxs-v{version}/{name}"
    sha = server.add(url, payload)
    manifest = {"schema": mf.SCHEMA_ID, "app": mf.APP_ID, "version": version, "released_at": "2026-10-11T00:00:00Z",
                "notes_ar": "نسخة جديدة", "notes_en": "new version",
                "assets": {"online": {"name": name, "url": url, "sha256": sha, "size": len(payload)}}}
    signed = signing.sign_manifest(manifest, private)
    if tamper_after_sign:
        signed["assets"]["online"]["url"] = f"{BASE}/mxs-v{version}/ModuleX-MagazineStudio-Setup-evil.exe"
    server.files["https://github.com/o/r/releases/latest/download/latest.json"] = json.dumps(signed).encode()
    return signed


def _manager(home, trust, server, version, spawn=None):
    def fetch(url):
        return b"".join(server(url, 0).chunks)
    return UpdateManager(home, current_version=version, trust=trust, fetch=fetch, transport=server,
                         spawn=spawn if spawn is not None else Spawned())


def _seed_installed(home: Path, version: str, payload: bytes) -> Path:
    """What NSIS does on install: keep a copy of the installer that installed this version."""
    keep = home / "update" / "installers" / installer_name(version)
    keep.parent.mkdir(parents=True, exist_ok=True)
    keep.write_bytes(payload)
    return keep


def test_full_cycle_check_download_stage_consent_apply_applied(home, trust, server, keypair):
    _seed_installed(home, "0.2.0", b"old installer" * 50)
    _publish(server, keypair, "0.3.0", b"new installer" * 500)
    spawn = Spawned()
    m = _manager(home, trust, server, "0.2.0", spawn)
    m.on_launch()
    assert m.check()["state"] == "available"
    lines = []
    assert m.download(progress=lines.append)["state"] == "downloaded"
    assert lines[-1]["percent"] == 100 and "٪" in lines[-1]["ar"] and "١٠٠" in lines[-1]["ar"]
    assert m.verify()
    assert m.stage()["state"] == "staged"
    # no consent → nothing runs, at launch either
    assert m.launch_hook() is False and spawn == []
    with pytest.raises(UpdateError) as info:
        m.apply()
    assert info.value.code == "no_consent"
    m.consent(True)
    assert m.launch_hook() is True
    assert spawn[-1][1:] == SILENT_ARGS and spawn[-1][0].endswith(installer_name("0.3.0"))
    assert m.state()["state"] == "applying" and m.state()["consent"] is False
    # next launch, new version running
    after = _manager(home, trust, server, "0.3.0")
    assert after.on_launch()["state"] == "applied"
    versions = [r["version"] for r in after.history()]
    assert versions == ["0.2.0", "0.3.0"]
    assert after.rollback_target()["version"] == "0.2.0"


def test_failed_apply_is_reported_and_never_loops(home, trust, server, keypair):
    _publish(server, keypair, "0.3.0", b"new" * 1000)
    spawn = Spawned()
    m = _manager(home, trust, server, "0.2.0", spawn)
    m.check(), m.download(), m.stage(), m.consent(True)
    assert m.launch_hook() is True
    same = _manager(home, trust, server, "0.2.0", spawn)  # installer did not change the version
    state = same.on_launch()
    assert state["state"] == "failed" and state["error"]["code"] == "apply_failed"
    assert same.launch_hook() is False and len(spawn) == 1  # consent was cleared: no loop
    same.consent(True)  # operator retries
    assert same.launch_hook() is True and len(spawn) == 2


def test_tampered_manifest_is_never_offered(home, trust, server, keypair):
    _publish(server, keypair, "0.3.0", b"x" * 100, tamper_after_sign=True)
    m = _manager(home, trust, server, "0.2.0")
    state = m.check()
    assert state["state"] == "idle" and state["error"]["code"] == "bad_signature"
    with pytest.raises(UpdateError):
        m.download()


def test_unsigned_manifest_rejected(home, trust, server):
    server.files["https://github.com/o/r/releases/latest/download/latest.json"] = json.dumps(
        {"schema": mf.SCHEMA_ID, "version": "9.0.0"}).encode()
    assert _manager(home, trust, server, "0.2.0").check()["error"]["code"] == "unsigned"


def test_older_or_same_version_not_offered(home, trust, server, keypair):
    _publish(server, keypair, "0.2.0", b"x" * 100)
    assert _manager(home, trust, server, "0.2.0").check()["result"] == "up_to_date"
    _publish(server, keypair, "0.1.0", b"x" * 100)  # replayed old signed manifest
    assert _manager(home, trust, server, "0.2.0").check()["state"] == "idle"


def test_download_resumes_after_interruption(home, trust, server, keypair):
    payload = bytes(range(256)) * 200
    _publish(server, keypair, "0.3.0", payload)
    m = _manager(home, trust, server, "0.2.0")
    m.check()
    server.cut_after = 20_000
    state = m.download()
    assert state["state"] == "available" and state["error"]["code"] == "interrupted"
    part = home / "update" / "downloads" / (installer_name("0.3.0") + ".part")
    assert part.stat().st_size == 20_000
    server.cut_after = None
    lines = []
    assert m.download(progress=lines.append)["state"] == "downloaded"
    assert server.requests[-1][1] == 20_000  # Range request from the cut byte
    assert lines[-1]["resumed_from"] == 20_000 and "كمّلنا" in lines[-1]["ar"]
    assert (home / "update" / "downloads" / installer_name("0.3.0")).read_bytes() == payload


def test_server_ignoring_range_restarts_cleanly(home, trust, server, keypair):
    payload = b"abc" * 10_000
    _publish(server, keypair, "0.3.0", payload)
    m = _manager(home, trust, server, "0.2.0")
    m.check()
    server.cut_after = 5_000
    m.download()
    server.cut_after, server.ignore_range = None, True
    assert m.download()["state"] == "downloaded"
    assert (home / "update" / "downloads" / installer_name("0.3.0")).read_bytes() == payload


def test_corrupted_download_is_deleted_not_staged(home, trust, server, keypair):
    signed = _publish(server, keypair, "0.3.0", b"good" * 100)
    server.files[signed["assets"]["online"]["url"]] = b"evil" * 100  # same size, other bytes
    m = _manager(home, trust, server, "0.2.0")
    m.check()
    state = m.download()
    assert state["state"] == "failed" and state["error"]["code"] == "sha256_mismatch"
    assert not list((home / "update" / "downloads").glob("*.exe*"))


def test_staged_file_tampered_before_apply_is_refused(home, trust, server, keypair):
    _publish(server, keypair, "0.3.0", b"good" * 100)
    spawn = Spawned()
    m = _manager(home, trust, server, "0.2.0", spawn)
    m.check(), m.download(), m.stage(), m.consent(True)
    Path(m.state()["staged"]["path"]).write_bytes(b"evil" * 100)
    assert m.apply() is False and spawn == []
    assert m.state()["error"]["code"] == "sha256_mismatch"


def test_rollback_uses_kept_installer_and_skips_bad_version(home, trust, server, keypair):
    old = b"0.2.0 installer" * 100
    _seed_installed(home, "0.2.0", old)
    m = _manager(home, trust, server, "0.2.0")
    m.on_launch()
    _publish(server, keypair, "0.3.0", b"0.3.0 installer" * 100)
    m.check(), m.download(), m.stage(), m.consent(True)
    m.launch_hook()
    spawn = Spawned()
    now = _manager(home, trust, server, "0.3.0", spawn)
    now.on_launch()
    assert now.rollback() is True
    assert spawn[-1][0].endswith(installer_name("0.2.0")) and spawn[-1][1:] == SILENT_ARGS
    back = _manager(home, trust, server, "0.2.0")
    assert back.on_launch()["state"] == "rolled_back"
    assert "0.3.0" in back.state()["skipped_versions"]
    assert back.check()["result"] == "up_to_date"  # the bad version is not offered again
    _publish(server, keypair, "0.3.1", b"fixed" * 100)
    assert back.check()["state"] == "available"  # a newer fix is


def test_rollback_refuses_tampered_previous_installer(home, trust, server, keypair):
    keep = _seed_installed(home, "0.2.0", b"original" * 100)
    _manager(home, trust, server, "0.2.0").on_launch()
    keep.write_bytes(b"replaced" * 100)
    spawn = Spawned()
    now = _manager(home, trust, server, "0.3.0", spawn)
    now.on_launch()
    assert now.rollback() is False and spawn == []
    assert now.state()["error"]["code"] == "sha256_mismatch"


def test_rollback_without_previous_installer_is_honest(home, trust, server):
    m = _manager(home, trust, server, "0.2.0")
    m.on_launch()
    assert m.rollback() is False
    assert m.state()["error"]["code"] == "no_previous"


def test_prune_keeps_current_and_previous_only(home, trust, server):
    for v in ("0.1.0", "0.2.0", "0.3.0"):
        _seed_installed(home, v, v.encode() * 50)
        _manager(home, trust, server, v).on_launch()
    names = sorted(p.name for p in (home / "update" / "installers").iterdir())
    assert names == [installer_name("0.2.0"), installer_name("0.3.0")]


def test_no_manifest_url_or_offline_is_reported(home, trust, server):
    trust.manifest_url = ""
    assert _manager(home, trust, server, "0.2.0").check()["error"]["code"] == "no_manifest_url"
    trust.manifest_url = "https://github.com/o/r/releases/latest/download/missing.json"
    assert _manager(home, trust, server, "0.2.0").check()["error"]["code"] == "offline"
