"""On-demand payloads listed in ``installer/downloads.json`` (LibreOffice MSI, fonts, shapes, Node).

Rules:
* an entry is *pinned* only when its sha256 is 64 hex and no field contains ``TO-PIN``;
  the app never downloads an unpinned entry (build tooling may, with ``allow_unpinned``,
  and then only records the computed sha256 — it never pretends it was pinned);
* the Full (offline) flavour ships the bundled files under ``<app_dir>/offline/<offline_path>``
  and those are used first, re-verified against the same pin;
* zip payloads are extracted without path traversal;
* the font vault and the shape packs are *recipes* (``"recipe"`` key): assembled file by file
  from pins in the catalog by :mod:`mxstudio.update.assets`, not downloaded as one archive.
"""
from __future__ import annotations

import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any

from .download import Progress, Transport, download, verify_file
from .errors import IntegrityError, UpdateError

SCHEMA_ID = "mxs-downloads/1"
TO_PIN = "TO-PIN"
_REPO_FILE = Path(__file__).resolve().parents[2] / "installer" / "downloads.json"


def candidates() -> list[Path]:
    out: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        out.append(Path(meipass) / "mxstudio_data" / "downloads.json")
    out.append(_REPO_FILE)
    return out


def load(path: Path | None = None) -> dict[str, Any]:
    for candidate in ([path] if path else candidates()):
        if candidate and candidate.is_file():
            data = json.loads(candidate.read_text(encoding="utf-8"))
            if data.get("schema") != SCHEMA_ID:
                raise UpdateError("downloads_schema", "ملف التنزيلات مش بالشكل المتوقع.",
                                  f"downloads.json schema must be {SCHEMA_ID}")
            return data
    raise UpdateError("downloads_missing", "ملف التنزيلات downloads.json مش موجود.", "downloads.json was not found.")


def is_pinned(entry: dict[str, Any]) -> bool:
    if entry.get("recipe"):
        # assembled from per-file pins (mxstudio/update/assets.py); the recipe refuses any unpinned input
        from .assets import RECIPES  # noqa: PLC0415
        return entry["recipe"] in RECIPES
    if not re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256") or "")):
        return False
    return not any(TO_PIN in str(entry.get(key) or "") for key in ("url", "version", "sha256"))


def unpinned(manifest: dict[str, Any]) -> list[str]:
    """Names of entries that still carry TO-PIN (entries verified by other means are excluded)."""
    return sorted(name for name, entry in manifest.get("entries", {}).items()
                  if not entry.get("verify") and not is_pinned(entry))


def entry(manifest: dict[str, Any], name: str) -> dict[str, Any]:
    try:
        return manifest["entries"][name]
    except KeyError as exc:
        raise UpdateError("unknown_payload", f"مفيش تنزيل اسمه {name}.", f"No payload named {name}.") from exc


def offline_copy(app_dir: Path, item: dict[str, Any]) -> Path | None:
    rel = item.get("offline_path")
    if not rel:
        return None
    path = Path(app_dir) / "offline" / rel
    return path if path.is_file() else None


def _offline_record(app_dir: Path, name: str) -> dict[str, Any]:
    path = Path(app_dir) / "offline" / "offline_manifest.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("entries", {}).get(name) or {}
    except (OSError, ValueError):
        return {}


def fetch(name: str, dest_dir: Path, *, app_dir: Path | None = None, manifest: dict[str, Any] | None = None,
          transport: Transport | None = None, progress: Progress | None = None, digits: str = "arabic_indic",
          cancel=None) -> Path:
    """Return a verified local copy of payload ``name`` (offline copy first, else resumable download)."""
    manifest = manifest or load()
    item = entry(manifest, name)
    if item.get("recipe"):
        raise UpdateError("recipe_payload", f"«{item.get('label_ar', name)}» بتتجمّع من ملفات مثبّتة (assets) مش ملف واحد.",
                          f"{name} is assembled by mxstudio.update.assets.build_tree, not downloaded as one file")
    if app_dir and not is_pinned(item):
        # Full flavour built with --allow-unpinned: the installer's own offline_manifest.json
        # (part of the program, covered by the installer's sha256) records the computed hash.
        bundled = offline_copy(app_dir, item)
        recorded = _offline_record(app_dir, name)
        if bundled and recorded.get("sha256") and verify_file(bundled, recorded["sha256"], recorded.get("size"),
                                                              raise_on_fail=False):
            return bundled
    if not is_pinned(item):
        raise IntegrityError("unpinned",
                             f"«{item.get('label_ar', name)}» لسه ملوش رابط/بصمة مثبّتة (TO-PIN) — مش هننزّله. "
                             "استخدم النسخة الكاملة (Full) أو ثبّته يدوي.",
                             f"{item.get('label_en', name)} is not pinned yet (TO-PIN); it is not downloaded. "
                             "Use the Full installer or install it manually.")
    if app_dir:
        bundled = offline_copy(app_dir, item)
        if bundled and verify_file(bundled, item["sha256"], item.get("size"), raise_on_fail=False):
            return bundled
    dest = Path(dest_dir) / item["file_name"]
    return download(item["url"], dest, sha256=item["sha256"], size=item.get("size"), transport=transport,
                    progress=progress, label_ar=item.get("label_ar", name), label_en=item.get("label_en", name),
                    digits=digits, cancel=cancel)


def safe_extract(archive: Path, target: Path) -> list[Path]:
    """Extract a zip refusing absolute paths and ``..`` components."""
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    root = target.resolve()
    written: list[Path] = []
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            name = info.filename.replace("\\", "/")
            if name.startswith("/") or re.match(r"^[A-Za-z]:", name) or ".." in name.split("/"):
                raise UpdateError("unsafe_zip", "الملف المضغوط فيه مسار مش آمن.", f"Unsafe path in archive: {name}")
            out = (target / name).resolve()
            if root not in out.parents and out != root:
                raise UpdateError("unsafe_zip", "الملف المضغوط فيه مسار مش آمن.", f"Unsafe path in archive: {name}")
            if info.is_dir():
                out.mkdir(parents=True, exist_ok=True)
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(out, "wb") as dst:
                while True:
                    block = src.read(1 << 20)
                    if not block:
                        break
                    dst.write(block)
            written.append(out)
    return written


def expand(template: str, **values: Any) -> str:
    out = template
    for key, value in values.items():
        out = out.replace("{" + key + "}", str(value))
    return out
