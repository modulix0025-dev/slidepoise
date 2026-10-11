"""Resolve installed fonts by family name, the way Office does.

Office asks for a typeface by *family name*, so the registry indexes every font
file by the names in its `name` table (typographic family 16, legacy family 1,
full name 4) and never by file name. Names are compared after NFC, end-trim and
casefold only: internal whitespace is significant, because a real story font is
called ``Blabeloo  MagdySoliman`` with two spaces and a collapsed name would
match nothing (or the wrong font).

Search order: ``SLIDEPOISE_FONT_DIRS`` (os.pathsep-separated), then the
per-user and machine Windows font folders plus the registry values that point
outside them, then the usual Linux and macOS folders.
"""
from __future__ import annotations

import os
import sys
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from fontTools.ttLib import TTCollection, TTFont, TTLibError

FONT_SUFFIXES = {".ttf", ".otf", ".ttc", ".otc"}
_WIN_FONT_KEY = r"Software\Microsoft\Windows NT\CurrentVersion\Fonts"


def normalize_family(name: str) -> str:
    """NFC + end-trim + casefold. Internal whitespace is never collapsed."""
    return unicodedata.normalize("NFC", str(name)).strip().casefold()


@dataclass(frozen=True)
class FontFace:
    path: str
    index: int
    family: str
    subfamily: str
    full_name: str
    weight: int
    italic: bool

    @property
    def bold(self) -> bool:
        return self.weight >= 600


def _windows_registry_paths() -> list[Path]:
    if sys.platform != "win32":
        return []
    try:
        import winreg  # noqa: PLC0415 - Windows only
    except ImportError:
        return []
    found: list[Path] = []
    windir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts"
    for hive, base in ((winreg.HKEY_LOCAL_MACHINE, windir), (winreg.HKEY_CURRENT_USER, local)):
        try:
            with winreg.OpenKey(hive, _WIN_FONT_KEY) as key:
                index = 0
                while True:
                    try:
                        _name, value, _kind = winreg.EnumValue(key, index)
                    except OSError:
                        break
                    index += 1
                    candidate = Path(str(value))
                    found.append(candidate if candidate.is_absolute() else base / candidate)
        except OSError:
            continue
    return found


def font_dirs() -> list[Path]:
    dirs: list[Path] = []
    extra = os.environ.get("SLIDEPOISE_FONT_DIRS", "")
    dirs.extend(Path(item) for item in extra.split(os.pathsep) if item.strip())
    if sys.platform == "win32":
        dirs.append(Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts")
        dirs.append(Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts")
    elif sys.platform == "darwin":
        dirs.extend([Path.home() / "Library" / "Fonts", Path("/Library/Fonts"), Path("/System/Library/Fonts"),
                     Path("/System/Library/Fonts/Supplemental")])
    else:
        dirs.extend([Path.home() / ".fonts", Path.home() / ".local" / "share" / "fonts",
                     Path("/usr/local/share/fonts"), Path("/usr/share/fonts")])
    return dirs


def _name(font: TTFont, *ids: int) -> str:
    table = font["name"] if "name" in font else None
    if table is None:
        return ""
    for name_id in ids:
        record = table.getDebugName(name_id)
        if record:
            return str(record)
    return ""


def _faces_in(path: Path) -> list[FontFace]:
    try:
        if path.suffix.lower() in {".ttc", ".otc"}:
            fonts = list(TTCollection(str(path), lazy=True).fonts)
        else:
            fonts = [TTFont(str(path), lazy=True, fontNumber=0)]
    except (TTLibError, OSError, ValueError, KeyError, AssertionError):
        return []
    faces = []
    for index, font in enumerate(fonts):
        try:
            os2 = font["OS/2"] if "OS/2" in font else None
            weight = int(getattr(os2, "usWeightClass", 400) or 400)
            italic = bool(getattr(os2, "fsSelection", 0) & 1)
            for family in {_name(font, 16, 1), _name(font, 1)} - {""}:
                faces.append(FontFace(path=str(path), index=index, family=family,
                                      subfamily=_name(font, 17, 2), full_name=_name(font, 4),
                                      weight=weight, italic=italic))
        except Exception:  # noqa: BLE001 - one broken font must not hide the others
            continue
        finally:
            font.close()
    return faces


class FontRegistry:
    """Family-name index over a fixed set of directories and files."""

    def __init__(self, directories: list[Path] | None = None, files: list[Path] | None = None):
        self._by_family: dict[str, list[FontFace]] = {}
        seen: set[str] = set()
        candidates: list[Path] = list(files or [])
        for directory in directories if directories is not None else font_dirs():
            if directory and directory.is_dir():
                candidates.extend(p for p in directory.rglob("*") if p.suffix.lower() in FONT_SUFFIXES)
        if directories is None and files is None:
            candidates.extend(_windows_registry_paths())
        for path in candidates:
            key = str(path.resolve()) if path.exists() else ""
            if not key or key in seen:
                continue
            seen.add(key)
            for face in _faces_in(path):
                self._by_family.setdefault(normalize_family(face.family), []).append(face)

    def families(self) -> list[str]:
        return sorted({faces[0].family for faces in self._by_family.values()})

    def faces(self, family: str) -> list[FontFace]:
        return list(self._by_family.get(normalize_family(family), []))

    def has(self, family: str) -> bool:
        return normalize_family(family) in self._by_family

    def resolve(self, family: str, bold: bool = False, italic: bool = False) -> FontFace | None:
        """Closest face of exactly this family, or None. Never substitutes another family."""
        faces = self.faces(family)
        if not faces:
            return None
        target = 700 if bold else 400
        return min(faces, key=lambda face: (face.italic != italic, abs(face.weight - target), face.path))


@lru_cache(maxsize=8)
def _cached_registry(dirs_key: tuple[str, ...]) -> FontRegistry:
    return FontRegistry()


def default_registry() -> FontRegistry:
    """Registry for the current font directories (cached per directory list)."""
    return _cached_registry(tuple(str(path) for path in font_dirs()))
