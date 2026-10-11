"""Verify the anchors every patch depends on (read-only).

Rule: an anchor is ground truth from the brief (a signature line, a verbatim body,
a constant, a regex, a sha256). Any mismatch blocks every patch that depends on it,
and the exact difference (expected vs found, a unified diff for bodies) is recorded.
A different sha256 on a contract file means "operator updated it": the Kit re-reads
the device copy, compares behaviour (5 signing vectors / ``pdf_stats`` known answers)
and reports — it never overwrites.
"""
from __future__ import annotations

import ast
import difflib
import json
import re
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import _vendor
from ._util import read_json, read_text, rel_posix, sha256_file, walk_files
from .discover import find_console_decks, system_dir

OPERATOR_PORTS = Path(__file__).resolve().parents[1] / "validators" / "operator_ports.py"

KNOWN_SHA = {
    "pptx_to_pdf.py": _vendor.PINNED["pptx_to_pdf.py"],
    "modulex_signing.py": _vendor.PINNED["modulex_signing.py"],
}

OM_DECK_CONSTANTS = {"EMU_PER_CM": 360000, "IDEAL_DPI": 300, "OK_DPI": 150, "MIN_DPI": 72, "MIN_SIDE_PX": 300,
                     "MIN_FRAME_CM": 1.5, "MAX_TEXT": 2000, "MAX_LINES": 30}
OM_DECK_REGEXES = {"TEXT_RE": r"^t-(\d{1,4})-(\d{1,7})-(\d{1,4})$", "IMG_RE": r"^i-(\d{1,4})-(\d{1,7})$"}
OM_DECK_SIGNATURES = {"locate": "order", "inventory": "deck", "_set_paragraph": "p, new",
                      "apply": "deck_in, deck_out, texts, images, inv",
                      "export_pdf": "deck, pdf, expect_pages, attempts=2"}
OM_PREFLIGHT_PREFIX = ("path, *, magazine_size='A4', expected_pages=None, expected_sha256=None, "
                       "output_status=None, require_approved=False, bleed_mm=Decimal('0'), max_bytes=")
STORE_EDITOR_MODULES = tuple(f"mxstore/areas/accounts/editor/{m}.py"
                             for m in ("ledger", "pricing", "topup", "limits", "audit", "config", "db"))
APP_OBJECT_RE = re.compile(r"^(\w+)\s*(?::\s*[\w.]+\s*)?=\s*(?:fastapi\.)?FastAPI\(", re.MULTILINE)


@dataclass
class Anchor:
    id: str
    system: str
    file: str          # relative to the system folder ("" for dynamic anchors)
    kind: str
    expected: Any = None
    severity: str = "block"   # "block" anchors gate patches; "info" anchors are reported only
    note: str = ""


@dataclass
class AnchorResult:
    id: str
    system: str
    file: str
    kind: str
    status: str               # ok | mismatch | missing | operator_updated | absent_system
    expected: Any = None
    found: Any = None
    diff: str = ""
    severity: str = "block"
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v not in ("", None, {}) or k in ("status", "id")}


# ---------------------------------------------------------------- verbatim blocks ----

def port_blocks(path: Path = OPERATOR_PORTS) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    return {m.group(1): m.group(2) for m in
            re.finditer(r"# ---- PORT BEGIN: ([^\n]*?) ----\n(.*?)# ---- PORT END", text, re.DOTALL)}


def extract_def(source: str, name: str) -> str | None:
    """Source text of top-level ``def name(...)`` up to the next column-0 statement; normalised."""
    lines = source.replace("\r\n", "\n").split("\n")
    start = next((i for i, line in enumerate(lines) if re.match(rf"def {re.escape(name)}\(", line)), None)
    if start is None:
        return None
    end = len(lines)
    for j in range(start + 1, len(lines)):
        line = lines[j]
        if line.strip() and not line[0].isspace():
            end = j
            break
    body = [line.rstrip() for line in lines[start:end]]
    while body and not body[-1]:
        body.pop()
    return "\n".join(body)


def expected_def(name: str) -> str:
    for block in port_blocks().values():
        found = extract_def(block, name)
        if found is not None:
            return found
    raise KeyError(name)


# ---------------------------------------------------------------- anchor table ----

