"""Publish: M1 template-set candidate (OM) + M2 deck-contract candidate (Console) + signed pack.

Nothing here activates anything. OM activates a set only through its own
`story_engine.add_story()` / `update_story()` after the operator confirms; the
Console's human approval writes the story contract. The Studio produces
candidates, signs them with the operator's vendored contract, and keeps the
previous approved set so rollback is byte-identical.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import sys
import time
import zipfile
from pathlib import Path

VENDOR = Path(__file__).resolve().parents[2] / "vendor" / "modulex"
SIZE_KEY = {"A4": "a4", "A5": "a5"}


def _signing():
    if str(VENDOR) not in sys.path:
        sys.path.insert(0, str(VENDOR))
    return importlib.import_module("modulex_signing")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def m1_candidate(story, built: dict, validation: dict) -> dict:
    """OM story-registry v2 entry (brief Appendix B.2) + file hashes; activation stays with OM."""
    variants: dict = {}
    files = {}
    for entry in built["variants"].values():
        language, gender = entry["variant"].split("_")
        slot = variants.setdefault(entry["size"], {"size": entry["size"]}).setdefault(language, {})
        slot["male" if gender == "boy" else "female"] = {"file": entry["file"], "base_name": entry["base_name"]}
        files[entry["file"]] = sha256_file(Path(entry["path"]))
    entry = {"_v2": True, "variants": variants, "characters_count": story.characters_count,
             "extra_characters": list(story.extra_characters), "figure_prompt_male": story.figure_prompt_male,
             "figure_prompt_female": story.figure_prompt_female, "logo_config": {}}
    return {"contract": "mag/v1/m1", "schema_version": 1, "story_key": story.key,
            "display_name": story.title.get("ar", story.key), "registry_entry": entry, "files": files,
            "replacements_additions": {}, "validation_ok": bool(validation.get("ok")),
            "validation_sha256": hashlib.sha256(json.dumps(validation, sort_keys=True, ensure_ascii=False,
                                                           default=str).encode()).hexdigest(),
            "created_at": time.time(), "activation": "operator confirm → OM story_engine.add_story()/update_story()"}


def m2_candidate(story, built: dict, validation: dict) -> dict:
    """Console story_decks.json entry (Appendix B.5) + measured slot maps; approval stays on the Console."""
    variants, slot_maps, hashes = {}, {}, {}
    reference = None
    for key, entry in built["variants"].items():
        language, gender = entry["variant"].split("_")
        if language != "ar":
            continue
        name = f"{gender}_{SIZE_KEY[entry['size']]}"
        variants[name] = entry["file"]
        slot_maps[name] = validation["variants"][key]["facts"]["slots"]["measured"]
        hashes[name] = sha256_file(Path(entry["path"]))
        if name == "girl_a4":
            reference = entry["file"]
    return {"contract": "mag/v1/m2", "schema_version": 1, "story_key": story.key,
            "story_decks_entry": {"display_name": story.title.get("ar", story.key),
                                  "reference": reference or next(iter(variants.values()), None), "variants": variants},
            "slot_maps": {k: {str(s): n for s, n in v.items()} for k, v in slot_maps.items()},
            "deck_sha256": hashes, "measured_with": "deck_picture_slots (verbatim port, sha-pinned)",
            "approval": "human, on the Console (the Studio never writes approvals.log.jsonl)"}


def build_pack(out_path: Path, story, built: dict, validation: dict, secret: str, key_id: str = "default") -> dict:
    """Signed pack = zip(files + manifest.json) + manifest.sig (HMAC via the vendored modulex_signing)."""
    signing = _signing()
    m1, m2 = m1_candidate(story, built, validation), m2_candidate(story, built, validation)
    manifest = {"pack": "mag/v1", "story_key": story.key, "m1": m1, "m2": m2,
                "validation": {k: {"ok": v["ok"], "findings": v["findings"]} for k, v in validation["variants"].items()}}
    raw = json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode("utf-8")
    timestamp = str(int(time.time()))
    path = f"/internal/mag/v1/packs/{story.key}"
    signature = signing.signature(secret, "POST", path, timestamp, raw)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for entry in built["variants"].values():
            archive.write(entry["path"], f"templates/{entry['file']}")
        archive.writestr("manifest.json", raw)
        archive.writestr("manifest.sig", json.dumps({"method": "POST", "path": path, "timestamp": timestamp,
                                                     "signature": signature, "key_id": key_id}))
    return {"pack": str(out_path), "sha256": sha256_file(out_path), "manifest_sha256": hashlib.sha256(raw).hexdigest()}


def verify_pack(pack: Path, secret: str, max_age_seconds: int | None = None) -> dict:
    signing = _signing()
    with zipfile.ZipFile(pack) as archive:
        raw = archive.read("manifest.json")
        sig = json.loads(archive.read("manifest.sig"))
        manifest = json.loads(raw)
        ok, reason = signing.verify(secret=secret, method=sig["method"], path=sig["path"], body=raw,
                                    timestamp=sig["timestamp"], signature=sig["signature"],
                                    max_skew_seconds=max_age_seconds if max_age_seconds is not None else 10 ** 9)
        file_errors = []
        for name, digest in manifest["m1"]["files"].items():
            data = archive.read(f"templates/{name}")
            if hashlib.sha256(data).hexdigest() != digest:
                file_errors.append(name)
    return {"ok": ok and not file_errors, "signature": reason, "file_errors": file_errors,
            "story_key": manifest["story_key"]}
