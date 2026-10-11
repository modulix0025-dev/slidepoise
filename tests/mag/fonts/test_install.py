"""Install: per-user vs machine scope by the exporting account, UAC in Arabic, never kill a live export."""
from __future__ import annotations

import sys

import pytest

from mxstudio.fonts.install import (Account, MemoryBackend, NeedsElevation, WindowsBackend, after_install,
                                    choose_scope, install_fonts, plan_install, verify_installed, wait_for_idle)

OPERATOR = Account("operator", "S-1-5-21-1-1001", session_id=1)
OTHER = Account("printer", "S-1-5-21-1-1002", session_id=2)
SERVICE = Account("SYSTEM", "S-1-5-18", session_id=0, is_service=True)


def test_scope_follows_the_exporting_account():
    assert choose_scope(OPERATOR, OPERATOR)["scope"] == "user"
    assert choose_scope(OPERATOR, OTHER)["reason"] == "exporter_is_other_user"
    decision = choose_scope(OPERATOR, SERVICE)
    assert decision["scope"] == "machine" and decision["reason"] == "exporter_is_service"
    assert "UAC" in decision["ar"] and "SYSTEM" in decision["ar"]
    assert Account("svc", "S-1-5-21-9", session_id=0).runs_as_service


def test_per_user_install_registers_full_path_and_broadcasts(fonts, tmp_path):
    backend = MemoryBackend(tmp_path)
    results = install_fonts([fonts["tajawal"], fonts["tajawal_bold"]], "user", backend)
    assert [r.windows_reported_name for r in results] == ["Tajawal", "Tajawal Bold"]  # Tajawal's own ID4 says «Tajawal»
    values = backend.registry_values("user")
    assert values["Tajawal (TrueType)"].endswith("LocalAppData/Microsoft/Windows/Fonts/Tajawal-Regular.ttf")
    assert backend.broadcasts == 1 and len(backend.resources) == 2
    assert verify_installed(results, backend) == []
    assert results[0].as_ack() == {"file": "Tajawal-Regular.ttf", "windows_reported_name": "Tajawal",
                                   "scope": "user"}


def test_machine_install_needs_elevation_explained_in_arabic(fonts, tmp_path):
    backend = MemoryBackend(tmp_path, admin=False)
    with pytest.raises(NeedsElevation) as excinfo:
        install_fonts([fonts["tajawal"]], "machine", backend)
    assert "C:\\Windows\\Fonts" in excinfo.value.message_ar and "UAC" in excinfo.value.message_ar
    assert backend.registry_values("machine") == {}
    plan = plan_install(OPERATOR, SERVICE, backend)
    assert plan["scope"] == "machine" and plan["needs_uac"]
    elevated = MemoryBackend(tmp_path / "admin", admin=True)
    results = install_fonts([fonts["tajawal"]], "machine", elevated)
    assert elevated.registry_values("machine") == {"Tajawal (TrueType)": "Tajawal-Regular.ttf"}
    assert results[0].scope == "machine"


def test_negative_control_verify_detects_a_changed_file(fonts, tmp_path):
    backend = MemoryBackend(tmp_path)
    results = install_fonts([fonts["amiri"]], "user", backend)
    with open(results[0].path, "ab") as handle:
        handle.write(b"\0")
    backend.registry["user"].clear()
    found = {p["finding"] for p in verify_installed(results, backend)}
    assert found == {"font_not_registered", "font_file_changed_or_missing"}


def test_running_powerpoint_waits_for_idle_and_is_never_killed(tmp_path):
    backend = MemoryBackend(tmp_path, running={"POWERPNT.EXE"})
    clock = iter(range(0, 10_000, 5))
    sleeps = []
    state = after_install(backend, lambda: True, poll_s=5, timeout_s=20, sleep=sleeps.append,
                          clock=lambda: next(clock))
    assert state["state"] == "waiting_for_idle" and sleeps  # it waited, it did not kill
    assert "POWERPNT.EXE" in backend.running
    busy = iter([True, True, False])
    state = after_install(backend, lambda: next(busy), poll_s=1, timeout_s=60, sleep=lambda s: None)
    assert state["state"] == "restart_powerpoint_when_idle" and "PowerPoint" in state["ar"]
    assert after_install(MemoryBackend(tmp_path), lambda: True)["state"] == "ready"
    assert wait_for_idle(lambda: False)


@pytest.mark.skipif(sys.platform == "win32", reason="checks the Linux guard")
def test_windows_backend_is_guarded_off_windows():
    with pytest.raises(OSError):
        WindowsBackend()
