"""Patch model and the hook engine (insert / remove marker blocks).

Rules enforced:
* a hook is a few lines between ``# >>> MODULEX_MAG <id> >>>`` and ``# <<< MODULEX_MAG <id> <<<``;
* every hook body starts with an env-flag check that defaults OFF;
* hook positions are found with :mod:`ast` (function body start after the docstring, or module
  end before ``if __name__ == "__main__":``) — never by fuzzy text matching;
* the patched file must still compile, line endings and a UTF-8 BOM are preserved;
* payloads are additive files in a new package folder; vendored ``mxlibs`` are copied verbatim
  after their MANIFEST.json sha256 list verifies (source and destination).
"""
from __future__ import annotations

import ast
import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PAYLOADS = Path(__file__).resolve().parent / "payloads"


class PatchError(RuntimeError):
    pass


@dataclass(frozen=True)
class Hook:
    system: str
    file: str            # relative to the system folder, or "@app_object" (resolved from the anchor)
    where: str           # "func_start:<name>" | "module_end"
    body: str            # unindented code; may use {app_var}


@dataclass(frozen=True)
class Payload:
    system: str
    dest: str                                    # package folder relative to the system folder
    sources: tuple[Path, ...]                    # files and/or folders copied into dest
    libs: tuple[str, ...] = ()                   # mxlibs copied to dest/vendor/<lib>
    config: Callable[[dict], dict] | None = None  # -> dest/mag_config.json


