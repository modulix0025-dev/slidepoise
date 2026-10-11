"""The operator's chosen icon («تاج على الغلاف») is the one source for the exe, installer, taskbar and UI."""
from __future__ import annotations

import io
import shutil
import struct
import subprocess
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
SVG = ROOT / "installer" / "assets" / "app.svg"
ICO = ROOT / "installer" / "assets" / "app.ico"


def test_icon_has_every_windows_size_and_no_text():
    sizes = sorted(Image.open(ICO).info["sizes"])
    assert sizes == [(s, s) for s in (16, 20, 24, 32, 40, 48, 64, 128, 256)]
    svg = SVG.read_text(encoding="utf-8")
    assert "<text" not in svg and "font" not in svg  # renders the same on every PC
    assert (ROOT / "mxstudio" / "ui" / "app-icon.svg").read_text(encoding="utf-8") == svg


def test_icon_is_used_everywhere():
    assert '!define MUI_ICON "../assets/app.ico"' in (ROOT / "installer" / "nsis" / "MagazineStudio.nsi").read_text("utf-8")
    assert 'ROOT / "installer" / "assets" / "app.ico"' in (ROOT / "installer" / "pyinstaller" /
                                                           "MagazineStudio.spec").read_text("utf-8")
    page = (ROOT / "mxstudio" / "ui" / "index.html").read_text("utf-8")
    assert 'rel="icon" href="/ui/app-icon.svg"' in page and 'src="/ui/app-icon.svg"' in page


def test_small_sizes_still_show_the_cover():
    """At 16 px the white cover must still stand out from the coral tile (not a blur)."""
    small = Image.open(io.BytesIO(ICO.read_bytes()))
    small.size = (16, 16)
    pixels = small.convert("RGB").load()
    centre, corner = pixels[8, 8], pixels[2, 8]
    assert sum(centre) > 600 and abs(sum(centre) - sum(corner)) > 150


@pytest.mark.skipif(not shutil.which("makensis"), reason="makensis (NSIS 3) is not installed here; mag-ci installs it")
def test_installer_carries_the_icon(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    for name in ("ModuleX Magazine Studio.exe", "mxstudio-cli.exe"):
        (app / name).write_bytes(b"")
    subprocess.run(["makensis", "-V1", "-WX", "-INPUTCHARSET", "UTF8", "-DAPP_VER=1.2.3", f"-DSRC_DIR={app}",
                    f"-DOUT_DIR={tmp_path}", str(ROOT / "installer" / "nsis" / "MagazineStudio.nsi")], check=True)
    exe = next(tmp_path.glob("*.exe")).read_bytes()
    assert b"IHDR" + struct.pack(">II", 256, 256) in exe  # our 256 px frame, not NSIS's default icon


@pytest.mark.skipif(not shutil.which("makensis"), reason="makensis (NSIS 3) is not installed here; mag-ci installs it")
def test_icon_check_reads_the_exe_and_catches_another_icon(tmp_path, monkeypatch):
    import sys
    sys.path.insert(0, str(ROOT / "tools"))
    import build_icon
    import check_exe_icon
    app = tmp_path / "app"
    app.mkdir()
    for name in ("ModuleX Magazine Studio.exe", "mxstudio-cli.exe"):
        (app / name).write_bytes(b"")
    subprocess.run(["makensis", "-V1", "-WX", "-INPUTCHARSET", "UTF8", "-DAPP_VER=1.2.3", f"-DSRC_DIR={app}",
                    f"-DOUT_DIR={tmp_path}", str(ROOT / "installer" / "nsis" / "MagazineStudio.nsi")], check=True)
    exe = str(next(tmp_path.glob("*.exe")))
    assert check_exe_icon.main([exe]) == 0
    other = tmp_path / "other.ico"  # same drawing, another colour: every frame differs
    other.write_bytes(build_icon.ico_bytes(SVG.read_text("utf-8").replace("#E9725B", "#2E86AB")))
    monkeypatch.setattr(check_exe_icon, "ICO", other)
    assert check_exe_icon.main([exe]) == 1


def test_icon_frames_are_classic_bitmaps_below_256():
    import struct as st
    data = ICO.read_bytes()
    count = st.unpack("<H", data[4:6])[0]
    for i in range(count):
        width, _, _, _, planes, bits, size, offset = st.unpack("<BBBBHHII", data[6 + 16 * i:22 + 16 * i])
        is_png = data[offset:offset + 4] == b"\x89PNG"
        assert planes == 1 and bits == 32 and is_png == (width == 0), (width, is_png)