def anchor_table() -> list[Anchor]:
    se = "app/services/story_engine.py"
    deck = "app/editor/deck.py"
    mp = "execution_console/services/magazine_pptx.py"
    return [
        Anchor("OM.story_engine.generate_story", "OM", se, "contains",
               'def generate_story(story_name, child_name, gender, language, output_folder, size="A4"):'),
        Anchor("OM.story_engine.replace_in_paragraph", "OM", se, "verbatim_def", "replace_in_paragraph"),
        Anchor("OM.story_engine.replace_in_shape", "OM", se, "verbatim_def", "replace_in_shape"),
        Anchor("OM.story_engine.resolve_variant", "OM", se, "contains",
               "def resolve_variant(stories, story_name, size):"),
        Anchor("OM.story_engine.add_story", "OM", se, "contains",
               "def add_story(display_name, ar_male_file, ar_male_base, ar_female_file, ar_female_base,"),
        Anchor("OM.editor.deck.constants", "OM", deck, "constants", OM_DECK_CONSTANTS),
        Anchor("OM.editor.deck.regexes", "OM", deck, "regex_constants", OM_DECK_REGEXES),
        Anchor("OM.editor.deck.signatures", "OM", deck, "signatures", OM_DECK_SIGNATURES),
        Anchor("OM.editor.deck.killswitch", "OM", deck, "contains", "MODULEX_P149"),
        Anchor("OM.editor.printing.freeze_rebind", "OM", "app/editor/printing.py", "ordered_contains",
               ["freeze_sent_artifacts(", "rebind_ready_artifacts("]),
        Anchor("OM.printing.preflight.run", "OM", "app/printing/preflight.py", "signature_prefix",
               {"run": OM_PREFLIGHT_PREFIX}),
        Anchor("OM.printing.print_service.public", "OM", "app/printing/print_service.py", "defs_present",
               ["freeze_sent_artifacts", "rebind_ready_artifacts"]),
        Anchor("OM.app_package", "OM", "app/__init__.py", "package"),
        Anchor("OM.app_object", "OM", "", "app_object"),
        Anchor("OM.signing.sha", "OM", "modulex_core/modulex_signing.py", "sha256", KNOWN_SHA["modulex_signing.py"]),
        Anchor("Console.magazine_pptx.entry_stem", "Console", mp, "contains", 'ENTRY_STEM = "modulex_scene_{:02d}"'),
        Anchor("Console.magazine_pptx.ph_pic_re", "Console", mp, "contains",
               """_PH_PIC_RE = re.compile(rb'<p:ph[^>]*type="pic"')"""),
        Anchor("Console.magazine_pptx.deck_picture_slots", "Console", mp, "verbatim_def", "deck_picture_slots"),
        Anchor("Console.pptx_to_pdf.sha", "Console", "execution_console/services/pptx_to_pdf.py", "sha256",
               KNOWN_SHA["pptx_to_pdf.py"]),
        Anchor("Console.story_decks.shape", "Console", "story_decks.json", "story_decks"),
        Anchor("Console.package", "Console", "execution_console/__init__.py", "package"),
        Anchor("Console.app_object", "Console", "", "app_object"),
        Anchor("Console.signing.sha", "Console", "", "sha256_any", KNOWN_SHA["modulex_signing.py"]),
        Anchor("Console.story_contracts", "Console", "story_contracts", "dir_exists", severity="info"),
        Anchor("Console.qc_agent", "Console", "qc_agent.py", "file_somewhere", severity="info",
               note="verify on device"),
        Anchor("Console.qc_store", "Console", "qc_store.py", "file_somewhere", severity="info",
               note="verify on device"),
        Anchor("Store.editor_modules", "Store", "", "files_exist", list(STORE_EDITOR_MODULES)),
        Anchor("Store.c11_admin_action", "Store", "contracts", "c11_admin_action"),
        Anchor("Orchestrator.signing.sha", "Orchestrator", "", "sha256_any", KNOWN_SHA["modulex_signing.py"],
               severity="info"),
    ]


# ---------------------------------------------------------------- checkers ----

def _ast(path: Path) -> ast.Module | None:
    try:
        return ast.parse(read_text(path))
    except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
        return None


def _top_assign(tree: ast.Module, name: str) -> ast.AST | None:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return node.value
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
            return node.value
    return None


