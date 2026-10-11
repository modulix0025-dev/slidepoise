"""Synthetic replicas of the operator's trees, generated from the brief's ground-truth facts only.

``build(root, mutate=...)`` writes ``<root>/OrderManagement``, ``ModuleX_Console``, ``ModuleX_Store``
and ``ModuleXOrchestrator`` with the exact anchors (signature lines, verbatim bodies copied from
``mxstudio/validators/operator_ports.py``, constants, regexes, sha-pinned contract copies), frozen
files, RUN_TESTS.bat, story templates (with «إياد», a lam-alef presentation-form «ﻹياد», a split
run and a hidden slide), story_decks.json, story contracts, ComfyUI workflows and Store contracts.
Behaviour of the replica functions is plausible, not the operator's — tests only rely on anchors
and on comparing a function with itself before/after a hook.

Mutations (negative controls): see ``MUTATIONS``.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

from pptx import Presentation
from pptx.util import Cm, Pt

ROOT = Path(__file__).resolve().parents[4]
PORTS = ROOT / "mxstudio" / "validators" / "operator_ports.py"
VENDOR = ROOT / "vendor" / "modulex"

MUTATIONS = {
    "om_replace_in_paragraph_body": "one line of replace_in_paragraph changed",
    "om_generate_story_signature": "generate_story default size changed to A5",
    "om_deck_constant": "MIN_DPI = 96",
    "om_deck_apply_signature": "apply() gained a parameter",
    "om_preflight_signature": "preflight.run lost require_approved",
    "console_deck_picture_slots": "deck_picture_slots body changed",
    "console_pptx_to_pdf_comment": "pptx_to_pdf.py gained a trailing comment (same behaviour)",
    "console_pptx_to_pdf_behaviour": "pdf_stats counts fonts differently",
    "om_signing_behaviour": "OM modulex_signing.py canonical string changed",
    "om_two_apps": "a second FastAPI() module in OM",
}


def _blocks() -> dict[str, str]:
    text = PORTS.read_text(encoding="utf-8")
    return {m.group(1): m.group(2) for m in
            re.finditer(r"# ---- PORT BEGIN: ([^\n]*?) ----\n(.*?)# ---- PORT END", text, re.DOTALL)}


def _w(path: Path, text: str, *, crlf: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = text.replace("\n", "\r\n") if crlf else text
    path.write_bytes(data.encode("utf-8"))


def _story_engine(mut: set[str]) -> str:
    block = _blocks()["OM app/services/story_engine.py (Appendix B.1, verbatim)"]
    if "om_replace_in_paragraph_body" in mut:
        block = block.replace("    simple_found = False", "    simple_found = None", 1)
    size_default = '"A5"' if "om_generate_story_signature" in mut else '"A4"'
    return f'''"""OM story engine (SYNTHETIC REPLICA built from the brief's anchors)."""
import json
from pathlib import Path

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

OM_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = OM_ROOT / "story_templates"
REGISTRY = OM_ROOT / "registry_replica.json"
REPLACEMENTS = {{"بكل الحب تهدى لإياد": "بكل الحب تهدى لـ{{child_name}}"}}


def load_registry():
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


{block}

def resolve_variant(stories, story_name, size):
    story = stories["stories"][story_name]
    return story["variants"][size]


def generate_story(story_name, child_name, gender, language, output_folder, size={size_default}):
    variant = resolve_variant(load_registry(), story_name, size)
    entry = variant[language][gender]
    prs = Presentation(str(TEMPLATES_DIR / entry["file"]))
    total = 0
    for slide in prs.slides:
        for shape in slide.shapes:
            total += replace_in_shape(shape, entry["base_name"], child_name)
    for old, new in REPLACEMENTS.items():
        for slide in prs.slides:
            for shape in slide.shapes:
                total += replace_in_shape(shape, old, new.replace("{{child_name}}", child_name))
    out = Path(output_folder) / f"{{child_name}} - {{story_name}} ({{language.upper()}}) [{{size}}].pptx"
    prs.save(str(out))
    return str(out)


def add_story(display_name, ar_male_file, ar_male_base, ar_female_file, ar_female_base,
              en_male_file=None, en_male_base=None, en_female_file=None, en_female_base=None, size="A5"):
    data = load_registry()
    story = data["stories"].setdefault(display_name, {{"variants": {{}}}})
    story["variants"][size] = {{"ar": {{"male": {{"file": ar_male_file, "base_name": ar_male_base}},
                                      "female": {{"file": ar_female_file, "base_name": ar_female_base}}}}}}
    REGISTRY.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return display_name


def update_story(display_name, **fields):
    return display_name
'''


def _deck_py(mut: set[str]) -> str:
    min_dpi = "96" if "om_deck_constant" in mut else "72"
    apply_sig = "deck_in, deck_out, texts, images, inv, strict=False" if "om_deck_apply_signature" in mut \
        else "deck_in, deck_out, texts, images, inv"
    return f'''"""OM editor deck engine P149-b (SYNTHETIC REPLICA built from the brief's anchors)."""
import os
import re
from pathlib import Path

EMU_PER_CM = 360000
IDEAL_DPI = 300
OK_DPI = 150
MIN_DPI = {min_dpi}
MIN_SIDE_PX = 300
MIN_FRAME_CM = 1.5
MAX_TEXT = 2000
MAX_LINES = 30
TEXT_RE = re.compile(r"^t-(\\d{{1,4}})-(\\d{{1,7}})-(\\d{{1,4}})$")
IMG_RE = re.compile(r"^i-(\\d{{1,4}})-(\\d{{1,7}})$")
ENABLED = os.environ.get("MODULEX_P149", "1") != "0"
ORDERS_DIR = Path(__file__).resolve().parents[2] / "orders"


def locate(order):
    d = ORDERS_DIR / str(order)
    return {{"deck": next(iter(sorted(d.glob("*.pptx"))), None), "pdf": next(iter(sorted(d.glob("*.pdf"))), None)}}


def inventory(deck):
    from pptx import Presentation
    prs = Presentation(str(deck))
    texts = {{}}
    for s_no, slide in enumerate(prs.slides, 1):
        for shape in slide.shapes:
            if shape.has_text_frame:
                for p_no, para in enumerate(shape.text_frame.paragraphs):
                    texts[f"t-{{s_no}}-{{shape.shape_id}}-{{p_no}}"] = para.text
    return {{"texts": texts, "images": {{}}}}


def _set_paragraph(p, new):
    runs = p.runs
    if not runs:
        p.text = new
        return
    runs[0].text = new
    for run in runs[1:]:
        run.text = ""


def apply({apply_sig}):
    """Write customer edits into a copy of the deck."""
    from pptx import Presentation
    if len(texts) > 500:
        raise ValueError("too many edits")
    prs = Presentation(str(deck_in))
    changed = 0
    for tid, new in texts.items():
        m = TEXT_RE.match(tid)
        if not m or len(new) > MAX_TEXT:
            raise ValueError(f"bad edit {{tid}}")
        slide = prs.slides[int(m.group(1)) - 1]
        shape = [s for s in slide.shapes if s.shape_id == int(m.group(2))][0]
        _set_paragraph(shape.text_frame.paragraphs[int(m.group(3))], new)
        changed += 1
    prs.save(str(deck_out))
    return {{"changed": changed, "images": len(images or {{}})}}


def export_pdf(deck, pdf, expect_pages, attempts=2):
    data = b"%PDF-1.4\\n% replica export of " + Path(deck).name.encode("utf-8") + b"\\n/Type /Page\\n/BaseFont /X\\n%%EOF"
    Path(pdf).write_bytes(data)
    return {{"ok": True, "pages": expect_pages, "attempts": attempts}}
'''


OM_PRINTING = '''"""OM editor printing glue (SYNTHETIC REPLICA)."""
from app.printing import print_service


def swap_pdf(order_ref, current_path, new_path, actor="editor"):
    print_service.freeze_sent_artifacts(order_ref, current_path, actor=actor)
    print_service.rebind_ready_artifacts(order_ref, new_path, actor=actor)
'''

PRINT_SERVICE = '''"""OM print service — the ONLY writer of print tables (SYNTHETIC REPLICA)."""
EVENTS = []


def freeze_sent_artifacts(order_ref, current_path, actor=None):
    EVENTS.append(("freeze", order_ref, actor))


def rebind_ready_artifacts(order_ref, new_path, actor=None):
    EVENTS.append(("rebind", order_ref, actor))


def _write_job(*a):
    raise RuntimeError("never called by the Kit")
'''


def _preflight(mut: set[str]) -> str:
    approved = "" if "om_preflight_signature" in mut else "require_approved=False, "
    return f'''"""OM printing preflight P129 (SYNTHETIC REPLICA)."""
from decimal import Decimal
from pathlib import Path


def run(path, *, magazine_size="A4", expected_pages=None, expected_sha256=None, output_status=None,
        {approved}bleed_mm=Decimal("0"), max_bytes=200 * 1024 * 1024):
    data = Path(path).read_bytes()
    checks = [{{"id": "is_pdf", "ok": data.startswith(b"%PDF-")}},
              {{"id": "size_limit", "ok": len(data) <= max_bytes}},
              {{"id": "bleed_declared", "ok": bleed_mm >= 0}}]
    return {{"ok": all(c["ok"] for c in checks), "checks": checks, "magazine_size": magazine_size}}
'''


def _om_main() -> str:
    return '''"""OM FastAPI app (SYNTHETIC REPLICA)."""
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app.editor import deck as editor_deck

app = FastAPI(title="OrderManagement replica")


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/api/editor/{order}/inventory")
def editor_inventory(order: str):
    found = editor_deck.locate(order)
    return editor_deck.inventory(found["deck"]) if found["deck"] else {}


@app.get("/editor/{order}", response_class=HTMLResponse)
def editor_page(order: str):
    return "<html><body><div id=\\"editor\\">محرر</div></body></html>"


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
'''


CONSOLE_SERVER = '''"""Execution Console FastAPI app (SYNTHETIC REPLICA)."""
from fastapi import FastAPI

app = FastAPI(title="Console replica")


@app.get("/health")
def health():
    return {"ok": True}
'''


def _magazine_pptx(mut: set[str]) -> str:
    block = _blocks()["Console magazine_pptx.py (Appendix B.4, verbatim)"]
    if "console_deck_picture_slots" in mut:
        block = block.replace("if n:", "if n > 1:", 1)
    return f'''"""Console magazine injection (SYNTHETIC REPLICA built from the brief's verbatim block)."""
import logging
import re

log = logging.getLogger("comfy-mvp")

{block}'''


def _template(path: Path, base: str, *, ligature: bool, typeface: str) -> None:
    prs = Presentation()
    prs.slide_width, prs.slide_height = Cm(14.8), Cm(21.0)
    s1 = prs.slides.add_slide(prs.slide_layouts[8])  # Picture with Caption -> <p:ph type="pic">
    box = s1.shapes.add_textbox(Cm(1), Cm(15), Cm(12), Cm(3))
    para = box.text_frame.paragraphs[0]
    run = para.add_run()
    run.text = f"ذهب {base} إلى البحر"
    run.font.size = Pt(18)
    rpr = run._r.get_or_add_rPr()
    rpr.append(rpr.makeelement("{http://schemas.openxmlformats.org/drawingml/2006/main}cs", {"typeface": typeface}))
    para._p.get_or_add_pPr().set("rtl", "1")
    p2 = box.text_frame.add_paragraph()
    a, b = p2.add_run(), p2.add_run()
    a.text, b.text = base[:2], base[2:] + " سعيد"
    s2 = prs.slides.add_slide(prs.slide_layouts[6])
    ded = s2.shapes.add_textbox(Cm(1), Cm(1), Cm(12), Cm(2))
    lam = "\ufef9" + base[1:] if ligature and base.startswith("إ") else "ل" + base
    ded.text_frame.paragraphs[0].add_run().text = f"بكل الحب تهدى {lam}"
    s3 = prs.slides.add_slide(prs.slide_layouts[6])
    s3._element.set("show", "0")
    s3.shapes.add_textbox(Cm(1), Cm(1), Cm(5), Cm(1)).text_frame.text = "hidden"
    prs.save(str(path))


def build(root: Path, mutate: set[str] | frozenset[str] = frozenset(), *, crlf_deck: bool = False) -> dict:
    """Write the replica estate under ``root`` and return a facts dict for the tests."""
    unknown = set(mutate) - set(MUTATIONS)
    if unknown:
        raise ValueError(f"unknown mutations {unknown}")
    mut = set(mutate)
    root = Path(root)
    om = root / "OrderManagement"
    con = root / "ModuleX_Console"
    store = root / "ModuleX_Store"
    orch = root / "ModuleXOrchestrator"
    for pkg in ("app", "app/services", "app/editor", "app/printing", "app/utils"):
        _w(om / pkg / "__init__.py", "")
    _w(om / "app/services/story_engine.py", _story_engine(mut))
    _w(om / "app/editor/deck.py", _deck_py(mut), crlf=crlf_deck)
    _w(om / "app/editor/printing.py", OM_PRINTING)
    _w(om / "app/editor/deck_pdf.py", '"""FROZEN operator file (replica)."""\nFROZEN = True\n')
    _w(om / "app/printing/print_service.py", PRINT_SERVICE)
    _w(om / "app/printing/preflight.py", _preflight(mut))
    _w(om / "app/utils/config.py", '"""FROZEN operator config (replica)."""\nTEMPLATES_DIR = "story_templates"\n')
    _w(om / "app/main.py", _om_main())
    if "om_two_apps" in mut:
        _w(om / "app/admin_app.py", "from fastapi import FastAPI\n\nadmin = FastAPI()\n")
    _w(om / "app/static/js/ui-utils.js", "function _willReload(){ return false; }\n")
    _w(om / "RUN_TESTS.bat", "@echo off\r\npython -m pytest -q\r\n")
    signing_src = (VENDOR / "modulex_signing.py").read_bytes()
    om_signing = signing_src
    if "om_signing_behaviour" in mut:
        om_signing = signing_src.replace(b'return "\\n".join([method.upper(), path, str(timestamp), body_hash])',
                                         b'return "|".join([method.upper(), path, str(timestamp), body_hash])')
        assert om_signing != signing_src
    (om / "modulex_core").mkdir(parents=True, exist_ok=True)
    _w(om / "modulex_core/__init__.py", "")
    (om / "modulex_core/modulex_signing.py").write_bytes(om_signing)
    tdir = om / "story_templates"
    tdir.mkdir(parents=True, exist_ok=True)
    _template(tdir / "الصدق مع الأرنب a5.pptx", "إياد", ligature=True, typeface="Blabeloo  MagdySoliman")
    _template(tdir / "honesty girl a5.pptx", "جيداء", ligature=False, typeface="Amiri")
    registry = {"stories": {"الصدق مع الأرنب": {"variants": {"A5": {"ar": {
        "male": {"file": "الصدق مع الأرنب a5.pptx", "base_name": "إياد"},
        "female": {"file": "honesty girl a5.pptx", "base_name": "جيداء"}}}}}}}
    _w(om / "registry_replica.json", json.dumps(registry, ensure_ascii=False))
    order = om / "orders" / "ORD-REPLICA-1"
    order.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(tdir / "الصدق مع الأرنب a5.pptx", order / "deck.pptx")
    (order / "order_final.pdf").write_bytes(b"%PDF-1.4\n/Type /Page\n/BaseFont /X\n%%EOF")

    # ---- Console
    for pkg in ("execution_console", "execution_console/services"):
        _w(con / pkg / "__init__.py", "")
    _w(con / "execution_console/services/magazine_pptx.py", _magazine_pptx(mut))
    p2p = (VENDOR / "pptx_to_pdf.py").read_bytes()
    if "console_pptx_to_pdf_comment" in mut:
        p2p += b"\n# operator note: unchanged behaviour\n"
    if "console_pptx_to_pdf_behaviour" in mut:
        p2p = p2p.replace(b'out["has_text"] = fonts > 0', b'out["has_text"] = fonts > 1')
    (con / "execution_console/services/pptx_to_pdf.py").write_bytes(p2p)
    (con / "execution_console/modulex_signing.py").write_bytes(signing_src)
    _w(con / "execution_console/server.py", CONSOLE_SERVER)
    _w(con / "execution_console/qc_agent.py", '"""QC agent (replica)."""\n')
    _w(con / "execution_console/qc_store.py", '"""QC store (replica)."""\n')
    _w(con / "qa_refs/README.txt", "refs\n")
    decks = {"stories": {"honesty": {"display_name": "الصدق مع الأرنب", "reference": "honesty-ref",
                                     "variants": {"boy_a5": "الصدق مع الأرنب a5.pptx",
                                                  "girl_a5": "honesty girl a5.pptx"}}}}
    _w(con / "story_decks.json", json.dumps(decks, ensure_ascii=False, indent=1))
    _w(con / "story_contracts/honesty-0123456789.json", json.dumps({"story": "honesty"}))
    _w(con / "story_contracts/approvals.log.jsonl", '{"story":"honesty","approved_by":"operator"}\n')
    wf_dev = {"4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "flux1-dev-kontext_fp8_scaled.safetensors"}},
              "5": {"class_type": "UNETLoader", "inputs": {"unet_name": "flux1-dev.safetensors"}}}
    wf_ok = {"nodes": [{"type": "UNETLoader", "widgets_values": ["qwen_image_edit_2511_fp8.safetensors"]},
                       {"type": "CheckpointLoaderSimple", "inputs": {}, "widgets_values": ["flux1-schnell.safetensors"]}]}
    _w(con / "workflows/scene_kontext.json", json.dumps(wf_dev))
    _w(con / "workflows/scene_qwen.json", json.dumps(wf_ok))
    _w(con / "RUN_TESTS.bat", "@echo off\r\npython -m pytest -q\r\n")

    # ---- Store
    for mod in ("ledger", "pricing", "topup", "limits", "audit", "config", "db"):
        _w(store / f"mxstore/areas/accounts/editor/{mod}.py", f'"""Store editor {mod} (replica)."""\n')
    c11 = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object",
           "required": ["store_id", "actor", "reason"],
           "properties": {"store_id": {"type": "string", "pattern": "^[a-z0-9-]{1,32}$"},
                          "actor": {"type": "string"}, "reason": {"type": "string"}}}
    _w(store / "contracts/c11_admin_action.schema.json", json.dumps(c11))
    _w(store / "contracts/fixtures/c11_admin_action.valid.json",
       json.dumps({"store_id": "kidx-main", "actor": "op", "reason": "x"}))

    # ---- Orchestrator
    (orch / "contrib").mkdir(parents=True, exist_ok=True)
    (orch / "contrib/modulex_signing.py").write_bytes(signing_src)
    return {"root": root, "om": om, "console": con, "store": store, "orchestrator": orch, "order": "ORD-REPLICA-1"}


if __name__ == "__main__":
    print(build(Path(sys.argv[1]), set(sys.argv[2:])))
