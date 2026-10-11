"""Office-safe static builds of variable fonts.

Rules this module enforces:

* PowerPoint groups a family by legacy name ID 1 + subfamily ID 2, so each
  static instance gets: ID1 = family (Regular/Bold/Italic/Bold Italic) or
  ``family <Weight>`` for other weights; ID2 = Regular/Bold/Italic/Bold Italic;
  ID16/ID17 = typographic family/subfamily; ID4 = full name; ID6 = a valid
  PostScript name; OS/2 usWeightClass, fsSelection and head.macStyle agree.
* An instance is a Modified Version under OFL: if the family declares any
  Reserved Font Name the build **must** be renamed (``MX Kids <id> …``);
  building it without the rename, or with a name that still contains an RFN,
  raises :class:`RfnRenameRequired` / :class:`RfnInModifiedName`.
* Builds are deterministic: same input bytes + same parameters ⇒ same output
  bytes (timestamps are copied from the source, never "now").
* Only weights a role needs are built (see :data:`ROLE_WEIGHTS`), clamped to
  the axis; every other axis is pinned at its default.
"""
from __future__ import annotations

import hashlib
import io
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

from mxstudio.fonts.rfn import renamed_family, rfn_conflicts

WEIGHT_NAMES = {100: "Thin", 200: "ExtraLight", 300: "Light", 400: "Regular", 500: "Medium", 600: "SemiBold",
                700: "Bold", 800: "ExtraBold", 900: "Black"}
#: catalog role → typography role → weights it needs (PowerPoint's Bold button needs a 700 member).
ROLE_WEIGHTS = {"title": (700, 800), "name": (700,), "body": (400, 700), "bubble": (400, 700),
                "effect": (800, 900), "handwriting": (400,), "dedication": (400,), "coloring": (400,),
                "ui": (400, 700), "fallback": (400, 700)}
NAME_IDS_REWRITTEN = (1, 2, 3, 4, 6, 16, 17, 18, 21, 22, 25)
_PS_BAD = re.compile(r"[^A-Za-z0-9\-]")


class OfficeBuildError(RuntimeError):
    finding = "office_build_failed"


class RfnRenameRequired(OfficeBuildError):
    finding = "rfn_rename_required"


class RfnInModifiedName(OfficeBuildError):
    finding = "rfn_in_modified_name"


@dataclass(frozen=True)
class BuiltFont:
    file: str
    sha256: str
    bytes: int
    family: str          # name ID 1 (what PowerPoint lists)
    subfamily: str       # name ID 2
    typographic_family: str  # name ID 16
    typographic_subfamily: str  # name ID 17
    full_name: str
    postscript_name: str
    weight: int
    italic: bool
    source_sha256: str

    def as_dict(self) -> dict:
        return asdict(self)


def style_names(family: str, weight: int, italic: bool) -> dict[int, str]:
    """Name IDs 1/2/4/16/17 for one member, Windows RIBBI-style grouping."""
    weight_name = WEIGHT_NAMES.get(weight, f"W{weight}")
    ribbi = weight in (400, 700)
    if ribbi:
        legacy_family = family
        legacy_sub = ("Bold" if weight == 700 else "Regular") if not italic else (
            "Bold Italic" if weight == 700 else "Italic")
    else:
        legacy_family = f"{family} {weight_name}"
        legacy_sub = "Italic" if italic else "Regular"
    typo_sub = weight_name if not italic else ("Italic" if weight == 400 else f"{weight_name} Italic")
    return {1: legacy_family, 2: legacy_sub, 4: f"{family} {typo_sub}", 16: family, 17: typo_sub}


def postscript_name(family: str, subfamily: str) -> str:
    name = f"{_PS_BAD.sub('', family)}-{_PS_BAD.sub('', subfamily)}"
    return name[:63]