def _top_defs(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    return {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _args_text(fn: ast.FunctionDef) -> str:
    return ast.unparse(fn.args)


def _udiff(expected: str, found: str, name: str) -> str:
    return "\n".join(difflib.unified_diff(expected.split("\n"), found.split("\n"), f"expected:{name}",
                                          f"device:{name}", lineterm=""))[:6000]


def find_app_objects(sdir: Path) -> list[dict]:
    hits = []
    for path in walk_files(sdir, suffixes=(".py",), max_depth=4):
        rel = rel_posix(path, sdir)
        if "/tests/" in f"/{rel}" or rel.startswith("test"):
            continue
        try:
            text = read_text(path)
        except (OSError, UnicodeDecodeError):
            continue
        for m in APP_OBJECT_RE.finditer(text):
            hits.append({"file": rel, "var": m.group(1), "line": text.count("\n", 0, m.start()) + 1})
    return hits


def _check(anchor: Anchor, sdir: Path, root: Path, overrides: dict) -> AnchorResult:
    res = AnchorResult(anchor.id, anchor.system, anchor.file, anchor.kind, "ok", anchor.expected,
                       severity=anchor.severity)
    path = sdir / anchor.file if anchor.file else sdir
    kind = anchor.kind

    if kind == "app_object":
        override = overrides.get("app_files", {}).get(anchor.system)
        hits = find_app_objects(sdir)
        if override:
            hits = [h for h in hits if h["file"] == override]
        res.found = hits
        if len(hits) == 1:
            res.file = hits[0]["file"]
            res.extra = {"var": hits[0]["var"], "line": hits[0]["line"]}
        else:
            res.status = "missing" if not hits else "mismatch"
            res.diff = "expected exactly one module-level `X = FastAPI(` (pass --app-file SYSTEM=relpath)"
        return res
    if kind == "sha256_any":
        copies = [p for p in walk_files(sdir, names=("modulex_signing.py",), max_depth=6)]
        res.found = [{"file": rel_posix(p, sdir), "sha256": sha256_file(p)} for p in copies]
        if not copies:
            res.status = "missing"
            return res
        res.file = res.found[0]["file"]
        if all(c["sha256"] == anchor.expected for c in res.found):
            return res
        res.status = "operator_updated"
        res.extra = {"behaviour": [compare_signing_behaviour(p) for p in copies
                                   if sha256_file(p) != anchor.expected]}
        return res
    if kind == "files_exist":
        missing = [f for f in anchor.expected if not (sdir / f).is_file()]
        res.found = {"missing": missing}
        res.status = "ok" if not missing else "missing"
        return res
    if kind == "dir_exists":
        res.status = "ok" if path.is_dir() else "missing"
        if path.is_dir():
            res.extra = {"approvals_log_present": (path / "approvals.log.jsonl").is_file(),
                         "contracts": len(list(path.glob("*.json")))}
        return res
    if kind == "file_somewhere":
        hits = [rel_posix(p, sdir) for p in walk_files(sdir, names=(anchor.file,), max_depth=5)]
        res.found = hits
        res.status = "ok" if hits else "missing"
        return res
    if kind == "story_decks":
        decks = find_console_decks(sdir)
        if not decks:
            res.status = "missing"
            return res
        res.file = rel_posix(decks, sdir)
        problems = story_decks_problems(read_json(decks))
        res.found = {"problems": problems[:50]}
        res.status = "ok" if not problems else "mismatch"
        return res
    if kind == "c11_admin_action":
        return _check_c11(res, path)
    if kind == "package":
        if path.is_file():
            res.found = "__init__.py present"
            return res
        # namespace package: accepted when the code itself imports through the package name
        pkg = Path(anchor.file).parts[0]
        users = []
        for p in walk_files(sdir, suffixes=(".py",), max_depth=5):
            try:
                if re.search(rf"^\s*(from|import) {re.escape(pkg)}\.", read_text(p), re.MULTILINE):
                    users.append(rel_posix(p, sdir))
            except (OSError, UnicodeDecodeError):
                continue
            if len(users) >= 3:
                break
        res.found = {"importers": users}
        res.status = "ok" if users else "missing"
        return res

    if not path.is_file():
        res.status = "missing"
        return res
    if kind == "sha256":
        digest = sha256_file(path)
        res.found = digest
        if digest != anchor.expected:
            res.status = "operator_updated"
            behaviour = (compare_signing_behaviour(path) if path.name == "modulex_signing.py"
                         else compare_pdf_stats_behaviour(path))
            res.extra = {"behaviour": behaviour}
        return res
    try:
        text = read_text(path).replace("\r\n", "\n")
    except (OSError, UnicodeDecodeError) as exc:
        res.status, res.found = "mismatch", f"unreadable: {exc}"
        return res
    if kind == "contains":
        if anchor.expected not in text:
            res.status = "mismatch"
            near = [line.strip() for line in text.split("\n")
                    if anchor.expected.split("(")[0].strip()[:24] in line][:5]
            res.found = near or None
        return res
    if kind == "ordered_contains":
        positions = [text.find(t) for t in anchor.expected]
        res.found = positions
        if any(p < 0 for p in positions) or positions != sorted(positions):
            res.status = "mismatch"
        return res
    if kind == "verbatim_def":
        expected = expected_def(anchor.expected)
        found = extract_def(text, anchor.expected)
        if found is None:
            res.status, res.found = "missing", None
        elif found != expected:
            res.status = "mismatch"
            res.diff = _udiff(expected, found, anchor.expected)
        res.expected = f"verbatim body of {anchor.expected} (operator_ports.py)"
        return res
    tree = _ast(path)
    if tree is None:
        res.status, res.found = "mismatch", "file does not parse as Python"
        return res
    if kind == "constants":
        found = {}
        for name in anchor.expected:
            node = _top_assign(tree, name)
            try:
                found[name] = ast.literal_eval(node) if node is not None else None
            except ValueError:
                found[name] = ast.unparse(node)
        res.found = found
        if found != anchor.expected:
            res.status = "mismatch"
        return res
    if kind == "regex_constants":
        found = {}
        for name in anchor.expected:
            node = _top_assign(tree, name)
            pattern = None
            if isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
                pattern = node.args[0].value
            elif isinstance(node, ast.Constant):
                pattern = node.value
            found[name] = pattern
        res.found = found
        if found != anchor.expected:
            res.status = "mismatch"
        return res
    if kind in ("signatures", "signature_prefix"):
        defs = _top_defs(tree)
        found = {name: (_args_text(defs[name]) if name in defs else None) for name in anchor.expected}
        res.found = found
        for name, want in anchor.expected.items():
            got = found[name]
            if got is None or (got != want if kind == "signatures" else not got.startswith(want)):
                res.status = "mismatch"
        return res
    if kind == "defs_present":
        defs = _top_defs(tree)
        missing = [n for n in anchor.expected if n not in defs]
        res.found = {"missing": missing, "public": sorted(n for n in defs if not n.startswith("_"))}
        if missing:
            res.status = "mismatch"
        return res
    res.status, res.found = "mismatch", f"unknown anchor kind {kind}"
    return res


def _check_c11(res: AnchorResult, contracts_dir: Path) -> AnchorResult:
    if not contracts_dir.is_dir():
        res.status = "missing"
        return res
    cands = [p for p in walk_files(contracts_dir, suffixes=(".json",), max_depth=4) if "c11_admin_action" in p.name]
    schemas = [p for p in cands if "schema" in p.name] or cands
    res.found = [rel_posix(p, contracts_dir) for p in cands]
    for schema_path in schemas:
        schema = read_json(schema_path)
        if not isinstance(schema, dict):
            continue
        required = set(schema.get("required") or [])
        pattern = ((schema.get("properties") or {}).get("store_id") or {}).get("pattern")
        if {"store_id", "actor", "reason"} <= required and pattern == "^[a-z0-9-]{1,32}$":
            res.extra = {"schema": rel_posix(schema_path, contracts_dir)}
            return res
    res.status = "mismatch" if cands else "missing"
    res.expected = "required ⊇ {store_id, actor, reason}; store_id.pattern ^[a-z0-9-]{1,32}$"
    return res


def story_decks_problems(data: Any) -> list[str]:
    """Structural facts from the brief: stories → display_name, reference, variants{boy_a4,…} → filenames."""
    problems: list[str] = []
    if not isinstance(data, dict) or not isinstance(data.get("stories"), dict):
        return ["top-level `stories` object missing"]
    for key, story in data["stories"].items():
        if not isinstance(story, dict):
            problems.append(f"{key}: not an object")
            continue
        for fld in ("display_name", "reference", "variants"):
            if fld not in story:
                problems.append(f"{key}: missing {fld}")
        variants = story.get("variants") or {}
        if isinstance(variants, dict):
            unknown = set(variants) - {"boy_a4", "boy_a5", "girl_a4", "girl_a5"}
            if unknown:
                problems.append(f"{key}: unknown variant keys {sorted(unknown)}")
            for vk, fname in variants.items():
                if not isinstance(fname, str) or not fname.lower().endswith(".pptx"):
                    problems.append(f"{key}.{vk}: not a .pptx filename")
    return problems


# ------------------------------------------------- behaviour comparison on drift ----

def compare_signing_behaviour(path: Path) -> dict:
    """Run the vendored five vectors through the DEVICE copy's ``signature()``."""
    ref = _vendor.signing()
    try:
        dev = _vendor.load_module_from(path, f"mx_device_signing_{abs(hash(str(path)))}")
    except Exception as exc:  # noqa: BLE001
        return {"file": path.name, "loaded": False, "error": f"{exc.__class__.__name__}: {exc}"}
    rows = []
    for v in ref.TEST_VECTORS:
        try:
            got = dev.signature(ref.TEST_SECRET, v["method"], v["path"], v["timestamp"], v["body"])
        except Exception as exc:  # noqa: BLE001
            got = f"error: {exc}"
        rows.append({"name": v["name"], "ok": got == v["signature"]})
    has_replay = hasattr(dev, "check_replay")
    return {"file": path.name, "loaded": True, "vectors_pass": sum(r["ok"] for r in rows), "vectors": rows,
            "check_replay_present": has_replay,
            "verdict": "same_signing_behaviour" if all(r["ok"] for r in rows) else "DIFFERENT_SIGNING"}


def _pdf_known_answers() -> list[tuple[str, bytes]]:
    font_page = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>"
                 b"endobj\n3 0 obj<</Type/Page/Parent 2 0 R/Resources<</Font<</F1 4 0 R>>>>>>endobj\n"
                 b"4 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF")
    image_only = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R 4 0 R]"
                  b"/Count 2>>endobj\n3 0 obj<</Type/Page/Parent 2 0 R>>endobj\n4 0 obj<</Type/Page/Parent 2 0 R>>"
                  b"endobj\ntrailer<</Root 1 0 R>>\n%%EOF")
    inner = b"<</Type/Page>> <</Type/Font/BaseFont/Amiri>>"
    packed = zlib.compress(inner)
    compressed = (b"%PDF-1.5\n5 0 obj<</Length " + str(len(packed)).encode() + b"/Filter/FlateDecode>>stream\n"
                  + packed + b"\nendstream endobj\n%%EOF")
    return [("font_page", font_page), ("image_only", image_only), ("flate_stream", compressed),
            ("not_pdf", b"PK\x03\x04"), ("empty", b"")]


