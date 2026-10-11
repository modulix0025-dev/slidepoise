# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller one-folder build of ModuleX Magazine Studio (run on Windows).

Produces ``dist/ModuleX Magazine Studio/`` with two windowed executables sharing one
``_internal`` folder (never a visible console):

* ``ModuleX Magazine Studio.exe`` — the desktop app (pywebview window, no js_api);
* ``mxstudio-cli.exe``            — background commands (serve, shutdown, doctor, update, …).

Bundled: Python runtime, OpenCV (headless), Pillow, NumPy, python-pptx, lxml, uharfbuzz,
fontTools, pypdf, pikepdf, pypdfium2, coloraide, pyclipper, vtracer — none of the components
banned by catalog/licence_policy.json, and no Poppler (pypdfium2 rasterises). The portable
Node runtime + node_modules are added next to the exes by build_windows.ps1 (``node/``).

    pyinstaller --noconfirm --clean installer/pyinstaller/MagazineStudio.spec
"""
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

HERE = Path(SPECPATH).resolve()
ROOT = HERE.parents[1]
APP_NAME = "ModuleX Magazine Studio"
for extra in (str(ROOT), str(ROOT / "slidepoise" / "runtime" / "src"), str(HERE)):
    if extra not in sys.path:
        sys.path.insert(0, extra)

FORBIDDEN = ["pdf2image", "tkinter", "_tkinter", "matplotlib", "IPython",
             "pytest", "PyQt5", "PyQt6", "PySide2", "PySide6"]


def _safe(fn, name):
    try:
        return fn(name)
    except Exception:  # package missing on this build host: reported by the Doctor at runtime
        return []


hiddenimports = ["entry_cli"]
for pkg in ("mxstudio", "slidepoise", "uvicorn", "webview", "clr_loader", "pythonnet", "cv2", "pikepdf",
            "pypdfium2", "pypdfium2_raw", "uharfbuzz", "fontTools", "coloraide", "pyclipper", "vtracer",
            "pptx", "lxml", "svgelements", "qrcode", "resvg_py", "cryptography"):
    hiddenimports += _safe(collect_submodules, pkg)

datas = [(str(ROOT / "installer" / "downloads.json"), "mxstudio_data")]
for pkg in ("mxstudio", "pptx", "pypdfium2", "pypdfium2_raw", "webview", "coloraide", "fontTools"):
    datas += _safe(collect_data_files, pkg)
# The SlidePoise skill tree (SKILL.md, references, schemas, runtime/js) as plain resources.
for rel, dest in (("slidepoise", "skill/slidepoise"), ("catalog", "catalog"), ("contracts", "contracts"),
                  ("vendor/modulex", "vendor/modulex"), ("framework/defaults", "framework/defaults"),
                  ("mxlibs", "mxlibs")):
    if (ROOT / rel).is_dir():
        datas.append((str(ROOT / rel), dest))

binaries = []
for pkg in ("pypdfium2_raw", "cv2", "pikepdf", "uharfbuzz", "vtracer"):
    binaries += _safe(collect_dynamic_libs, pkg)

# UTF-8 mode inside the frozen interpreter (Arabic paths; Doctor check "python").
PY_OPTIONS = [("X utf8", None, "OPTION")]


def _analysis(script):
    return Analysis(
        [str(HERE / script)],
        pathex=[str(ROOT), str(ROOT / "slidepoise" / "runtime" / "src"), str(HERE)],
        binaries=binaries,
        datas=datas,
        hiddenimports=hiddenimports,
        excludes=FORBIDDEN,
        noarchive=False,
    )


a_gui = _analysis("entry_gui.py")
a_cli = _analysis("entry_cli.py")
pyz_gui = PYZ(a_gui.pure)
pyz_cli = PYZ(a_cli.pure)

icon = ROOT / "installer" / "assets" / "app.ico"
exe_kwargs = dict(debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
                  console=False,  # NEVER a visible console (operator rule)
                  disable_windowed_traceback=False, argv_emulation=False,
                  icon=str(icon) if icon.is_file() else None)

exe_gui = EXE(pyz_gui, a_gui.scripts, PY_OPTIONS, exclude_binaries=True, name=APP_NAME, **exe_kwargs)
exe_cli = EXE(pyz_cli, a_cli.scripts, PY_OPTIONS, exclude_binaries=True, name="mxstudio-cli", **exe_kwargs)

coll = COLLECT(
    exe_gui, a_gui.binaries, a_gui.datas,
    exe_cli, a_cli.binaries, a_cli.datas,
    strip=False, upx=False, name=APP_NAME,
)
