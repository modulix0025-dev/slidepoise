"""Prove a built exe (or installer) carries OUR icon: every frame of installer/assets/app.ico, byte for byte.

    python tools/check_exe_icon.py "workspace/dist/ModuleX Magazine Studio/ModuleX Magazine Studio.exe" ...

Build-time check only (needs `pefile`, MIT, installed in the build venv, never shipped). Exit 1 names
the exe that still has another icon (e.g. PyInstaller's or NSIS's default).
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

ICO = Path(__file__).resolve().parents[1] / "installer" / "assets" / "app.ico"


def ico_frames(data: bytes) -> list[bytes]:
    count = struct.unpack("<H", data[4:6])[0]
    frames = []
    for i in range(count):
        size, offset = struct.unpack("<II", data[6 + 16 * i + 8:6 + 16 * i + 16])
        frames.append(data[offset:offset + size])
    return frames


def exe_frames(path: Path) -> list[bytes]:
    import pefile  # noqa: PLC0415
    pe = pefile.PE(str(path), fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]])
    out = []
    for entry in getattr(pe, "DIRECTORY_ENTRY_RESOURCE", None).entries if hasattr(pe, "DIRECTORY_ENTRY_RESOURCE") else []:
        if entry.id != pefile.RESOURCE_TYPE["RT_ICON"]:
            continue
        for icon in entry.directory.entries:
            for lang in icon.directory.entries:
                out.append(pe.get_data(lang.data.struct.OffsetToData, lang.data.struct.Size))
    return out


def main(argv: list[str]) -> int:
    ours = ico_frames(ICO.read_bytes())
    bad = 0
    for name in argv:
        found = exe_frames(Path(name))
        missing = [i for i, frame in enumerate(ours) if frame not in found]
        print(f"{'ok ' if not missing else 'BAD'} {name}: {len(ours) - len(missing)}/{len(ours)} icon frames are ours")
        bad += bool(missing)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