def plan_weights(axis: tuple[float, float, float] | None, roles: list[str]) -> list[int]:
    """Weights to build for these catalog roles, snapped into the wght axis. Always includes a Regular."""
    lo, default, hi = axis if axis else (400.0, 400.0, 400.0)
    wanted = {400}
    for role in roles:
        wanted.update(ROLE_WEIGHTS.get(role, (400,)))
    out = set()
    for weight in sorted(wanted):
        if lo <= weight <= hi:
            out.add(weight)
        elif weight == 400:
            out.add(int(round(min(max(400, lo), hi) / 100.0) * 100) if lo <= 400 <= hi else int(lo))
        elif weight == 700 and hi >= 600:
            out.add(int(hi // 100 * 100))
    return sorted(out)


def _set_names(font: TTFont, names: dict[int, str], ps_name: str, version: str) -> None:
    table = font["name"]
    table.names = [rec for rec in table.names if rec.nameID not in NAME_IDS_REWRITTEN]
    values = {**names, 6: ps_name, 3: f"{version};MXKIDS;{ps_name}"}
    for name_id in sorted(values):
        table.setName(values[name_id], name_id, 3, 1, 0x409)
    table.names.sort(key=lambda r: (r.platformID, r.platEncID, r.langID, r.nameID))


def _set_style_bits(font: TTFont, weight: int, italic: bool) -> None:
    os2 = font["OS/2"]
    os2.usWeightClass = weight
    selection = os2.fsSelection & ~((1 << 0) | (1 << 5) | (1 << 6))
    if italic:
        selection |= 1 << 0
    if weight == 700:
        selection |= 1 << 5
    if weight == 400 and not italic:
        selection |= 1 << 6
    os2.fsSelection = selection
    mac = font["head"].macStyle & ~0b11
    font["head"].macStyle = mac | (1 if weight == 700 else 0) | (2 if italic else 0)


def check_modified_names(font: TTFont, original_family: str, rfns: list[str]) -> None:
    """Refuse a modified font that keeps the RFN-bearing family or still uses an RFN in any naming record."""
    if not rfns:
        return
    family = str(font["name"].getDebugName(16) or font["name"].getDebugName(1) or "")
    if " ".join(family.split()).casefold() == " ".join(original_family.split()).casefold():
        raise RfnRenameRequired(
            f"«{original_family}» declares Reserved Font Name(s) {rfns}: a modified build must be renamed "
            f"(MX Kids <id> …) — الخط ده عليه اسم محجوز، لازم يتسمّى باسم جديد قبل أي تعديل")
    for record in font["name"].names:
        if record.nameID in NAME_IDS_REWRITTEN:
            hits = rfn_conflicts(record.toUnicode(), rfns)
            if hits:
                raise RfnInModifiedName(f"name ID {record.nameID} «{record.toUnicode()}» still uses RFN {hits}")


def build_instance(source: Path, *, font_id: str, family: str, rfns: list[str], weight: int,
                   rename: bool | None = None, italic: bool = False) -> tuple[bytes, BuiltFont]:
    """One static instance as bytes + its facts. `rename=None` renames exactly when an RFN applies."""
    source = Path(source)
    data = source.read_bytes()
    rename = bool(rfns) if rename is None else rename
    if rfns and not rename:
        raise RfnRenameRequired(
            f"«{family}» declares Reserved Font Name(s) {rfns}; instancing makes a Modified Version, so the "
            f"build must be renamed (MX Kids {font_id} …)")
    new_family = renamed_family(font_id, family, rfns) if rename else family
    font = TTFont(io.BytesIO(data), recalcTimestamp=False)
    created, modified = font["head"].created, font["head"].modified
    if "fvar" in font:
        limits = {axis.axisTag: axis.defaultValue for axis in font["fvar"].axes}
        if "wght" in limits:
            axis = next(a for a in font["fvar"].axes if a.axisTag == "wght")
            if not axis.minValue <= weight <= axis.maxValue:
                raise OfficeBuildError(f"weight {weight} outside the wght axis {axis.minValue}–{axis.maxValue}")
            limits["wght"] = float(weight)
        if "ital" in limits:
            limits["ital"] = 1.0 if italic else 0.0
        font = instancer.instantiateVariableFont(font, limits, inplace=False, updateFontNames=False,
                                                 static=True)
    font.recalcTimestamp = False
    font["head"].created, font["head"].modified = created, modified
    names = style_names(new_family, weight, italic)
    ps_name = postscript_name(new_family, names[17])
    version = str(font["name"].getDebugName(5) or "Version 1.000").split(";")[0]
    _set_names(font, names, ps_name, version)
    _set_style_bits(font, weight, italic)
    if "STAT" in font:
        del font["STAT"]
    check_modified_names(font, family, rfns)
    out = io.BytesIO()
    font.save(out, reorderTables=True)
    blob = out.getvalue()
    built = BuiltFont(file=f"{ps_name}.ttf", sha256=hashlib.sha256(blob).hexdigest(), bytes=len(blob),
                      family=names[1], subfamily=names[2], typographic_family=names[16],
                      typographic_subfamily=names[17], full_name=names[4], postscript_name=ps_name,
                      weight=weight, italic=italic, source_sha256=hashlib.sha256(data).hexdigest())
    return blob, built


def build_family(source: Path, out_dir: Path, *, font_id: str, family: str, rfns: list[str], roles: list[str],
                 rename: bool | None = None, weights: list[int] | None = None) -> list[BuiltFont]:
    """Build every weight the roles need into `out_dir` (files named by PostScript name)."""
    probe = TTFont(str(source), lazy=True)
    try:
        axis = next(((a.minValue, a.defaultValue, a.maxValue) for a in probe["fvar"].axes if a.axisTag == "wght"),
                    None) if "fvar" in probe else None
    finally:
        probe.close()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    built = []
    for weight in weights or plan_weights(axis, roles):
        blob, facts = build_instance(source, font_id=font_id, family=family, rfns=rfns, weight=weight,
                                     rename=rename)
        (out_dir / facts.file).write_bytes(blob)
        built.append(facts)
    return built


def family_install_plan(fam: dict, qa_entry: dict | None, checkout: Path | None = None,
                        out_dir: Path | None = None) -> dict:
    """What gets installed on export machines for one catalog family.

    * static families: the upstream files, unmodified (no rename needed even with an RFN);
    * variable families: Office builds of the upright VF for the weights the roles need
      (renamed when an RFN applies); italic VFs are not built (no role needs italic);
    * colour / rejected families: nothing (quarantined for print).
    When `checkout` and `out_dir` are given the builds are made and their sha256 recorded.
    """
    status = (qa_entry or {}).get("status", "certified_print")
    plan: dict = {"id": fam["id"], "family": fam["family"], "qa_status": status}
    if status != "certified_print":
        return plan | {"source": "none", "install_family": None, "files": [],
                       "note": "not installed for print: " + status}
    rfns = fam.get("reserved_font_names", [])
    upright_vf = [f for f in fam["files"] if f.get("variable") and "Italic" not in f["file"]]
    if not upright_vf:
        files = [{"file": f["file"], "sha256": f["sha256"], "family": f["names"].get("1", fam["family"]),
                  "subfamily": f["names"].get("2", ""), "weight": f["weight_class"], "italic": f["italic"],
                  "source": "upstream"} for f in fam["files"]]
        regular = min(files, key=lambda f: (f["italic"], abs(f["weight"] - 400)))
        return plan | {"source": "upstream_static", "install_family": regular["family"], "renamed": False,
                       "files": files}
    vf = upright_vf[0]
    axis = vf.get("axes", {}).get("wght")
    weights = plan_weights(tuple(axis) if axis else None, fam["roles"])
    new_family = renamed_family(fam["id"], fam["family"], rfns) if rfns else fam["family"]
    files = []
    if checkout is not None and out_dir is not None:
        built = build_family(Path(checkout) / fam["repo_dir"] / vf["file"], Path(out_dir) / fam["id"],
                             font_id=fam["id"], family=fam["family"], rfns=rfns, roles=fam["roles"],
                             weights=weights)
        files = [{**b.as_dict(), "source": "office_build", "from_file": vf["file"]} for b in built]
    return plan | {"source": "office_build", "install_family": new_family, "renamed": bool(rfns),
                   "from_file": vf["file"], "from_sha256": vf["sha256"], "weights": weights,
                   "skipped_files": [f["file"] for f in fam["files"] if f is not vf], "files": files}


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json
    import tempfile

    import fontTools

    from mxstudio.fonts.build_catalog import write_json
    from mxstudio.fonts.catalog import default_catalog
    from mxstudio.fonts.paths import OFFICE_BUILDS_JSON, QA_JSON

    parser = argparse.ArgumentParser(description="Build Office-safe statics for every certified variable family")
    parser.add_argument("--checkout", required=True, type=Path)
    parser.add_argument("--out-dir", type=Path, help="where the built fonts go (not committed)")
    args = parser.parse_args(argv)
    qa = {f["family"]: f for f in json.loads(QA_JSON.read_text(encoding="utf-8"))["families"]}
    catalog = default_catalog()
    out_dir = args.out_dir or Path(tempfile.mkdtemp(prefix="mx_office_build_"))
    plans = [family_install_plan(fam, qa.get(fam["family"]), args.checkout, out_dir) for fam in catalog.families]
    # determinism proof: rebuild every office build into a second folder and compare bytes
    second = out_dir / "_rebuild"
    mismatched = []
    for fam, plan in zip(catalog.families, plans):
        if plan.get("source") != "office_build":
            continue
        again = family_install_plan(fam, qa.get(fam["family"]), args.checkout, second)
        if [f["sha256"] for f in again["files"]] != [f["sha256"] for f in plan["files"]]:
            mismatched.append(fam["family"])
    report = {
        "schema": "mx.fonts.office_builds/1", "commit": catalog.commit, "fonttools": fontTools.version,
        "determinism": {"rebuilt_and_compared": sum(p.get("source") == "office_build" for p in plans),
                        "mismatched": mismatched},
        "counts": {"office_build_families": sum(p.get("source") == "office_build" for p in plans),
                   "office_build_files": sum(len(p["files"]) for p in plans if p.get("source") == "office_build"),
                   "upstream_static_families": sum(p.get("source") == "upstream_static" for p in plans),
                   "not_installed": sum(p.get("source") == "none" for p in plans),
                   "renamed_families": sum(bool(p.get("renamed")) for p in plans)},
        "families": plans,
    }
    write_json(report, OFFICE_BUILDS_JSON)
    print(json.dumps(report["counts"]), json.dumps(report["determinism"]))
    return 0 if not mismatched else 1


if __name__ == "__main__":
    raise SystemExit(main())


def install_name_map(builds_path: Path | None = None) -> dict[str, str]:
    """catalog family → the family name PowerPoint lists once installed (renamed when an RFN applied)."""
    import json

    from mxstudio.fonts.paths import OFFICE_BUILDS_JSON
    data = json.loads(Path(builds_path or OFFICE_BUILDS_JSON).read_text(encoding="utf-8"))
    return {plan["family"]: plan["install_family"] for plan in data["families"] if plan.get("install_family")}


_DECK_NAMES: dict[str, str] | None = None


def deck_family(family: str) -> str:
    """The family name a deck must use so the INSTALLED font is found: an Office build renamed for an OFL Reserved
    Font Name is installed as «MX Kids F076 …», never under the catalog name (which would be substituted)."""
    global _DECK_NAMES
    if _DECK_NAMES is None:
        try:
            _DECK_NAMES = install_name_map()
        except (OSError, ValueError, KeyError):
            _DECK_NAMES = {}
    return _DECK_NAMES.get(family) or family
