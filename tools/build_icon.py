"""Build every app icon from the one source drawing, installer/assets/app.svg (chosen by the operator: «تاج على الغلاف»).

    python tools/build_icon.py           # writes installer/assets/app.ico and mxstudio/ui/app-icon.svg
    python tools/build_icon.py --check   # exit 1 if a generated file is stale

app.ico (16-256 px) is used by PyInstaller for both exes, by NSIS for the installer and the
uninstaller, and by Windows for the taskbar and the Start menu; the UI uses the SVG as logo and favicon.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "installer" / "assets" / "app.svg"
ICO = ROOT / "installer" / "assets" / "app.ico"
UI_SVG = ROOT / "mxstudio" / "ui" / "app-icon.svg"
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def render(size: int, svg: str):
    import resvg_py  # noqa: PLC0415
    from PIL import Image  # noqa: PLC0415
    return Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_string=svg, width=size, height=size))).convert("RGBA")


def ico_bytes(svg: str) -> bytes:
    """Each size rendered from the vector (sharper than downscaling one bitmap)."""
    from PIL import Image  # noqa: PLC0415,F401
    images = [render(size, svg) for size in SIZES]
    out = io.BytesIO()
    images[-1].save(out, format="ICO", sizes=[(s, s) for s in SIZES], append_images=images[:-1])
    return out.getvalue()


def main(argv: list[str]) -> int:
    svg = SOURCE.read_text(encoding="utf-8")
    wanted = {UI_SVG: svg.encode("utf-8"), ICO: ico_bytes(svg)}
    stale = [path for path, data in wanted.items() if not path.is_file() or path.read_bytes() != data]
    if "--check" in argv:
        for path in stale:
            print(f"stale: {path.relative_to(ROOT)} (run python tools/build_icon.py)")
        return 1 if stale else 0
    for path in stale:
        path.write_bytes(wanted[path])
        print(f"wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
