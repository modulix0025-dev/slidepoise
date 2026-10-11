"""Phase 0 — re-derive the Appendix F font facts from a google/fonts checkout.

Usage:
    python tools/phase0/measure_font_catalog.py <google-fonts-checkout> <catalog.tsv> <out.json>

Reads each family's METADATA.pb (file list), hashes every file, and measures with
fontTools + HarfBuzz: OS/2.fsType, fvar axes/instances, colour tables, Arabic
coverage (36 base letters, 8 harakat, Arabic-Indic digits, punctuation), GPOS
mark/mkmk, licence kind, Reserved Font Names, and a shaping test with zero
.notdef. Output is evidence only; nothing here is product code.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

from fontTools.ttLib import TTFont
import uharfbuzz as hb

ARABIC_BASE = [chr(c) for c in range(0x0621, 0x063B)] + [chr(c) for c in range(0x0641, 0x064B)]
# 0621..063A (26) + 0641..064A (10) = 36 base letters incl. hamza forms and ta marbuta
HARAKAT = [chr(c) for c in range(0x064B, 0x0653)]  # 8 marks
AR_INDIC_DIGITS = [chr(c) for c in range(0x0660, 0x066A)]
AR_PUNCT = ["،", "؛", "؟", "ـ"]  # ، ؛ ؟ ـ
SHAPE_SAMPLE = "يُوسُف مَرْيَم لا"
COLOR_TABLES = ("COLR", "SVG ", "CBDT", "sbix")


def metadata_files(meta: Path) -> list[str]:
    return re.findall(r'filename:\s*"([^"]+)"', meta.read_text(encoding="utf-8"))


def rfn_names(licence_text: str) -> list[str]:
    """Names declared in the copyright header: `... with Reserved Font Name(s) "X" and "Y".`

    Only the header (before the licence body) is read — the OFL body itself defines the
    term "Reserved Font Name", which must not count as a declaration."""
    head = licence_text.split("This Font Software is licensed", 1)[0]
    head = re.sub(r"\s+", " ", head)
    out: list[str] = []
    for m in re.finditer(r"with (?:the )?Reserved Font Names?[,:]? ?(.+?)(?:\.(?: |$)|$)", head, re.IGNORECASE):
        clause = m.group(1)
        quoted = re.findall(r"[\"'“”]([^\"'“”]+)[\"'“”]", clause)
        out.extend(q.strip() for q in quoted) if quoted else out.append(clause.strip())
    return [n for n in out if n]


def gpos_features(font: TTFont) -> set[str]:
    if "GPOS" not in font:
        return set()
    fl = font["GPOS"].table.FeatureList
    return {fr.FeatureTag for fr in (fl.FeatureRecord if fl else [])}


def shape_notdef(path: Path, text: str) -> int:
    blob = hb.Blob.from_file_path(str(path))
    face = hb.Face(blob)
    font = hb.Font(face)
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(font, buf, {})
    return sum(1 for g in buf.glyph_infos if g.codepoint == 0)


def measure_file(path: Path, script: str) -> dict:
    data = path.read_bytes()
    rec = {"file": path.name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    f = TTFont(str(path), lazy=True)
    rec["fsType"] = int(f["OS/2"].fsType) if "OS/2" in f else None
    rec["variable"] = "fvar" in f
    if rec["variable"]:
        fv = f["fvar"]
        rec["axes"] = {a.axisTag: [a.minValue, a.defaultValue, a.maxValue] for a in fv.axes}
        rec["instances"] = len(fv.instances)
    rec["color_tables"] = [t.strip() for t in COLOR_TABLES if t in f]
    if "COLR" in f:
        rec["colr_version"] = int(getattr(f["COLR"], "version", 0))
    cmap = f.getBestCmap() or {}
    if script == "AR":
        cov = lambda chars: [c for c in chars if ord(c) not in cmap]  # noqa: E731
        rec["missing_base"] = cov(ARABIC_BASE)
        rec["missing_harakat"] = cov(HARAKAT)
        rec["missing_indic_digits"] = cov(AR_INDIC_DIGITS)
        rec["missing_punct"] = cov(AR_PUNCT)
        feats = gpos_features(f)
        rec["gpos_mark"] = "mark" in feats
        rec["gpos_mkmk"] = "mkmk" in feats
        rec["notdef_in_sample"] = shape_notdef(path, SHAPE_SAMPLE)
    f.close()
    return rec


def main(root: str, catalog: str, out: str) -> int:
    root_p = Path(root)
    commit = subprocess.run(["git", "-C", root, "rev-parse", "HEAD"], capture_output=True,
                            text=True).stdout.strip()
    rows = list(csv.DictReader(open(catalog, encoding="utf-8"), delimiter="\t"))
    families, drift = [], []
    for row in rows:
        d = root_p / row["repo_dir"]
        fam = {"id": row["id"], "family": row["family"], "script": row["script"],
               "repo_dir": row["repo_dir"], "brief_flags": row["flags"].split(),
               "brief_licence": row["licence"]}
        meta = d / "METADATA.pb"
        if not meta.is_file():
            fam["error"] = "METADATA.pb missing"
            drift.append(f"{row['id']} {row['family']}: METADATA.pb missing")
            families.append(fam)
            continue
        names = metadata_files(meta)
        lic_path = next((d / n for n in ("OFL.txt", "LICENSE.txt") if (d / n).is_file()), None)
        lic_text = lic_path.read_text(encoding="utf-8", errors="replace") if lic_path else ""
        fam["licence"] = ("OFL" if lic_path and lic_path.name == "OFL.txt"
                          else "APACHE2" if lic_path else "UNKNOWN")
        fam["licence_file"] = lic_path.name if lic_path else None
        fam["licence_sha256"] = hashlib.sha256(lic_text.encode()).hexdigest() if lic_text else None
        fam["reserved_font_names"] = rfn_names(lic_text)
        fam["files"] = []
        for n in names:
            p = d / n
            if not p.is_file():
                drift.append(f"{row['id']} {row['family']}: listed file missing {n}")
                continue
            fam["files"].append(measure_file(p, row["script"]))
        fam["is_variable"] = any(x["variable"] for x in fam["files"])
        fam["is_color"] = any(x["color_tables"] for x in fam["files"])
        measured_flags = set()
        if fam["is_color"]:
            measured_flags.add("COLOR")
        if fam["is_variable"]:
            measured_flags.add("VAR")
        if fam["reserved_font_names"]:
            measured_flags.add("RFN")
        fam["measured_flags"] = sorted(measured_flags)
        if measured_flags != set(fam["brief_flags"]):
            drift.append(f"{row['id']} {row['family']}: flags brief={sorted(fam['brief_flags'])} "
                         f"measured={sorted(measured_flags)}")
        if fam["licence"] != row["licence"]:
            drift.append(f"{row['id']} {row['family']}: licence brief={row['licence']} measured={fam['licence']}")
        families.append(fam)

    files = [f for fam in families for f in fam.get("files", [])]
    ar = [fam for fam in families if fam["script"] == "AR" and fam.get("files")]
    summary = {
        "commit": commit,
        "families": len(families),
        "arabic": sum(1 for f in families if f["script"] == "AR"),
        "latin": sum(1 for f in families if f["script"] == "EN"),
        "files": len(files),
        "bytes": sum(f["bytes"] for f in files),
        "mb": round(sum(f["bytes"] for f in files) / 1e6, 1),
        "color_families": sorted(f["family"] for f in families if f.get("is_color")),
        "variable_families": sum(1 for f in families if f.get("is_variable")),
        "ofl": sum(1 for f in families if f.get("licence") == "OFL"),
        "apache": sum(1 for f in families if f.get("licence") == "APACHE2"),
        "rfn_families": sum(1 for f in families if f.get("reserved_font_names")),
        "fsType_nonzero": sorted({(fam["family"], x["fsType"]) for fam in families
                                  for x in fam.get("files", []) if x["fsType"]}),
        "arabic_full_coverage": sum(
            1 for fam in ar if all(not (x["missing_base"] or x["missing_harakat"] or x["missing_indic_digits"]
                                        or x["missing_punct"]) for x in fam["files"])),
        "arabic_gpos_mark_all": sum(1 for fam in ar if all(x["gpos_mark"] for x in fam["files"])),
        "arabic_without_mkmk": sorted(fam["family"] for fam in ar if not all(x["gpos_mkmk"] for x in fam["files"])),
        "arabic_zero_notdef": sum(1 for fam in ar if all(x["notdef_in_sample"] == 0 for x in fam["files"])),
        "drift": drift,
    }
    summary["print_candidates"] = summary["families"] - len(summary["color_families"])
    Path(out).write_text(json.dumps({"summary": summary, "families": families}, ensure_ascii=False,
                                    indent=1, default=list), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1, default=list))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:4]))
