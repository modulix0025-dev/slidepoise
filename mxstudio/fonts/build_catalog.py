"""Build ``catalog/fonts/catalog.json`` from a google/fonts checkout at the pinned commit.

Rule: every fact is re-derived from the bytes at the pinned commit — the
appendix TSV contributes only the curated columns (id, roles, themes,
observation) and its *claimed* licence/flags, which are compared with what the
files say and any disagreement is written down as drift. The builder refuses a
checkout at any other commit, and refuses a family whose directory, font files
or licence file is missing.

Usage::

    python -m mxstudio.fonts.build_catalog --checkout <google-fonts> [--out catalog/fonts/catalog.json]

The output is deterministic: no timestamps except the explicit
``--retrieved-at`` date, sorted keys, files sorted by name.
"""
from __future__ import annotations

import argparse
import codecs
import csv
import hashlib
import json
import re
import sys
from pathlib import Path

from fontTools.ttLib import TTFont

from mxstudio.fonts.paths import (APPENDIX_TSV, CATALOG_JSON, PHASE0_MEASURED, PINNED_COMMIT, REPO_URL,
                                  raw_url)
from mxstudio.fonts.rfn import parse_reserved_font_names

SCHEMA = "mx.fonts.catalog/1"
FONT_SUFFIXES = (".ttf", ".otf")
COLOUR_TABLES = ("COLR", "CPAL", "SVG ", "CBDT", "CBLC", "sbix")
LICENCE_SPDX = {"OFL": "OFL-1.1", "APACHE2": "Apache-2.0", "UFL": "UFL-1.0"}
LICENCE_FILES = {"OFL-1.1": "OFL.txt", "Apache-2.0": "LICENSE.txt", "UFL-1.0": "UFL.txt"}


