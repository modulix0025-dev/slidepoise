"""Discover the operator's systems under the project root by marker files (read-only).

Rule: a system is "found" only when every marker exists; "partial" when its folder exists
but a marker is missing (patches for it are then blocked); "absent" otherwise. The root
defaults to the Studio's configured project root (``C:\\المشروع`` on Windows) and can be
overridden per call. Arabic paths are handled with :mod:`pathlib` only.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._util import read_json, rel_posix, sha256_file, walk_files


@dataclass(frozen=True)
class SystemSpec:
    key: str
    folder: str
    markers: tuple[str, ...]
    label_ar: str
    label_en: str


SYSTEMS: tuple[SystemSpec, ...] = (
    SystemSpec("OM", "OrderManagement", ("app/services/story_engine.py", "app/editor/deck.py"),
               "إدارة الأوردرات", "Order Management"),
    SystemSpec("Console", "ModuleX_Console",
               ("execution_console/services/magazine_pptx.py", "story_decks.json"),
               "الكونسول", "Execution Console"),
    SystemSpec("Store", "ModuleX_Store", ("mxstore/", "contracts/"), "المتجر", "ModuleX Store"),
    SystemSpec("Orchestrator", "ModuleXOrchestrator", ("",), "الأوركستريتور", "Orchestrator"),
)
SYSTEM_BY_KEY = {s.key: s for s in SYSTEMS}

#: Where story_decks.json may live inside the Console (verified on device; first hit wins).
CONSOLE_DECKS_CANDIDATES = ("story_decks.json", "execution_console/story_decks.json",
                            "execution_console/services/story_decks.json")


def default_root() -> Path:
    from mxstudio.config import Settings, project_root

    try:
        configured = Settings().load().get("project_root")
    except Exception:  # noqa: BLE001 - a broken settings file must not stop discovery
        configured = None
    return Path(configured) if configured else project_root()


def _marker_exists(system_dir: Path, marker: str) -> bool:
    if marker == "":
        return system_dir.is_dir()
    if marker.endswith("/"):
        return (system_dir / marker.rstrip("/")).is_dir()
    if marker == "story_decks.json":
        return any((system_dir / c).is_file() for c in CONSOLE_DECKS_CANDIDATES)
    return (system_dir / marker).is_file()


def find_console_decks(console_dir: Path) -> Path | None:
    for cand in CONSOLE_DECKS_CANDIDATES:
        if (console_dir / cand).is_file():
            return console_dir / cand
    return None


def discover(root: Path | str | None = None) -> dict[str, Any]:
    """Return ``{root, root_exists, systems: {key: {...}}, contract_copies: [...]}``."""
    root = Path(root) if root else default_root()
    out: dict[str, Any] = {"root": str(root), "root_exists": root.is_dir(), "systems": {}}
    for spec in SYSTEMS:
        sdir = root / spec.folder
        markers = {m or "<folder>": _marker_exists(sdir, m) for m in spec.markers}
        if not sdir.is_dir():
            status = "absent"
        elif all(markers.values()):
            status = "found"
        else:
            status = "partial"
        entry: dict[str, Any] = {"key": spec.key, "folder": spec.folder, "path": str(sdir), "status": status,
                                 "markers": markers, "label_ar": spec.label_ar, "label_en": spec.label_en,
                                 "run_tests_bat": (sdir / "RUN_TESTS.bat").is_file()}
        if spec.key == "Console" and sdir.is_dir():
            decks = find_console_decks(sdir)
            entry["story_decks_json"] = rel_posix(decks, sdir) if decks else None
            entry["frozen_app_hint"] = any(p.suffix.lower() == ".exe" for p in walk_files(sdir, max_depth=2,
                                                                                         suffixes=(".exe",)))
        if spec.key == "OM" and sdir.is_dir():
            entry["templates_dir_exists"] = (sdir / "story_templates").is_dir()
        out["systems"][spec.key] = entry
    out["contract_copies"] = contract_copies(root) if root.is_dir() else []
    return out


def contract_copies(root: Path) -> list[dict[str, Any]]:
    """Every copy of a frozen contract file under the root (modulex_signing / pptx_to_pdf / pairing)."""
    copies = []
    for path in walk_files(root, names=("modulex_signing.py", "pptx_to_pdf.py", "modulex_pairing.py"), max_depth=7):
        copies.append({"path": rel_posix(path, root), "name": path.name, "sha256": sha256_file(path)})
    return copies


def system_dir(found: dict[str, Any], key: str) -> Path | None:
    entry = found.get("systems", {}).get(key)
    if not entry or entry["status"] == "absent":
        return None
    return Path(entry["path"])


def load_story_decks(console_dir: Path) -> dict | None:
    decks = find_console_decks(console_dir)
    return read_json(decks) if decks else None
