"""Phase 0 read-only template anatomy measurement for ModuleX story templates.

Reads every .pptx under a templates folder and writes MAG_TEMPLATE_ANATOMY.json.
It never modifies a template. When --console-root is given, picture slots are
counted with the Console's own magazine_pptx.deck_picture_slots; otherwise a
local re-implementation is used and the record says so.

Usage (Windows, from any folder):
    set PYTHONUTF8=1
    python mag_template_anatomy.py --templates "C:\\المشروع\\OrderManagement\\story_templates" ^
        --console-root "C:\\المشروع\\ModuleX_Console" --base-name "<base name>" --output MAG_TEMPLATE_ANATOMY.json
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any

from lxml import etree

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}
EMU_PER_CM = 360000
EMU_PER_INCH = 914400
SLIDE_RE = re.compile(r"^ppt/slides/slide(\d+)\.xml$")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_console_slot_counter(console_root: Path | None):
    if console_root is None:
        return None, "local_reimplementation_unverified"
    candidates = list(console_root.rglob("magazine_pptx.py"))
    if not candidates:
        return None, f"console_root_given_but_magazine_pptx_not_found:{console_root}"
    spec = importlib.util.spec_from_file_location("mx_console_magazine_pptx", candidates[0])
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(candidates[0].parent.parent.parent))
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return getattr(module, "deck_picture_slots"), f"console:{candidates[0]}"


def local_picture_slots(archive: zipfile.ZipFile) -> dict[int, int]:
    """Count empty <p:sp> carrying <p:ph type="pic"> per slideN.xml (brief §3.4 rule)."""
    counts: dict[int, int] = {}
    for name in archive.namelist():
        match = SLIDE_RE.match(name)
        if not match:
            continue
        root = etree.fromstring(archive.read(name))
        count = 0
        for shape in root.iterfind(".//p:sp", NS):
            ph = shape.find("./p:nvSpPr/p:nvPr/p:ph", NS)
            if ph is not None and ph.get("type") == "pic" and shape.find(".//a:blip", NS) is None:
                count += 1
        counts[int(match.group(1))] = count
    return dict(sorted(counts.items()))


def _slide_order(archive: zipfile.ZipFile) -> list[tuple[str, bool]]:
    pres = etree.fromstring(archive.read("ppt/presentation.xml"))
    rels = etree.fromstring(archive.read("ppt/_rels/presentation.xml.rels"))
    targets = {rel.get("Id"): rel.get("Target") for rel in rels.iterfind("rel:Relationship", NS)}
    order = []
    for sld in pres.iterfind("./p:sldIdLst/p:sldId", NS):
        target = targets[sld.get(f"{{{NS['r']}}}id")].lstrip("/")
        part = target if target.startswith("ppt/") else f"ppt/{target}"
        slide = etree.fromstring(archive.read(part))
        order.append((part, slide.get("show") == "0"))
    return order


def _rels(archive: zipfile.ZipFile, part: str) -> dict[str, str]:
    folder, name = part.rsplit("/", 1)
    rel_part = f"{folder}/_rels/{name}.rels"
    if rel_part not in archive.namelist():
        return {}
    root = etree.fromstring(archive.read(rel_part))
    out = {}
    for rel in root.iterfind("rel:Relationship", NS):
        target = rel.get("Target")
        if rel.get("TargetMode") == "External":
            continue
        out[rel.get("Id")] = str(Path(folder, target).as_posix()).replace("ppt/slides/../", "ppt/")
    return out


def _xfrm(shape) -> list[int] | None:
    off = shape.find(".//a:xfrm/a:off", NS)
    ext = shape.find(".//a:xfrm/a:ext", NS)
    if off is None or ext is None:
        return None
    return [int(off.get("x")), int(off.get("y")), int(ext.get("cx")), int(ext.get("cy"))]


def _text_shapes(slide, base_name: str | None) -> list[dict[str, Any]]:
    records = []
    for shape in slide.iterfind(".//p:sp", NS):
        body = shape.find("./p:txBody", NS)
        if body is None:
            continue
        c_nv = shape.find("./p:nvSpPr/p:cNvPr", NS)
        paragraphs = []
        for para in body.iterfind("./a:p", NS):
            runs = para.findall("./a:r", NS)
            texts = [(run.findtext("./a:t", default="", namespaces=NS)) for run in runs]
            joined = "".join(texts)
            if not joined.strip():
                continue
            ppr = para.find("./a:pPr", NS)
            run_records = []
            for run, text in zip(runs, texts):
                rpr = run.find("./a:rPr", NS)
                run_records.append({
                    "text": text,
                    "sz_pt": (int(rpr.get("sz")) / 100) if rpr is not None and rpr.get("sz") else None,
                    "lang": rpr.get("lang") if rpr is not None else None,
                    "latin": _typeface(rpr, "latin"),
                    "cs": _typeface(rpr, "cs"),
                    "ea": _typeface(rpr, "ea"),
                })
            record = {
                "text": joined,
                "rtl": ppr.get("rtl") if ppr is not None else None,
                "algn": ppr.get("algn") if ppr is not None else None,
                "runs": run_records,
            }
            if base_name:
                single = sum(text.count(base_name) for text in texts)
                total = joined.count(base_name)
                record["base_name"] = {"total": total, "in_single_run": single, "split_across_runs": total - single}
            paragraphs.append(record)
        if paragraphs:
            body_pr = body.find("./a:bodyPr", NS)
            autofit = None
            if body_pr is not None:
                for tag in ("noAutofit", "normAutofit", "spAutofit"):
                    if body_pr.find(f"./a:{tag}", NS) is not None:
                        autofit = tag
            records.append({
                "shape_id": c_nv.get("id") if c_nv is not None else None,
                "name": c_nv.get("name") if c_nv is not None else None,
                "box_emu": _xfrm(shape),
                "autofit": autofit,
                "rtlCol": body_pr.get("rtlCol") if body_pr is not None else None,
                "paragraphs": paragraphs,
            })
    return records


def _typeface(rpr, tag: str) -> str | None:
    if rpr is None:
        return None
    node = rpr.find(f"./a:{tag}", NS)
    return node.get("typeface") if node is not None else None


def _images(archive: zipfile.ZipFile, slide, rels: dict[str, str], size: tuple[int, int]) -> list[dict[str, Any]]:
    from PIL import Image

    out = []
    for pic in slide.iterfind(".//p:pic", NS):
        blip = pic.find(".//a:blip", NS)
        box = _xfrm(pic)
        if blip is None or box is None:
            continue
        part = rels.get(blip.get(f"{{{NS['r']}}}embed"))
        record: dict[str, Any] = {"part": part, "box_emu": box}
        if part and part in archive.namelist():
            try:
                with Image.open(io.BytesIO(archive.read(part))) as image:
                    width_px, height_px = image.size
                record["pixels"] = [width_px, height_px]
                if box[2] and box[3]:
                    record["effective_dpi"] = round(min(width_px / (box[2] / EMU_PER_INCH), height_px / (box[3] / EMU_PER_INCH)), 1)
            except Exception as exc:  # unreadable / vector media is reported, not fatal
                record["error"] = type(exc).__name__
        x, y, w, h = box
        record["touches_trim"] = {"left": x <= 0, "top": y <= 0, "right": x + w >= size[0], "bottom": y + h >= size[1]}
        out.append(record)
    return out


def measure(path: Path, base_name: str | None, console_counter) -> dict[str, Any]:
    with zipfile.ZipFile(path) as archive:
        pres = etree.fromstring(archive.read("ppt/presentation.xml"))
        sld_sz = pres.find("./p:sldSz", NS)
        size = (int(sld_sz.get("cx")), int(sld_sz.get("cy")))
        order = _slide_order(archive)
        slides = []
        typefaces: dict[str, int] = {}
        for index, (part, hidden) in enumerate(order, start=1):
            slide = etree.fromstring(archive.read(part))
            rels = _rels(archive, part)
            texts = _text_shapes(slide, base_name)
            for shape in texts:
                for para in shape["paragraphs"]:
                    for run in para["runs"]:
                        for key in ("latin", "cs", "ea"):
                            if run[key]:
                                typefaces[run[key]] = typefaces.get(run[key], 0) + 1
            slides.append({
                "index": index,
                "part": part,
                "hidden": hidden,
                "text_shapes": texts,
                "images": _images(archive, slide, rels, size),
            })
        local_slots = local_picture_slots(archive)
    console_slots = None
    if console_counter is not None:
        console_slots = console_counter(str(path))
    base_total = sum(p.get("base_name", {}).get("total", 0) for s in slides for t in s["text_shapes"] for p in t["paragraphs"])
    base_split = sum(p.get("base_name", {}).get("split_across_runs", 0) for s in slides for t in s["text_shapes"] for p in t["paragraphs"])
    return {
        "file": path.name,
        "sha256": _sha256(path),
        "slide_size_emu": list(size),
        "slide_size_cm": [round(size[0] / EMU_PER_CM, 3), round(size[1] / EMU_PER_CM, 3)],
        "slide_count": len(slides),
        "hidden_slides": [s["index"] for s in slides if s["hidden"]],
        "picture_slots_local": local_slots,
        "picture_slots_local_total": sum(local_slots.values()),
        "picture_slots_console": console_slots,
        "typefaces": dict(sorted(typefaces.items())),
        "base_name_total": base_total if base_name else None,
        "base_name_split_across_runs": base_split if base_name else None,
        "slides": slides,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--templates", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--base-name", action="append", default=[], help="story base_name; repeat for several (AR/EN)")
    parser.add_argument("--console-root", type=Path)
    args = parser.parse_args(argv)
    counter, counter_source = _load_console_slot_counter(args.console_root)
    templates = sorted(args.templates.rglob("*.pptx"))
    records = []
    for path in templates:
        base = next((name for name in args.base_name if name and _contains(path, name)), None)
        try:
            records.append(measure(path, base, counter) | {"base_name_used": base})
        except Exception as exc:
            records.append({"file": path.name, "error": f"{type(exc).__name__}: {exc}"})
    report = {
        "schema": "mag-template-anatomy/1",
        "templates_root": str(args.templates),
        "picture_slot_counter": counter_source,
        "count": len(records),
        "templates": records,
    }
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"written": str(args.output), "templates": len(records), "slot_counter": counter_source}, ensure_ascii=False))
    return 0


def _contains(path: Path, needle: str) -> bool:
    with zipfile.ZipFile(path) as archive:
        return any(needle in archive.read(name).decode("utf-8", "ignore") for name in archive.namelist() if SLIDE_RE.match(name))


if __name__ == "__main__":
    raise SystemExit(main())
