"""NSIS script: both flavours compile with makensis (dummy payload, warnings are errors) and keep the
MarketX conventions: per-user, program outside C:\\المشروع, uninstall asks with default No."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
NSI = ROOT / "installer" / "nsis" / "MagazineStudio.nsi"
TEXT = NSI.read_text(encoding="utf-8")
makensis = shutil.which("makensis")
needs_makensis = pytest.mark.skipif(not makensis, reason="makensis (NSIS 3) is not installed here; mag-ci installs it")


@pytest.fixture
def payload(tmp_path):
    app = tmp_path / "مجلد البرنامج"
    app.mkdir()
    (app / "ModuleX Magazine Studio.exe").write_bytes(b"MZ placeholder")
    (app / "mxstudio-cli.exe").write_bytes(b"MZ placeholder")
    (app / "_internal").mkdir()
    (app / "_internal" / "ملف.txt").write_text("عربي", encoding="utf-8")
    offline = tmp_path / "offline"
    (offline / "libreoffice").mkdir(parents=True)
    (offline / "libreoffice" / "LibreOffice_Win_x86-64.msi").write_bytes(b"placeholder msi")
    return app, offline


def _build(app, offline, out, *defines):
    cmd = [makensis, "-V2", "-WX", "-INPUTCHARSET", "UTF8", "-DAPP_VER=1.2.3", f"-DSRC_DIR={app}", f"-DOUT_DIR={out}",
           *defines, str(NSI)]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=300)


@needs_makensis
@pytest.mark.parametrize("flavour,name", [("online", "ModuleX-MagazineStudio-Setup-1.2.3.exe"),
                                          ("full", "ModuleX-MagazineStudio-Setup-1.2.3-Full.exe")])
def test_both_flavours_compile(tmp_path, payload, flavour, name):
    app, offline = payload
    out = tmp_path / "out"
    out.mkdir()
    result = _build(app, offline, out, f"-DFLAVOUR={flavour}", f"-DOFFLINE_DIR={offline}")
    assert result.returncode == 0, result.stdout + result.stderr
    exe = out / name
    assert exe.is_file() and exe.read_bytes()[:2] == b"MZ"
    assert b"Nullsoft" in exe.read_bytes()[:200_000] or exe.stat().st_size > 30_000


@needs_makensis
def test_negative_controls_do_not_compile(tmp_path, payload):
    app, offline = payload
    out = tmp_path / "out"
    out.mkdir()
    assert _build(app, offline, out, "-DFLAVOUR=full").returncode != 0  # Full without OFFLINE_DIR
    assert _build(app, offline, out, "-DFLAVOUR=portable").returncode != 0
    bad = subprocess.run([makensis, "-V2", "-INPUTCHARSET", "UTF8", str(NSI)], capture_output=True, text=True)
    assert bad.returncode != 0 and "SRC_DIR" in (bad.stdout + bad.stderr)


def test_per_user_fixed_dir_outside_project():
    assert re.search(r"^RequestExecutionLevel user$", TEXT, re.MULTILINE)
    assert 'InstallDir "$LOCALAPPDATA\\Programs\\${APP_NAME}"' in TEXT
    assert "MUI_PAGE_DIRECTORY" not in TEXT  # no directory page: the program location is fixed
    assert "المشروع" not in TEXT.split('InstallDir')[1].splitlines()[0]
    assert 'MUI_LANGUAGE "Arabic"' in TEXT


def test_uninstall_asks_with_default_no_and_never_touches_workspace():
    un_init = TEXT.split("Function un.onInit", 1)[1].split("FunctionEnd", 1)[0]
    assert "MB_YESNO" in un_init and "MB_DEFBUTTON2" in un_init and "/SD IDNO" in un_init
    assert 'StrCpy $RemoveData "0"' in un_init
    uninstall = TEXT.split('Section "Uninstall"', 1)[1]
    data_rm = uninstall.split('${If} $RemoveData == "1"', 1)
    assert len(data_rm) == 2 and 'RMDir /r "${DATA_DIR}"' in data_rm[1]
    assert 'RMDir /r "${DATA_DIR}"' not in data_rm[0]
    for line in TEXT.splitlines():
        if "RMDir" in line or "Delete " in line:
            assert "المشروع" not in line and "Workspace" not in line


def test_webview2_check_graceful_stop_and_hidden_children():
    assert "WEBVIEW2_GUID" in TEXT and "Call WebView2Installed" in TEXT
    assert "Call StopOld" in TEXT and "shutdown" in TEXT
    assert "ExecWait" not in TEXT and "ExecShell" not in TEXT
    # every child is nsExec (hidden); the only plain Exec relaunches the windowed GUI after /S /RELAUNCH=1
    plain = [l.strip() for l in TEXT.splitlines() if re.match(r"\s*Exec\s", l)]
    assert plain == ["Exec '\"$INSTDIR\\${APP_EXE}\"'"]


def test_full_flavour_extracts_libreoffice_without_admin():
    assert "msiexec.exe /a" in TEXT and "/qn" in TEXT and 'TARGETDIR="$INSTDIR\\libreoffice"' in TEXT
    assert "/i " not in TEXT.split('Section "Office engine"', 1)[1].split("SectionEnd", 1)[0]  # never a machine install
    assert "Call PowerPointInstalled" in TEXT


def test_online_flavour_keeps_installer_for_rollback():
    assert '!define KEEP_DIR "${DATA_DIR}\\update\\installers"' in TEXT
    assert 'CopyFiles /SILENT "$EXEPATH" "${KEEP_DIR}\\${SETUP_NAME}"' in TEXT
    from mxstudio.update.state import INSTALLER_PREFIX
    assert 'SETUP_NAME "ModuleX-MagazineStudio-Setup-${APP_VER}.exe"' in TEXT and INSTALLER_PREFIX == "ModuleX-MagazineStudio-Setup-"
