"""Small shared helpers for the Kit: hashing, bounded tree walks, frozen/static path rules, JSON I/O.

Rules enforced here:
* frozen operator files (brief §5/§6.11) are recognised by relative path or file name;
* no Kit write (backup, payload) may land inside a folder named ``static`` (any case);
* tree walks are bounded and skip virtualenvs, VCS folders, caches and Kit backups.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
from collections.abc import Iterator
from pathlib import Path, PurePosixPath
from typing import Any

#: Relative paths (from the project root, posix, case-insensitive) that are frozen.
FROZEN_RELPATHS = (
    "OrderManagement/app/utils/config.py",
    "OrderManagement/app/editor/deck_pdf.py",
)
#: File names frozen wherever they appear.
FROZEN_NAMES = ("modulex_pairing.py", "modulex_signing.py", "ui-utils.js")

SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "venv", ".venv", "env", ".env", "site-packages",
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", "dist", "build",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str | None:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def today_stamp() -> str:
    return _dt.datetime.now().strftime("%Y%m%d")  # noqa: DTZ005 - local date names the backup folder


def rel_posix(path: Path, root: Path) -> str:
    try:
        return PurePosixPath(Path(path).resolve().relative_to(Path(root).resolve())).as_posix()
    except ValueError:
        return PurePosixPath(Path(path)).as_posix()


def is_frozen(relpath_from_project_root: str) -> bool:
    """True if the path (relative to the project root, any separator) is a frozen operator file."""
    rel = relpath_from_project_root.replace("\\", "/").strip("/")
    low = rel.lower()
    if any(low == f.lower() for f in FROZEN_RELPATHS):
        return True
    return PurePosixPath(rel).name.lower() in FROZEN_NAMES


def inside_static(path: Path | str) -> bool:
    """True if any component of the path is a folder named ``static`` (case-insensitive)."""
    return any(part.lower() == "static" for part in str(path).replace("\\", "/").split("/"))


def walk_files(root: Path, *, suffixes: tuple[str, ...] | None = None, names: tuple[str, ...] | None = None,
               max_depth: int = 8, max_files: int = 200_000) -> Iterator[Path]:
    """Bounded, deterministic walk (sorted) that skips caches, venvs and ``_backup_mag_*`` folders."""
    root = Path(root)
    if not root.is_dir():
        return
    seen = 0
    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack:
        current, depth = stack.pop()
        try:
            entries = sorted(os.scandir(current), key=lambda e: e.name, reverse=True)
        except OSError:
            continue
        for entry in entries:
            name = entry.name
            try:
                if entry.is_dir(follow_symlinks=False):
                    if name in SKIP_DIRS or name.lower() in SKIP_DIRS or name.startswith("_backup_mag_"):
                        continue
                    if depth + 1 <= max_depth:
                        stack.append((Path(entry.path), depth + 1))
                    continue
            except OSError:
                continue
            if suffixes and not name.lower().endswith(suffixes):
                continue
            if names and name not in names:
                continue
            seen += 1
            if seen > max_files:
                return
            yield Path(entry.path)


def read_text(path: Path) -> str:
    """UTF-8 text (BOM tolerated), CRLF kept as-is."""
    data = Path(path).read_bytes()
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    return data.decode("utf-8")


def write_json(path: Path, obj: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def kit_home() -> Path:
    """Where the Kit keeps its state, logs and keys (inside the Studio app home)."""
    from mxstudio.config import app_home

    return Path(os.environ.get("MXS_KIT_HOME") or app_home() / "kit")


def log_event(event: str, **fields: Any) -> None:
    """Append one JSON line to the Kit log. Never raises; never logs secrets (callers pass facts only)."""
    try:
        home = kit_home()
        home.mkdir(parents=True, exist_ok=True)
        line = json.dumps({"at": now_iso(), "event": event, **fields}, ensure_ascii=False, default=str)
        with open(home / "kit.log.jsonl", "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:  # noqa: BLE001 - logging must never break a Kit action
        pass