@dataclass(frozen=True)
class Patch:
    id: str
    flag: str
    title_ar: str
    title_en: str
    summary_en: str
    anchors: tuple[str, ...]
    hooks: tuple[Hook, ...]
    payloads: tuple[Payload, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def systems(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys([h.system for h in self.hooks] + [p.system for p in self.payloads]))


# ---------------------------------------------------------------- markers ----

def begin_marker(pid: str) -> str:
    return f"# >>> MODULEX_MAG {pid} >>>"


def end_marker(pid: str) -> str:
    return f"# <<< MODULEX_MAG {pid} <<<"


def has_markers(text: str, pid: str) -> bool:
    return begin_marker(pid) in text or end_marker(pid) in text


def any_mag_markers(text: str) -> list[str]:
    return sorted(set(re.findall(r"# >>> MODULEX_MAG (\S+) >>>", text)))


def _split_bom(data: bytes) -> tuple[bytes, str]:
    if data.startswith(b"\xef\xbb\xbf"):
        return b"\xef\xbb\xbf", data[3:].decode("utf-8")
    return b"", data.decode("utf-8")


def render_block(pid: str, body: str, indent: str, newline: str, ctx: dict[str, Any]) -> str:
    lines = [begin_marker(pid)] + body.format(**ctx).strip("\n").split("\n") + [end_marker(pid)]
    return "".join((indent + line if line.strip() else "") + newline for line in lines)


def insert_hook(data: bytes, hook: Hook, pid: str, ctx: dict[str, Any]) -> bytes:
    try:
        bom, text = _split_bom(data)
    except UnicodeDecodeError as exc:
        raise PatchError(f"{hook.file}: not UTF-8") from exc
    if has_markers(text, pid):
        raise PatchError(f"{hook.file}: markers for {pid} already present")
    newline = "\r\n" if "\r\n" in text else "\n"
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        raise PatchError(f"{hook.file}: does not parse ({exc.msg})") from exc
    lines = text.splitlines(keepends=True)
    if hook.where.startswith("func_start:"):
        name = hook.where.split(":", 1)[1]
        defs = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
        if len(defs) != 1:
            raise PatchError(f"{hook.file}: expected exactly one top-level def {name}, found {len(defs)}")
        fn = defs[0]
        first = fn.body[0]
        if first.lineno == fn.lineno:
            raise PatchError(f"{hook.file}: {name} is a one-line function")
        is_doc = isinstance(first, ast.Expr) and isinstance(getattr(first, "value", None), ast.Constant) \
            and isinstance(first.value.value, str)
        ref_line = lines[first.lineno - 1]
        indent = ref_line[: len(ref_line) - len(ref_line.lstrip())]
        if is_doc:
            at = first.end_lineno
        else:
            deco = getattr(first, "decorator_list", None) or []
            at = min([first.lineno] + [d.lineno for d in deco]) - 1
    elif hook.where == "module_end":
        indent = ""
        mains = [n for n in tree.body if isinstance(n, ast.If) and "__name__" in ast.unparse(n.test)
                 and "__main__" in ast.unparse(n.test)]
        if mains:
            at = mains[0].lineno - 1
        else:
            at = len(lines)
            if lines and not lines[-1].endswith(("\n", "\r")):
                lines[-1] = lines[-1] + newline
    else:
        raise PatchError(f"unknown hook position {hook.where}")
    block = render_block(pid, hook.body, indent, newline, ctx)
    new_text = "".join(lines[:at]) + block + "".join(lines[at:])
    try:
        compile(new_text, hook.file, "exec")
    except SyntaxError as exc:
        raise PatchError(f"{hook.file}: patched text does not compile ({exc.msg})") from exc
    return bom + new_text.encode("utf-8")


def remove_hook(data: bytes, pid: str) -> bytes:
    bom, text = _split_bom(data)
    lines = text.splitlines(keepends=True)
    out, inside = [], False
    for line in lines:
        stripped = line.strip()
        if stripped == begin_marker(pid):
            inside = True
            continue
        if inside and stripped == end_marker(pid):
            inside = False
            continue
        if not inside:
            out.append(line)
    return bom + "".join(out).encode("utf-8")


# ---------------------------------------------------------------- payload files ----

def _iter_source_files(src: Path) -> list[tuple[str, Path]]:
    if src.is_file():
        return [(src.name, src)]
    out = []
    for path in sorted(src.rglob("*")):
        if path.is_dir() or "__pycache__" in path.parts or path.suffix in (".pyc", ".pyo"):
            continue
        out.append((path.relative_to(src).as_posix(), path))
    return out


def mxlibs_dir() -> Path:
    env = os.environ.get("MXS_MXLIBS_DIR")
    return Path(env) if env else Path(__file__).resolve().parents[3] / "mxlibs"


def lib_manifest_files(lib_dir: Path) -> dict[str, str]:
    """``{relpath: sha256}`` from ``MANIFEST.json`` (dict form or list of {path, sha256})."""
    manifest = json.loads((lib_dir / "MANIFEST.json").read_text(encoding="utf-8"))
    files = manifest.get("files")
    if isinstance(files, dict):
        rows = files.items()
    elif isinstance(files, list):
        rows = [(f.get("path") or f.get("file"), f.get("sha256")) for f in files]
    else:
        raise PatchError(f"{lib_dir.name}: MANIFEST.json has no files list")
    out = {}
    for rel, digest in rows:
        rel = str(rel).replace("\\", "/")
        if not rel or rel.startswith("/") or ".." in rel.split("/") or not re.fullmatch(r"[0-9a-f]{64}", str(digest)):
            raise PatchError(f"{lib_dir.name}: bad manifest row {rel!r}")
        out[rel] = digest
    return out


def lib_files(name: str) -> dict[str, bytes]:
    """Verified bytes of a vendored mxlib (manifest + every listed file). Unlisted .py files refuse."""
    import hashlib

    lib_dir = mxlibs_dir() / name
    if not (lib_dir / "MANIFEST.json").is_file():
        raise PatchError(f"{name}: not available (no {lib_dir}/MANIFEST.json) — mxlibs not shipped")
    listed = lib_manifest_files(lib_dir)
    out = {"MANIFEST.json": (lib_dir / "MANIFEST.json").read_bytes()}
    for rel, digest in listed.items():
        data = (lib_dir / rel).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise PatchError(f"{name}/{rel}: sha256 differs from MANIFEST.json")
        out[rel] = data
    unlisted = [p.relative_to(lib_dir).as_posix() for p in lib_dir.rglob("*.py")
                if "__pycache__" not in p.parts and p.relative_to(lib_dir).as_posix() not in listed]
    if unlisted:
        raise PatchError(f"{name}: python files not in MANIFEST.json: {unlisted[:5]}")
    return out


def payload_files(payload: Payload, ctx: dict[str, Any]) -> dict[str, bytes]:
    """``{relpath-in-system: bytes}`` for one payload (sources + vendored libs + config)."""
    out: dict[str, bytes] = {}
    for src in payload.sources:
        for rel, path in _iter_source_files(src):
            out[f"{payload.dest}/{rel}"] = path.read_bytes()
    if payload.libs:
        out[f"{payload.dest}/vendor/__init__.py"] = b'"""Vendored ModuleX Magazine libraries (verbatim, see MANIFEST.json)."""\n'
    for lib in payload.libs:
        for rel, data in lib_files(lib).items():
            out[f"{payload.dest}/vendor/{lib}/{rel}"] = data
    if payload.config:
        cfg = payload.config(ctx)
        out[f"{payload.dest}/mag_config.json"] = (json.dumps(cfg, ensure_ascii=False, indent=1, sort_keys=True)
                                                  + "\n").encode("utf-8")
    return out


def module_path(dest: str) -> str:
    return dest.strip("/").replace("/", ".")
