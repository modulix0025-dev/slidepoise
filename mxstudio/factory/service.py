"""Factory service: story → variants → validation → contact sheet → candidates, stored in the workspace."""
from __future__ import annotations

import json
from pathlib import Path

from mxstudio.factory.art import contact_sheet
from mxstudio.factory.forge import forge
from mxstudio.factory.publish import m1_candidate, m2_candidate
from mxstudio.factory.story import Story
from mxstudio.factory.validate import strip_specs, validate_set


def build_and_validate(story: Story, out_dir: Path, registry=None, engines=None, export: bool = True) -> dict:
    built = forge(story, out_dir, registry=registry)
    validation = validate_set(built, out_dir, registry=registry, export=export, engines=engines)
    pdfs = [Path(r["facts"]["pdf"]) for r in validation["variants"].values() if r["facts"].get("pdf")]
    sheet = contact_sheet(pdfs, out_dir / f"{story.key}_contact_sheet.png", thumb_height=280) if pdfs else None
    return {"built": built, "validation": validation, "contact_sheet": str(sheet) if sheet else None,
            "m1": m1_candidate(story, built, validation), "m2": m2_candidate(story, built, validation)}


def store(workspace, story: Story, result: dict) -> int:
    blobs = {entry["file"]: workspace.put_file(Path(entry["path"])) for entry in result["built"]["variants"].values()}
    if result.get("contact_sheet"):
        blobs["contact_sheet.png"] = workspace.put_file(Path(result["contact_sheet"]))
    body = {"story": story.as_dict(), "built": strip_specs(result["built"]), "validation": result["validation"],
            "m1": result["m1"], "m2": result["m2"]}
    json.dumps(body, ensure_ascii=False, default=str)  # must be serialisable
    return workspace.save("template_set", story.key, json.loads(json.dumps(body, default=str)), blobs,
                          note="factory build")
