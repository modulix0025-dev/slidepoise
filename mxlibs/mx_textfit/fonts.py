"""Resolve installed fonts by exact family name, the way Office asks for them.

Rule enforced: a family is matched on the names in the font's ``name`` table
(typographic family 16, legacy family 1) after NFC, end-trim and casefold only.
Internal whitespace is significant: the operator's story font is literally
``Blabeloo  MagdySoliman`` (two spaces), and collapsing it would match nothing
or the wrong font. A family that is not installed is reported as missing; it is
never silently replaced (a caller may name explicit fallbacks, and the result
then says which family was substituted).

Search order: ``MX_FONT_DIRS`` then ``SLIDEPOISE_FONT_DIRS`` (os.pathsep
separated), the per-user and machine Windows font folders plus registry values
that point outside them, then the usual Linux and macOS folders.
"""

from __future__ import annotations

import os
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from . import _sfnt

FONT_SUFFIXES = {".ttf", ".otf", ".ttc", ".otc"}
_WIN_FONT_KEY = r"Software\Microsoft\Windows NT\CurrentVersion\Fonts"


def normalize_family(name: str) -> str:
    """NFC + end-trim + casefold. Internal whitespace is never collapsed."""
    return unicodedata.normalize("NFC", str(name or "")).strip().casefold()


@dataclass(frozen=True)
class FontFace:
    path: str
    index: int
    family: str
    subfamily: str
    full_name: str
    weight: int
    italic: bool

    def as_dict(self) -> dict:
        return {
            "family": self.family,
            "subfamily": self.subfamily,
            "full_name": self.full_name,
            "path": self.path,
            "index": self.index,
            "weight": self.weight,
            "italic": self.italic,
        }


def _windows_registry_paths() -> list[Path]:
    if sys.platform != "win32":
        return []
    try:
        import winreg
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
    for var in ("MX_FONT_DIRS", "SLIDEPOISE_FONT_DIRS"):
        extra = os.environ.get(var, "")
        dirs.extend(Path(item) for item in extra.split(os.pathsep) if item.strip())
    if sys.platform == "win32":
        dirs.append(Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts")
        dirs.append(Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts")
    elif sys.platform == "darwin":
        dirs.extend(
            [
                Path.home() / "Library" / "Fonts",
                Path("/Library/Fonts"),
                Path("/System/Library/Fonts"),
                Path("/System/Library/Fonts/Supplemental"),
            ]
        )
    else:
        dirs.extend(
            [
                Path.home() / ".fonts",
                Path.home() / ".local" / "share" / "fonts",
                Path("/usr/local/share/fonts"),
                Path("/usr/share/fonts"),
            ]
        )
    return dirs


def faces_in(path: Path) -> list[FontFace]:
    try:
        infos = _sfnt.read_all(str(path))
    except (OSError, ValueError, Exception):  # noqa: BLE001 - one broken font must not hide the others
        return []
    faces: list[FontFace] = []
    for index, info in enumerate(infos):
        families = {info.names.get(16, ""), info.names.get(1, "")} - {""}
        for family in families:
            faces.append(
                FontFace(
                    path=str(path),
                    index=index,
                    family=family,
                    subfamily=info.names.get(17) or info.names.get(2, ""),
                    full_name=info.names.get(4, ""),
                    weight=info.weight,
                    italic=info.italic,
                )
            )
    return faces


class FontResolver:
    """Family-name index over a fixed set of directories and files."""

    def __init__(self, directories: list | None = None, files: list | None = None):
        self._by_family: dict[str, list[FontFace]] = {}
        seen: set[str] = set()
        candidates: list[Path] = [Path(p) for p in (files or [])]
        dirs = [Path(d) for d in directories] if directories is not None else font_dirs()
        for directory in dirs:
            try:
                if directory and directory.is_dir():
                    candidates.extend(p for p in sorted(directory.rglob("*")) if p.suffix.lower() in FONT_SUFFIXES)
            except OSError:
                continue
        if directories is None and files is None:
            candidates.extend(_windows_registry_paths())
        for path in candidates:
            try:
                key = str(path.resolve()) if path.is_file() else ""
            except OSError:
                key = ""
            if not key or key in seen:
                continue
            seen.add(key)
            for face in faces_in(path):
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
        return min(faces, key=lambda face: (face.italic != italic, abs(face.weight - target), face.path, face.index))


_DEFAULT: dict[tuple, FontResolver] = {}


def default_resolver() -> FontResolver:
    """Resolver over the current font directories (cached per directory list)."""
    key = tuple(str(path) for path in font_dirs())
    if key not in _DEFAULT:
        _DEFAULT.clear()
        _DEFAULT[key] = FontResolver()
    return _DEFAULT[key]