def compare_pdf_stats_behaviour(path: Path) -> dict:
    """Feed known-answer PDFs to the DEVICE copy's ``pdf_stats`` and the vendored one."""
    ref = _vendor.pptx_to_pdf()
    try:
        dev = _vendor.load_module_from(path, f"mx_device_pptx_to_pdf_{abs(hash(str(path)))}")
    except Exception as exc:  # noqa: BLE001
        return {"file": path.name, "loaded": False, "error": f"{exc.__class__.__name__}: {exc}"}
    rows = []
    for name, data in _pdf_known_answers():
        want = ref.pdf_stats(data)
        try:
            got = dev.pdf_stats(data)
        except Exception as exc:  # noqa: BLE001
            got = {"error": str(exc)}
        rows.append({"name": name, "ok": got == want, "vendored": want, "device": got})
    extras = sorted(set(dir(dev)) - set(dir(ref)))
    return {"file": path.name, "loaded": True, "known_answers_pass": sum(r["ok"] for r in rows),
            "known_answers": rows, "new_public_names": [n for n in extras if not n.startswith("_")][:30],
            "verdict": "same_pdf_stats" if all(r["ok"] for r in rows) else "DIFFERENT_PDF_STATS"}


# ---------------------------------------------------------------- entry point ----

def verify(found: dict, *, overrides: dict | None = None,
           table: Callable[[], list[Anchor]] = anchor_table) -> dict:
    """Check every anchor. ``found`` is :func:`mxstudio.kit.discover.discover` output."""
    overrides = overrides or {}
    root = Path(found["root"])
    results: list[dict] = []
    for anchor in table():
        sdir = system_dir(found, anchor.system)
        if sdir is None:
            results.append(AnchorResult(anchor.id, anchor.system, anchor.file, anchor.kind, "absent_system",
                                        anchor.expected, severity=anchor.severity).as_dict())
            continue
        try:
            results.append(_check(anchor, sdir, root, overrides).as_dict())
        except Exception as exc:  # noqa: BLE001 - one broken anchor must not hide the others
            results.append(AnchorResult(anchor.id, anchor.system, anchor.file, anchor.kind, "mismatch",
                                        anchor.expected, found=f"checker error: {exc}",
                                        severity=anchor.severity).as_dict())
    for r in results:  # JSON-safe
        json.dumps(r, default=str)
    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {"root": str(root), "anchors": results, "counts": counts}


def by_id(verified: dict) -> dict[str, dict]:
    return {a["id"]: a for a in verified.get("anchors", [])}
