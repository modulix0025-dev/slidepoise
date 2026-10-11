"""Build every app icon from the one source drawing, installer/assets/app.svg (chosen by the operator: «تاج على الغلاف»).

    python tools/build_icon.py           # writes installer/assets/app.ico and mxstudio/ui/app-icon.svg
    python tools/build_icon.py --check   # exit 1 if a generated file is stale

app.ico (16-256 px) is used by PyInstaller for both exes, by NSIS for the installer and the
uninstaller, and by Windows for the taskbar and the Start menu; the UI uses the SVG as logo and favicon.
"""
from __future__ import annotations

import io
import struct
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


def _dib(image) -> bytes:
    """32-bit BGRA DIB with an all-zero AND mask: the classic frame every Windows component reads."""
    size = image.width
    header = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    rows = [image.crop((0, y, size, y + 1)).tobytes("raw", "BGRA") for y in range(size - 1, -1, -1)]
    mask_row = b"\0" * (((size + 31) // 32) * 4)
    return header + b"".join(rows) + mask_row * size


def ico_bytes(svg: str) -> bytes:
    """Each size rendered from the vector (sharper than downscaling one bitmap). Sizes below 256 are DIB
    frames (shortcuts, the taskbar and Explorer's small views read those everywhere); 256 is PNG, as usual."""
    frames = []
    for size in SIZES:
        image = render(size, svg)
        if size >= 256:
            out = io.BytesIO()
            image.save(out, "PNG", optimize=True)
            frames.append((size, out.getvalue()))
        else:
            frames.append((size, _dib(image)))
    header = struct.pack("<HHH", 0, 1, len(frames))
    offset = 6 + 16 * len(frames)
    directory, blobs = b"", b""
    for size, blob in frames:
        directory += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(blob), offset + len(blobs))
        blobs += blob
    return header + directory + blobs


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
