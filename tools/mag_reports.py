"""Release reports: CycloneDX SBOM + licence report (code, fonts, shapes) for the Magazine Studio.

    python tools/mag_reports.py --out docs/mag/phase-13

Python components are read from the environment the command runs in (run it in the
release build environment); npm components from package-lock.json; fonts from the
licence ledger; shape sources from catalog/shapes/sources.json; vendored contracts by sha256.
Any component matching a banned pattern in catalog/licence_policy.json fails the run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXTRAS = ("runtime", "studio")
#: components whose metadata alone does not settle the licence question, with the reviewed reading
REVIEWED = {
    "anthropic": "MIT SDK. The Claude API it calls is a paid service the operator opted into for the Start-page "
    "chat; optional - the free route is an open-weight model (Qwen3-VL) on the operator's GPU or Claude Desktop "
    "over MCP.",
    "certifi": "MPL-2.0 (file-level copyleft): shipped unmodified; free for commercial use.",
    "pikepdf": "MPL-2.0 (file-level copyleft): shipped unmodified; its QPDF core is Apache-2.0.",
    "libreoffice_msi": "MPL-2.0: official binaries installed unmodified; free for commercial use.",
    "jszip": "dual MIT OR GPL-3.0-or-later: used under MIT.",
    "qrcode": "BSD licence; the extra 'Other/Proprietary' trove classifier is a metadata artefact "
    "(TO-CHECK at release).",
    "resvg_py": "no licence field in the wheel metadata (TO-CHECK at release against the upstream repository; "
    "the resvg engine itself is Apache-2.0 OR MIT).",
    "pypdfium2": "Apache-2.0 / BSD-3-Clause; bundled PDFium is BSD-3-Clause with permissive third-party notices.",
    "webview2_bootstrapper": "Microsoft Edge WebView2 redistributable: free distribution terms from Microsoft.",
}


def _requirement_names() -> list[str]:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    names = set()
    for block in re.findall(r"^(?:dependencies|" + "|".join(EXTRAS) + r")\s*=\s*\[(.*?)\]", text, re.S | re.M):
        for item in re.findall(r'"([^"]+)"', block):
            names.add(re.split(r"[<>=;!\s\[]", item, maxsplit=1)[0].lower())
    return sorted(names)


def _closure(names: list[str]) -> dict[str, metadata.Distribution]:
    seen: dict[str, metadata.Distribution] = {}
    todo = list(names)
    while todo:
        name = todo.pop()
        key = name.lower().replace("_", "-")
        if key in seen:
            continue
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue
        seen[key] = dist
        for req in dist.requires or []:
            if "extra ==" in req:
                continue
            todo.append(re.split(r"[<>=;!\s\[(]", req, maxsplit=1)[0])
    return seen


def _licence(dist: metadata.Distribution) -> str:
    meta = dist.metadata
    expression = meta.get("License-Expression")
    if expression:
        return expression
    classifiers = [c.split("::")[-1].strip() for c in meta.get_all("Classifier") or [] if c.startswith("License ::")]
    if classifiers:
        return " / ".join(sorted(set(classifiers)))
    text = (meta.get("License") or "").strip().splitlines()
    return text[0][:80] if text else "UNKNOWN"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(out: Path) -> dict:
    policy = json.loads((ROOT / "catalog" / "licence_policy.json").read_text(encoding="utf-8"))
    python = [
        {
            "type": "library",
            "name": d.metadata["Name"],
            "version": d.version,
            "purl": f"pkg:pypi/{d.metadata['Name'].lower()}@{d.version}",
            "licenses": [{"license": {"name": _licence(d)}}],
            "properties": [{"name": "mxs:ecosystem", "value": "python"}],
        }
        for _, d in sorted(_closure(_requirement_names()).items())
    ]
    lock = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))
    npm = [
        {
            "type": "library",
            "name": key.split("node_modules/")[-1],
            "version": value.get("version", ""),
            "purl": f"pkg:npm/{key.split('node_modules/')[-1]}@{value.get('version', '')}",
            "licenses": [{"license": {"name": value.get("license", "UNKNOWN")}}],
            "properties": [
                {"name": "mxs:ecosystem", "value": "npm"},
                {"name": "mxs:dev", "value": str(bool(value.get("dev")))},
            ],
        }
        for key, value in sorted(lock["packages"].items())
        if key
    ]
    vendored = [
        {
            "type": "file",
            "name": f"vendor/modulex/{p.name}",
            "hashes": [{"alg": "SHA-256", "content": _sha(p)}],
            "properties": [{"name": "mxs:rule", "value": "byte-identical copy of the operator's file"}],
        }
        for p in sorted((ROOT / "vendor" / "modulex").glob("*.py"))
    ]
    ledger = json.loads((ROOT / "catalog" / "fonts" / "font_license_ledger.json").read_text(encoding="utf-8"))
    qa = {
        f["family"]: f["status"]
        for f in json.loads((ROOT / "catalog" / "fonts" / "qa_status.json").read_text(encoding="utf-8"))["families"]
    }
    fonts = [
        {
            "type": "file",
            "name": f["family"],
            "licenses": [{"license": {"id": f["licence"]}}],
            "properties": [
                {"name": "mxs:ecosystem", "value": "font"},
                {"name": "mxs:qa_status", "value": qa.get(f["family"], "")},
                {"name": "mxs:source", "value": f"google/fonts@{ledger['commit'][:8]}"},
            ],
        }
        for f in ledger["families"]
    ]
    downloads = json.loads((ROOT / "installer" / "downloads.json").read_text(encoding="utf-8"))["entries"]
    bundled = [
        {
            "type": "application",
            "name": key,
            "version": entry.get("version", ""),
            "licenses": [{"license": {"name": entry.get("licence", "UNKNOWN")}}],
            "properties": [
                {"name": "mxs:sha256", "value": entry.get("sha256", "") or f"recipe:{entry.get('recipe')}"},
                {"name": "mxs:pinned", "value": str(bool(entry.get("recipe"))
                                                    or entry.get("sha256") not in (None, "", "TO-PIN"))},
            ],
        }
        for key, entry in sorted(downloads.items())
    ]
    packs = json.loads((ROOT / "catalog" / "shapes" / "packs.json").read_text(encoding="utf-8"))
    shape_sets = [
        {
            "type": "data",
            "name": item["package"],
            "version": item["version"],
            "purl": f"pkg:npm/{item['package'].replace('@', '%40')}@{item['version']}",
            "licenses": [{"license": {"id": item["licence"]}}],
            "hashes": [{"alg": "SHA-256", "content": item["sha256"]}],
            "properties": [{"name": "mxs:ecosystem", "value": "shape-pack"},
                           {"name": "mxs:set", "value": item["name"]}],
        }
        for item in packs["sets"]
    ]
    components = python + npm + vendored + fonts + bundled + shape_sets
    blob = json.dumps(components).lower()
    banned = [b["id"] for b in policy["banned_components"] for p in b["patterns"] if p.lower() in blob]
    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "component": {"type": "application", "name": "ModuleX Magazine Studio"},
            "properties": [
                {"name": "mxs:python", "value": sys.version.split()[0]},
                {"name": "mxs:licence_policy", "value": "catalog/licence_policy.json"},
            ],
        },
        "components": components,
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "SBOM.cdx.json").write_text(json.dumps(sbom, ensure_ascii=False, indent=1), encoding="utf-8")
    shapes = json.loads((ROOT / "catalog" / "shapes" / "sources.json").read_text(encoding="utf-8"))
    report = licence_report(python, npm, ledger, qa, shapes, policy, bundled, banned, shape_sets)
    (out / "LICENCE_REPORT_AR_EN.md").write_text(report, encoding="utf-8")
    return {
        "components": len(components),
        "python": len(python),
        "npm": len(npm),
        "fonts": len(fonts),
        "banned_found": banned,
    }


def licence_report(python, npm, ledger, qa, shapes, policy, bundled, banned, shape_sets=()) -> str:
    def counts(items):
        return Counter(i["licenses"][0]["license"].get("id") or i["licenses"][0]["license"]["name"] for i in items)

    lines = [
        "# LICENCE_REPORT_AR_EN — تقرير التراخيص · Licence report",
        "",
        "> Generated by `tools/mag_reports.py`. Rule (`catalog/licence_policy.json`): " + policy["rule"],
        "",
        "**AR:** كل مكوّن في الاستوديو برخصة مجانية للاستخدام التجاري. المكوّنات اللي ليها ترخيص تجاري مدفوع "
        "أو غير تجاري ممنوعة واتبدلت ببدايل مجانية (شوف `docs/mag/decisions/FREE_ALTERNATIVES_AR_EN.md`).",
        "",
        f"**Banned components found: {', '.join(banned) if banned else 'none'}**",
        "",
        "## Code · الكود",
        "",
        f"Python ({len(python)} distributions, runtime + studio closure):",
        "",
    ]
    lines += [f"* {name}: {n}" for name, n in sorted(counts(python).items())]
    runtime_npm = [c for c in npm if c["properties"][1]["value"] == "False"]
    lines += ["", f"npm ({len(runtime_npm)} runtime packages, dev excluded):", ""]
    lines += [f"* {name}: {n}" for name, n in sorted(counts(runtime_npm).items())]
    lines += ["", "Installer payloads:", ""]
    lines += [
        f"* {c['name']} {c['version']}: {c['licenses'][0]['license']['name']} — pinned: {c['properties'][1]['value']}"
        for c in bundled
    ]
    lines += [
        "",
        "Vendored operator contracts (`vendor/modulex/`) are the operator's own files, copied byte-identically.",
        "",
        "## Fonts · الخطوط",
        "",
        f"{len(ledger['families'])} families from google/fonts @ `{ledger['commit']}`:",
        "",
    ]
    lines += [f"* {name}: {n}" for name, n in sorted(Counter(f["licence"] for f in ledger["families"]).items())]
    status = Counter(qa.values())
    lines += [
        "",
        "QA status: " + ", ".join(f"{k} {v}" for k, v in sorted(status.items())),
        "Reserved Font Names are recorded per family; modified builds are renamed when an RFN is declared.",
        "",
        "## Shapes · الأشكال",
        "",
        "* Office preset geometries and generated shapes: original work (`" + shapes["original_work_licence"] + "`).",
        "* Discovery sources (official APIs only): " + ", ".join(s["name"] for s in shapes["sources"]) + ".",
        "* Allowed for print: "
        + ", ".join(policy["print_asset_allowlist"])
        + "; credits required for "
        + ", ".join(policy["print_asset_requires_credits"])
        + ".",
        "* Shape packs shipped in the Full installer (pinned npm tarballs, `catalog/shapes/packs.json`): "
        + ", ".join(f"{c['properties'][1]['value']} ({c['licenses'][0]['license']['id']})" for c in shape_sets)
        + "; CC-BY-4.0 icons go on the credits page.",
        "* Refused for print: " + ", ".join(policy["print_asset_refused"]) + ".",
        "* Waiting for the operator's decision: " + ", ".join(policy["print_asset_pending_operator"]) + ".",
        "",
        "## AI models · موديلات الذكاء الاصطناعي",
        "",
        "* Weights allowed by default: "
        + ", ".join(policy["model_weight_allowlist"])
        + " (Qwen-Image, Qwen-Image-Edit-2511, FLUX.1 [schnell], Qwen3-VL). FLUX.1 [dev]/Kontext [dev] are refused.",
        "",
        "## Reviewed items · مراجعة يدوية",
        "",
    ]
    lines += [f"* {name}: {note}" for name, note in sorted(REVIEWED.items())]
    lines += ["", "## Banned → replacement · الممنوع وبديله", ""]
    lines += [f"* {b['id']}: {b['reason']} → {b['replacement']}" for b in policy["banned_components"]]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "docs" / "mag" / "phase-13")
    args = parser.parse_args(argv)
    result = build(args.out)
    print(json.dumps(result))
    return 1 if result["banned_found"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
