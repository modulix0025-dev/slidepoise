"""Asset bundles built from pinned sources: the font vault and the shape packs.

Neither bundle is a single file somebody uploaded somewhere. Each is *assembled* from
files whose sha256 is already pinned in the repository:

* ``font_vault`` — every font file (and its licence file) of every family the licence
  ledger allows to ship with the Studio, from google/fonts at the pinned commit
  (``catalog/fonts/catalog.json`` + ``font_license_ledger.json``);
* ``shape_packs`` — the official ``@iconify-json/<set>`` npm tarballs listed in
  ``catalog/shapes/packs.json`` (sha256 + npm's sha512 integrity), only sets on the print
  allowlist, with the excluded prefixes and version caps of ``catalog/shapes/sources.json``.

The same recipe serves the Full installer (built once in CI into ``offline/<dir>``) and
the Online flavour (the Doctor's «إصلاح» builds it into the app home on demand). Every
input goes through the verified, resumable downloader; nothing unverified is written.

CLI (``mxstudio-cli.exe assets`` / ``python -m mxstudio assets``), JSON on stdout::

    status                       what is present (Full offline copy, app home) and installed
    fetch fonts|shapes           build the bundle into the app home from the pinned sources
    install-fonts                install the vault fonts for the current Windows user (no admin)
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import tarfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .download import Progress, Transport, download, verify_file
from .errors import UpdateError

ROOT = Path(__file__).resolve().parents[2]
RECIPES = ("font_vault", "shape_packs")
MANIFEST = "MANIFEST.json"
FONT_SUFFIXES = (".ttf", ".otf")
#: files taken from each @iconify-json tarball (everything else in it is JS glue)
ICONIFY_MEMBERS = ("icons.json", "info.json", "metadata.json")


def _catalog_dir() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass and (Path(meipass) / "catalog").is_dir():
        return Path(meipass) / "catalog"
    return ROOT / "catalog"


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Input:
    url: str
    sha256: str
    size: int | None
    path: str  # where the verified file lands inside the bundle (fonts) or its cache name (tarballs)
    licence: str
    note: str = ""


def _pinned(sha: str) -> bool:
    return len(sha) == 64 and all(c in "0123456789abcdef" for c in sha)


# ------------------------------------------------------------------ recipes
def font_inputs() -> list[Input]:
    cat = _catalog_dir() / "fonts"
    catalog, ledger = _json(cat / "catalog.json"), _json(cat / "font_license_ledger.json")
    if catalog["source"]["commit"] != ledger["commit"]:
        raise UpdateError("assets_mismatch", "كتالوج الخطوط ودفتر التراخيص مش على نفس النسخة.",
                          "font catalog and licence ledger are pinned to different commits")
    allowed = {f["family"]: f for f in ledger["families"] if f["bundle_with_studio"]["allowed"]}
    out: list[Input] = []
    for family in catalog["families"]:
        rule = allowed.get(family["family"])
        if rule is None:
            continue
        folder = family["repo_dir"]
        for item in family["files"]:
            out.append(Input(item["url"], item["sha256"], item.get("bytes"), f"{folder}/{item['file']}",
                             family["licence"], family["family"]))
        lic = family["licence_file"]
        out.append(Input(lic["url"], lic["sha256"], None, f"{folder}/{lic['file']}", family["licence"],
                         family["family"]))
    return out


def shape_sets() -> list[dict]:
    """The pinned Iconify sets, each re-checked against the licence policy and the source rules."""
    cat = _catalog_dir()
    packs = _json(cat / "shapes" / "packs.json")
    sources = _json(cat / "shapes" / "sources.json")
    policy = _json(cat / "licence_policy.json")
    excluded = sources.get("iconify_excluded_prefixes", {})
    caps = sources.get("iconify_version_caps", {})
    sets = []
    for item in packs["sets"]:
        prefix = item["prefix"]
        if prefix in excluded:
            raise UpdateError("assets_licence", f"مجموعة {prefix} مستبعدة.", f"set {prefix} is excluded: {excluded[prefix]}")
        if item["licence"] not in policy["print_asset_allowlist"]:
            raise UpdateError("assets_licence", f"رخصة {prefix} مش مسموحة للطباعة.",
                              f"set {prefix} licence {item['licence']} is not on the print allowlist")
        cap = caps.get(prefix)
        if cap is not None and _version(item.get("set_version") or "999") > _version(cap):
            raise UpdateError("assets_licence", f"إصدار {prefix} أعلى من المسموح.",
                              f"set {prefix} version {item.get('set_version')} is above the {cap} cap")
        sets.append(item)
    return sets


def _version(text: str) -> tuple[int, ...]:
    return tuple(int("".join(ch for ch in part if ch.isdigit()) or 0) for part in str(text).split("."))


def shape_inputs() -> list[Input]:
    return [Input(s["url"], s["sha256"], s.get("size"), f"{s['prefix']}.tgz", s["licence"], s["name"])
            for s in shape_sets()]


def inputs(name: str) -> list[Input]:
    if name == "font_vault":
        found = font_inputs()
    elif name == "shape_packs":
        found = shape_inputs()
    else:
        raise UpdateError("unknown_payload", f"مفيش حزمة اسمها {name}.", f"No asset recipe named {name}.")
    bad = [i.url for i in found if not _pinned(i.sha256)]
    if bad:
        raise UpdateError("unpinned", "فيه ملفات في الحزمة من غير بصمة مثبّتة.", f"unpinned inputs: {bad[:3]}")
    return found


def version(name: str) -> str:
    if name == "font_vault":
        return "google/fonts@" + _json(_catalog_dir() / "fonts" / "catalog.json")["source"]["commit"][:12]
    packs = _json(_catalog_dir() / "shapes" / "packs.json")
    return "iconify-json@" + packs["retrieved_at"]


# ------------------------------------------------------------------ building
def _safe_rel(rel: str) -> str:
    parts = rel.replace("\\", "/").split("/")
    if rel.startswith("/") or any(p in ("", ".", "..") or ":" in p for p in parts):
        raise UpdateError("unsafe_path", "مسار مش آمن في الحزمة.", f"unsafe path in bundle: {rel}")
    return "/".join(parts)


def _write(target: Path, rel: str, data: bytes) -> None:
    out = target / _safe_rel(rel)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".part")
    tmp.write_bytes(data)
    os.replace(tmp, out)


def _iconify_files(tarball: bytes, prefix: str) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as tar:
        for member in tar.getmembers():
            name = member.name.replace("\\", "/")
            if not member.isfile() or name.count("/") != 1 or not name.startswith("package/"):
                continue
            base = name.split("/", 1)[1]
            if base in ICONIFY_MEMBERS:
                handle = tar.extractfile(member)
                if handle is not None:
                    out[base] = handle.read()
    if "icons.json" not in out or "info.json" not in out:
        raise UpdateError("assets_broken", f"حزمة {prefix} ناقصة.", f"@iconify-json/{prefix} lacks icons.json/info.json")
    info = json.loads(out["info.json"])
    icons = json.loads(out["icons.json"])
    if icons.get("prefix") != prefix:
        raise UpdateError("assets_broken", f"حزمة {prefix} مش هي.", f"tarball prefix {icons.get('prefix')!r} != {prefix!r}")
    return out | {"_licence": (info.get("license") or {}).get("spdx", "")}


def build_tree(name: str, target: Path, *, cache_dir: Path | None = None, transport: Transport | None = None,
               progress: Progress | None = None, digits: str = "arabic_indic") -> dict[str, Any]:
    """Assemble bundle ``name`` into folder ``target`` from its pinned inputs; returns a summary.

    Each input is downloaded through the verified downloader into ``cache_dir`` (resumable),
    then copied/extracted into ``target``; ``MANIFEST.json`` lists every file with its sha256
    and source. Already-present verified inputs are not downloaded again.
    """
    target = Path(target)
    cache = Path(cache_dir) if cache_dir else target.parent / f".{name}-cache"
    items = inputs(name)
    files: list[dict[str, Any]] = []
    for index, item in enumerate(items, 1):
        cached = cache / item.sha256[:2] / f"{item.sha256}-{Path(item.path).name}"
        if not (cached.is_file() and verify_file(cached, item.sha256, item.size, raise_on_fail=False)):
            download(item.url, cached, sha256=item.sha256, size=item.size, transport=transport, progress=progress,
                     label_ar=f"{index}/{len(items)} {Path(item.path).name}",
                     label_en=f"{index}/{len(items)} {Path(item.path).name}", digits=digits)
        data = cached.read_bytes()
        if name == "font_vault":
            _write(target, item.path, data)
            files.append({"path": item.path, "sha256": item.sha256, "source": item.url, "licence": item.licence,
                          "family": item.note})
            continue
        prefix = item.path[:-len(".tgz")]
        extracted = _iconify_files(data, prefix)
        if extracted.pop("_licence") != item.licence:
            raise UpdateError("assets_licence", f"رخصة {prefix} جوه الحزمة مختلفة عن المثبّتة.",
                              f"licence inside @iconify-json/{prefix} differs from the pinned {item.licence}")
        for base, blob in sorted(extracted.items()):
            rel = f"iconify/{prefix}/{base}"
            _write(target, rel, blob)
            files.append({"path": rel, "sha256": hashlib.sha256(blob).hexdigest(), "source": item.url,
                          "source_sha256": item.sha256, "licence": item.licence, "set": item.note})
    manifest = {"schema": "mxs-asset-bundle/1", "recipe": name, "version": version(name), "files": files}
    _write(target, MANIFEST, (json.dumps(manifest, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    return {"recipe": name, "version": manifest["version"], "files": len(files), "inputs": len(items)}


def tree_status(folder: Path) -> dict[str, Any]:
    """Facts about a built bundle folder: manifest present, files present and unchanged."""
    folder = Path(folder)
    path = folder / MANIFEST
    if not path.is_file():
        return {"present": False, "folder": str(folder)}
    manifest = _json(path)
    missing, changed = [], []
    for item in manifest["files"]:
        f = folder / item["path"]
        if not f.is_file():
            missing.append(item["path"])
        elif f.stat().st_size < 64 * 1024 * 1024 and hashlib.sha256(f.read_bytes()).hexdigest() != item["sha256"]:
            changed.append(item["path"])
    return {"present": True, "folder": str(folder), "recipe": manifest.get("recipe"), "version": manifest.get("version"),
            "files": len(manifest["files"]), "missing": missing[:20], "changed": changed[:20],
            "ok": not missing and not changed}


# ------------------------------------------------------------------ where bundles live on a PC
def bundle_dirs(name: str, *, app_dir: Path, home: Path) -> list[Path]:
    """Full installer copy first (read-only, inside the program), then the app home (Online/Doctor)."""
    sub = "fonts" if name == "font_vault" else "shapes"
    return [Path(app_dir) / "offline" / sub, Path(home) / sub]


def font_files(folders: list[Path]) -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()
    for folder in folders:
        if not folder.is_dir():
            continue
        for path in sorted(folder.rglob("*")):
            if path.suffix.lower() in FONT_SUFFIXES and path.is_file() and path.name.casefold() not in seen:
                seen.add(path.name.casefold())
                out.append(path)
    return out


def install_vault_fonts(files: list[Path], backend=None) -> dict[str, Any]:
    """Install vault fonts for the current Windows user (no admin): copy + HKCU registry + AddFontResourceExW +
    WM_FONTCHANGE. File by file: one failure never stops the others; identical files are not copied again."""
    from mxstudio.fonts.install import install_fonts_each  # noqa: PLC0415

    if backend is None:
        if sys.platform != "win32":
            return {"ok": True, "skipped": "not windows", "installed": 0, "files": len(files)}
        from mxstudio.fonts.install import WindowsBackend  # noqa: PLC0415
        backend = WindowsBackend()
    outcome = install_fonts_each(files, "user", backend)
    failed = outcome["failed"]
    powerpoint_running = False
    try:
        powerpoint_running = bool(backend.process_running("POWERPNT.EXE"))
    except Exception:  # noqa: BLE001 - only a hint
        pass
    import time  # noqa: PLC0415
    return {"ok": not failed, "installed": len(outcome["results"]), "files": len(files),
            "identical_skipped": outcome["identical_skipped"], "failed": failed[:20], "failed_count": len(failed),
            "registered": sorted({r.registry_value for r in outcome["results"]})[:2000],
            "installed_at": time.time(), "powerpoint_running_at_install": powerpoint_running}


# ------------------------------------------------------------------ CLI
def _context():
    from mxstudio.config import app_home  # noqa: PLC0415
    from mxstudio.doctor.context import program_dir  # noqa: PLC0415
    return program_dir(), app_home()


def status(app_dir: Path, home: Path) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name in RECIPES:
        out[name] = [tree_status(p) for p in bundle_dirs(name, app_dir=app_dir, home=home)]
    out["font_files"] = len(font_files(bundle_dirs("font_vault", app_dir=app_dir, home=home)))
    return out


def main(argv: list[str] | None = None, *, emit: Callable[[dict], None] | None = None) -> int:
    import argparse  # noqa: PLC0415

    parser = argparse.ArgumentParser(prog="mxstudio assets")
    parser.add_argument("cmd", choices=["status", "fetch", "install-fonts"])
    parser.add_argument("what", nargs="?", choices=["fonts", "shapes"])
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    app_dir, home = _context()

    def _emit(result: dict) -> None:
        text = json.dumps(result, ensure_ascii=False, indent=1)
        if args.out:
            Path(args.out).write_text(text, encoding="utf-8")
        print(text)

    emit = emit or _emit
    try:
        if args.cmd == "status":
            result = {"ok": True, **status(app_dir, home)}
        elif args.cmd == "fetch":
            name = "font_vault" if args.what == "fonts" else "shape_packs"
            target = bundle_dirs(name, app_dir=app_dir, home=home)[1]
            result = {"ok": True, **build_tree(name, target, cache_dir=home / "downloads" / "assets")}
        else:
            result = install_vault_fonts(font_files(bundle_dirs("font_vault", app_dir=app_dir, home=home)))
    except UpdateError as err:
        result = {"ok": False, "code": err.code, "ar": err.ar, "en": err.en}
    emit(result)
    return 0 if result.get("ok") else 1