class CatalogBuildError(RuntimeError):
    """A named refusal while building the catalog."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def checkout_commit(checkout: Path) -> str:
    """HEAD of a git checkout, read from the files (no git process needed)."""
    git = checkout / ".git"
    if git.is_file():  # worktree: "gitdir: <path>"
        git = Path(git.read_text(encoding="utf-8").split(":", 1)[1].strip())
    head = (git / "HEAD").read_text(encoding="utf-8").strip()
    if not head.startswith("ref:"):
        return head
    ref = head.split(":", 1)[1].strip()
    ref_file = git / ref
    if ref_file.is_file():
        return ref_file.read_text(encoding="utf-8").strip()
    packed = git / "packed-refs"
    if packed.is_file():
        for line in packed.read_text(encoding="utf-8").splitlines():
            if line.endswith(" " + ref):
                return line.split(" ", 1)[0]
    raise CatalogBuildError(f"cannot resolve {ref} in {git}")


def read_appendix(tsv: Path = APPENDIX_TSV) -> list[dict]:
    with open(tsv, encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    out = []
    for row in rows:
        out.append({
            "id": row["id"].strip(), "family": row["family"].strip(), "script": row["script"].strip(),
            "repo_dir": row["repo_dir"].strip(),
            "roles": [r for r in (row.get("roles") or "").split(",") if r],
            "themes": [t for t in (row.get("themes") or "").split(",") if t],
            "brief_licence": (row.get("licence") or "").strip(),
            "brief_flags": sorted((row.get("flags") or "").split()),
            "observation": (row.get("observation") or "").strip(),
        })
    return out


_TOP_FIELD = re.compile(r'^(?P<key>[a-z_]+):\s*(?P<value>"(?:[^"\\]|\\.)*"|[\w.\-]+)\s*$')


def _unquote(value: str) -> str:
    """Text-proto string literal → str (C escapes, octal bytes are UTF-8)."""
    return codecs.escape_decode(value[1:-1].encode("utf-8"))[0].decode("utf-8", "replace")


def parse_metadata_pb(text: str) -> dict:
    """Top-level scalar fields of a METADATA.pb text proto (repeated ones become lists) + font blocks."""
    meta: dict = {"subsets": [], "fonts": []}
    depth = 0
    current: dict | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.endswith("{"):
            depth += 1
            if depth == 1 and line.startswith("fonts"):
                current = {}
            continue
        if line == "}":
            depth -= 1
            if depth == 0 and current is not None:
                meta["fonts"].append(current)
                current = None
            continue
        match = _TOP_FIELD.match(line)
        if not match:
            continue
        key, value = match.group("key"), match.group("value")
        value = _unquote(value) if value.startswith('"') else value
        if depth == 0:
            if key == "subsets":
                meta["subsets"].append(value)
            else:
                meta[key] = value
        elif depth == 1 and current is not None:
            current[key] = value
    return meta


def _name(font: TTFont, name_id: int) -> str:
    record = font["name"].getName(name_id, 3, 1, 0x409) or font["name"].getName(name_id, 1, 0, 0)
    return str(record) if record is not None else ""


def font_file_facts(path: Path, repo_dir: str, commit: str) -> dict:
    font = TTFont(str(path), lazy=False)
    try:
        facts = {
            "file": path.name, "url": raw_url(repo_dir, path.name, commit), "sha256": sha256_file(path),
            "bytes": path.stat().st_size, "fsType": int(font["OS/2"].fsType),
            "weight_class": int(font["OS/2"].usWeightClass),
            "italic": bool(font["OS/2"].fsSelection & 1), "upem": int(font["head"].unitsPerEm),
            "glyphs": len(font.getGlyphOrder()), "variable": "fvar" in font,
            "color_tables": [tag.strip() for tag in COLOUR_TABLES if tag in font],
            "names": {str(i): _name(font, i) for i in (1, 2, 4, 6, 16, 17) if _name(font, i)},
            "outline": "CFF" if ("CFF " in font or "CFF2" in font) else "TrueType",
        }
        if "COLR" in font:
            facts["colr_version"] = int(font["COLR"].version)
        if facts["variable"]:
            fvar = font["fvar"]
            facts["axes"] = {a.axisTag: [a.minValue, a.defaultValue, a.maxValue] for a in fvar.axes}
            facts["named_instances"] = [
                {"subfamily": str(font["name"].getDebugName(inst.subfamilyNameID) or ""),
                 "coordinates": {k: float(v) for k, v in sorted(inst.coordinates.items())}}
                for inst in fvar.instances]
        return facts
    finally:
        font.close()


def _measured_index(measured_path: Path | None) -> dict:
    if not measured_path or not measured_path.is_file():
        return {}
    data = json.loads(measured_path.read_text(encoding="utf-8"))
    return {fam["id"]: fam for fam in data.get("families", [])}


def build_family(row: dict, checkout: Path, commit: str, measured: dict | None = None) -> dict:
    folder = checkout / row["repo_dir"]
    if not folder.is_dir():
        raise CatalogBuildError(f"{row['id']} {row['family']}: directory {row['repo_dir']} missing at {commit}")
    metadata_path = folder / "METADATA.pb"
    meta = parse_metadata_pb(metadata_path.read_text(encoding="utf-8")) if metadata_path.is_file() else {}
    licence = LICENCE_SPDX.get(meta.get("license", row["brief_licence"]), meta.get("license", "UNKNOWN"))
    licence_name = LICENCE_FILES.get(licence)
    licence_path = folder / licence_name if licence_name else None
    if licence_path is None or not licence_path.is_file():
        raise CatalogBuildError(f"{row['id']} {row['family']}: licence file missing ({licence})")
    licence_text = licence_path.read_text(encoding="utf-8", errors="replace")
    rfns = parse_reserved_font_names(licence_text) if licence == "OFL-1.1" else []
    font_paths = sorted(p for p in folder.iterdir() if p.suffix.lower() in FONT_SUFFIXES)
    if not font_paths:
        raise CatalogBuildError(f"{row['id']} {row['family']}: no font files in {row['repo_dir']}")
    files = [font_file_facts(p, row["repo_dir"], commit) for p in font_paths]
    notice = folder / "NOTICE.txt" if (folder / "NOTICE.txt").is_file() else (
        folder / "NOTICE" if (folder / "NOTICE").is_file() else None)
    is_colour = any(f["color_tables"] for f in files)
    is_variable = any(f["variable"] for f in files)
    flags = sorted({*(["COLOR"] if is_colour else []), *(["VAR"] if is_variable else []),
                    *(["RFN"] if rfns else [])})
    family_names = sorted({f["names"].get("16") or f["names"].get("1", "") for f in files})
    drift = []
    if row["brief_flags"] != flags:
        drift.append({"field": "flags", "appendix": row["brief_flags"], "measured": flags})
    if LICENCE_SPDX.get(row["brief_licence"], row["brief_licence"]) != licence:
        drift.append({"field": "licence", "appendix": row["brief_licence"], "measured": licence})
    if meta.get("name") and meta["name"] != row["family"]:
        drift.append({"field": "family", "appendix": row["family"], "metadata": meta["name"]})
    prior = (measured or {}).get(row["id"])
    if prior:
        if prior.get("reserved_font_names", []) != rfns:
            drift.append({"field": "reserved_font_names", "phase0": prior.get("reserved_font_names", []),
                          "measured": rfns})
        prior_files = {f["file"]: f for f in prior.get("files", [])}
        for item in files:
            before = prior_files.get(item["file"])
            if before is None:
                drift.append({"field": "file", "file": item["file"], "phase0": None})
            elif before.get("sha256") != item["sha256"]:
                drift.append({"field": "sha256", "file": item["file"], "phase0": before.get("sha256"),
                              "measured": item["sha256"]})
            elif before.get("fsType") != item["fsType"]:
                drift.append({"field": "fsType", "file": item["file"], "phase0": before.get("fsType"),
                              "measured": item["fsType"]})
        for missing in sorted(set(prior_files) - {f["file"] for f in files}):
            drift.append({"field": "file", "file": missing, "measured": None})
    return {
        "id": row["id"], "family": row["family"], "script": row["script"], "repo_dir": row["repo_dir"],
        "roles": row["roles"], "themes": row["themes"], "observation": row["observation"],
        "brief_licence": row["brief_licence"], "brief_flags": row["brief_flags"],
        "licence": licence,
        "licence_file": {"file": licence_path.name, "url": raw_url(row["repo_dir"], licence_path.name, commit),
                         "sha256": sha256_file(licence_path)},
        "notice_file": ({"file": notice.name, "url": raw_url(row["repo_dir"], notice.name, commit),
                         "sha256": sha256_file(notice)} if notice else None),
        "reserved_font_names": rfns,
        "flags": flags, "is_variable": is_variable, "is_colour": is_colour,
        "name_table_families": family_names,
        "metadata": {key: meta[key] for key in ("name", "designer", "license", "category", "primary_script",
                                                 "date_added") if key in meta} | {"subsets": meta.get("subsets", [])},
        "files": files,
        "drift": drift,
    }


def build_catalog(checkout: Path, *, tsv: Path = APPENDIX_TSV, commit: str = PINNED_COMMIT,
                  retrieved_at: str = "2026-10-11", measured_path: Path | None = PHASE0_MEASURED,
                  verify_commit: bool = True) -> dict:
    checkout = Path(checkout)
    if verify_commit:
        head = checkout_commit(checkout)
        if head != commit:
            raise CatalogBuildError(f"checkout is at {head}, the catalog is pinned to {commit}")
    rows = read_appendix(tsv)
    measured = _measured_index(measured_path)
    families = [build_family(row, checkout, commit, measured) for row in rows]
    files = [f for fam in families for f in fam["files"]]
    return {
        "schema": SCHEMA,
        "source": {"repo": REPO_URL, "commit": commit, "retrieved_at": retrieved_at,
                   "raw_url_form": "https://raw.githubusercontent.com/google/fonts/<commit>/<repo_dir>/<file>"
                                   " (path segments percent-encoded: [ → %5B, ] → %5D, , → %2C)",
                   "appendix": "docs/mag/catalog/fonts_appendix_f.tsv",
                   "appendix_sha256": sha256_file(tsv)},
        "counts": {
            "families": len(families), "files": len(files), "bytes": sum(f["bytes"] for f in files),
            "arabic": sum(fam["script"] == "AR" for fam in families),
            "latin": sum(fam["script"] == "EN" for fam in families),
            "ofl": sum(fam["licence"] == "OFL-1.1" for fam in families),
            "apache": sum(fam["licence"] == "Apache-2.0" for fam in families),
            "variable": sum(fam["is_variable"] for fam in families),
            "colour": sum(fam["is_colour"] for fam in families),
            "rfn": sum(bool(fam["reserved_font_names"]) for fam in families),
            "fsType_nonzero": sorted({fam["family"] for fam in families for f in fam["files"] if f["fsType"]}),
            "families_with_drift": sum(bool(fam["drift"]) for fam in families),
        },
        "families": families,
    }


def write_json(data: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--checkout", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=CATALOG_JSON)
    parser.add_argument("--retrieved-at", default="2026-10-11")
    args = parser.parse_args(argv)
    catalog = build_catalog(args.checkout, retrieved_at=args.retrieved_at)
    write_json(catalog, args.out)
    print(json.dumps(catalog["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
