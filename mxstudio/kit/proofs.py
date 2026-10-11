"""On-Device Proof Runner: facts only PowerPoint on the operator's PC can prove, signed.

Steps (each recorded with its own status; nothing is inferred when a step cannot run):
1. export proofs — every template COPY through the vendored ``pptx_to_pdf.convert`` (engine order
   PowerPoint first unless overridden) in a hidden child; pages vs visible slides, font objects,
   deck typefaces vs PDF fonts (substitutions), picture-slot map of the deck (Console rule);
2. a real ``generate_story`` dry run under OM's own interpreter, output to a temp folder; the
   templates folder is hashed before/after to prove it was not touched;
3. deck font validator — template typefaces vs installed fonts (and per-user-only installs);
4. preflight v2 on a sample exported PDF with the vendored ``mx_preflight2`` (if shipped);
then a proof report signed with the Studio's Ed25519 key.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import _keys
from ._pdfscan import norm_font
from ._util import kit_home, log_event, now_iso, sha256_file, walk_files, write_json
from .discover import discover, load_story_decks, system_dir
from .probe import DEFAULT_BASE_NAMES, installed_fonts, template_anatomy, typeface_visibility

Runner = Callable[..., Any]
REPO_ROOT = Path(__file__).resolve().parents[2]


def _runner(runner: Runner | None) -> Runner:
    if runner:
        return runner
    from mxstudio.proc import run_hidden

    return run_hidden


def _python() -> str:
    return os.environ.get("MXS_PYTHON") or sys.executable


def tree_hash(d: Path) -> dict[str, str | None]:
    return {p.relative_to(d).as_posix(): sha256_file(p) for p in walk_files(d, max_depth=3)} if d.is_dir() else {}


def export_proof(copy: Path, out_pdf: Path, anatomy: dict, *, engines: str, runner: Runner,
                 timeout: int = 900) -> dict:
    visible = anatomy.get("slide_count", 0) - len(anatomy.get("hidden_slides", []))
    env = {"MX_PPTX_SRC": str(copy), "MX_PPTX_DST": str(out_pdf), "MXS_KIT_ENGINES": engines,
           "MX_EXPECT_PAGES": str(visible), "PYTHONPATH": str(REPO_ROOT)}
    try:
        res = runner([_python(), "-m", "mxstudio.kit._export_child"], env=env, timeout=timeout)
        rec = json.loads((res.stdout or b"").decode("utf-8", "replace").strip().splitlines()[-1])
    except Exception as exc:  # noqa: BLE001
        return {"template": anatomy.get("file"), "status": "error", "error": f"{exc.__class__.__name__}: {exc}"}
    if not rec.get("ok"):
        return {"template": anatomy.get("file"), "status": "failed", "error": rec.get("error"),
                "attempts": rec.get("attempts")}
    pdf_keys = {norm_font(f) for f in rec.get("pdf_fonts", [])}
    typefaces = [t for t in anatomy.get("typefaces", []) if t and not t.startswith("+")]
    substituted = [t for t in typefaces if norm_font(t) not in pdf_keys]
    findings = []
    if rec.get("page_mismatch"):
        findings.append({"id": "page_count_mismatch", "detail": rec["page_mismatch"]})
    if rec.get("pages") != visible:
        findings.append({"id": "pages_vs_visible_slides", "pages": rec.get("pages"), "visible_slides": visible})
    if substituted:
        findings.append({"id": "typeface_not_in_pdf", "typefaces": substituted})
    return {"template": anatomy.get("file"), "status": "exported", "engine": rec.get("engine"),
            "engine_label": rec.get("engine_label"), "pages": rec.get("pages"), "visible_slides": visible,
            "font_objects": rec.get("fonts"), "has_text": rec.get("has_text"), "pdf_fonts": rec.get("pdf_fonts"),
            "deck_typefaces": typefaces, "picture_slots": anatomy.get("picture_slots"), "findings": findings,
            "pdf_sha256": rec.get("sha256"), "placeholder_roundtrip": "pending: PowerPoint open/save round-trip "
                                                                       "is not automated in this phase"}


def _om_python(om: Path) -> str:
    env = os.environ.get("MXS_OM_PYTHON")
    if env:
        return env
    for rel in ("venv/Scripts/python.exe", ".venv/Scripts/python.exe", "venv/bin/python", ".venv/bin/python"):
        if (om / rel).is_file():
            return str(om / rel)
    return sys.executable


def story_dry_run(om: Path, console: Path | None, *, story: str | None, runner: Runner, size: str = "A5",
                  gender: str = "male", language: str = "ar", child_name: str = "تجربة",
                  base_names: tuple[str, ...] = DEFAULT_BASE_NAMES) -> dict:
    if not story and console is not None:
        decks = load_story_decks(console) or {}
        story = next((s.get("display_name") for s in (decks.get("stories") or {}).values()
                      if isinstance(s, dict) and s.get("display_name")), None)
    if not story:
        return {"status": "skipped", "reason": "no story name (pass --story)"}
    tdir = om / "story_templates"
    before = tree_hash(tdir)
    with tempfile.TemporaryDirectory(prefix="mx_story_") as td:
        env = {"MX_OM_ROOT": str(om), "MX_OUT_DIR": td, "MX_STORY": story, "MX_CHILD_NAME": child_name,
               "MX_GENDER": gender, "MX_LANGUAGE": language, "MX_SIZE": size,
               "MX_SCRIPT": str(Path(__file__).with_name("_story_child.py"))}
        boot = "import os,runpy; runpy.run_path(os.environ['MX_SCRIPT'], run_name='__main__')"
        try:
            res = runner([_om_python(om), "-c", boot], env=env, timeout=600, cwd=td)
            rec = json.loads((res.stdout or b"").decode("utf-8", "replace").strip().splitlines()[-1])
        except Exception as exc:  # noqa: BLE001
            rec = {"ok": False, "error": f"{exc.__class__.__name__}: {exc}"}
        analysis = []
        for name in rec.get("outputs", []) if rec.get("ok") else []:
            anatomy = template_anatomy(Path(td) / name, tuple(base_names) + (child_name,))
            occ = anatomy.get("name_occurrences", [])
            analysis.append({"output": "<child> - " + name.split(" - ", 1)[-1] if " - " in name else "<output>",
                             "child_name_hits": sum(1 for o in occ if o["base_name"] == child_name),
                             "base_name_left": [o for o in occ if o["base_name"] != child_name],
                             "slides": anatomy.get("slide_count")})
    after = tree_hash(tdir)
    rec.pop("returned", None)
    rec["outputs"] = len(rec.get("outputs", []))
    findings = [{"id": "base_name_left_after_generate", "output": a["output"]} for a in analysis if a["base_name_left"]]
    if rec.get("ok") and not analysis:
        findings.append({"id": "no_output_written"})
    return {"status": "ran" if rec.get("ok") else "failed", "story": story, "size": size, "gender": gender,
            "language": language, "child": rec, "analysis": analysis, "findings": findings,
            "templates_untouched": before == after}


def preflight_v2_sample(pdf: Path | None, size_cm: list | None) -> dict:
    if pdf is None:
        return {"status": "skipped", "reason": "no exported PDF"}
    from .patches.base import PatchError, lib_files, mxlibs_dir

    try:
        lib_files("mx_preflight2")
    except PatchError as exc:
        return {"status": "pending", "reason": str(exc)}
    sys.path.insert(0, str(mxlibs_dir()))
    try:
        import mx_preflight2

        size = "A5" if size_cm and min(size_cm) < 16 else "A4"
        return {"status": "ran", "result": mx_preflight2.run(str(pdf), {"size": size, "bleed_mm": 0.0})}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": f"{exc.__class__.__name__}: {exc}"}
    finally:
        try:
            sys.path.remove(str(mxlibs_dir()))
        except ValueError:
            pass


def run_proofs(root: Path | str | None = None, *, engines: str = "powerpoint,soffice", runner: Runner | None = None,
               limit: int | None = None, story: str | None = None, run_story: bool = True,
               out_dir: Path | None = None) -> dict:
    run = _runner(runner)
    found = discover(root)
    om = system_dir(found, "OM")
    console = system_dir(found, "Console")
    stamp = now_iso().replace(":", "").replace("-", "")
    work = Path(out_dir) if out_dir else kit_home() / "proofs" / stamp
    work.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"kind": "mag_device_proofs", "created_at": now_iso(), "engines": engines,
                              "platform": sys.platform, "steps": {}}
    tdir = om / "story_templates" if om else None
    templates = sorted(p for p in tdir.iterdir() if p.suffix.lower() == ".pptx") if tdir and tdir.is_dir() else []
    if limit:
        templates = templates[:limit]
    before = tree_hash(tdir) if tdir else {}
    exports, sample_pdf, sample_size = [], None, None
    for i, tpl in enumerate(templates):
        copy_dir = work / "copies"
        copy_dir.mkdir(exist_ok=True)
        copy = copy_dir / f"t{i:02d}.pptx"
        shutil.copyfile(tpl, copy)
        anatomy = template_anatomy(copy)
        anatomy["file"] = tpl.name
        out_pdf = work / "pdf" / f"t{i:02d}.pdf"
        out_pdf.parent.mkdir(exist_ok=True)
        row = export_proof(copy, out_pdf, anatomy, engines=engines, runner=run)
        exports.append(row)
        if row["status"] == "exported" and sample_pdf is None:
            sample_pdf, sample_size = out_pdf, anatomy.get("slide_size_cm")
    report["steps"]["export"] = {"templates": len(templates), "results": exports,
                                 "templates_untouched": before == (tree_hash(tdir) if tdir else {})}
    if run_story and om:
        report["steps"]["generate_story"] = story_dry_run(om, console, story=story, runner=run)
    else:
        report["steps"]["generate_story"] = {"status": "skipped"}
    fonts = installed_fonts(run if runner else None)
    typefaces = sorted({t for r in exports for t in r.get("deck_typefaces", [])} |
                       {t for p in templates for t in template_anatomy(p).get("typefaces", [])})
    vis = typeface_visibility(typefaces, fonts) if fonts.get("available") else []
    report["steps"]["fonts"] = {"available": fonts.get("available"), "typefaces": vis,
                                "missing": [v["typeface"] for v in vis if not v["installed"]],
                                "user_scope_only": [v["typeface"] for v in vis if v["user_scope_only"]]}
    report["steps"]["preflight_v2"] = preflight_v2_sample(sample_pdf, sample_size)
    body = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8")
    sig = _keys.sign(body)
    (work / "proof_report.json").write_bytes(body)
    write_json(work / "proof_report.sig.json", sig)
    log_event("proofs", dir=str(work), templates=len(templates))
    return {"result": "ok", "dir": str(work), "report": report, "signature": sig}


def verify_report(report_dir: Path) -> bool:
    body = (Path(report_dir) / "proof_report.json").read_bytes()
    sig = json.loads((Path(report_dir) / "proof_report.sig.json").read_text(encoding="utf-8"))
    return _keys.verify(body, sig) and sig.get("sha256") == __import__("hashlib").sha256(body).hexdigest()
