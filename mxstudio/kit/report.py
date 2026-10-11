"""Device report: ``MAG_DEVICE_REPORT_<date>.zip`` for a later cloud session to read.

Contents: discover.json, anchors.json, probe.json, patches.json (plan + manifests), proofs/ (latest
signed proof report), logs/kit.log.jsonl, README.txt. Rules:
* no secrets: environment values are never collected; any value of the known secret variables found
  in the text is replaced, and the archive is re-scanned before it is written;
* no customer data: child names in output file names («<child> - <story> …»), order ids (UUIDs,
  ``order_<id>``, 8-hex upper-case refs), e-mail addresses and phone numbers are redacted.
"""
from __future__ import annotations

import io
import json
import os
import re
import zipfile
from pathlib import Path
from typing import Any

from . import KIT_VERSION
from ._util import kit_home, log_event, now_iso, today_stamp

SECRET_ENVS = ("MODULEX_HMAC_SECRET", "ORCHESTRATOR_HMAC_SECRET", "API_HMAC_SECRET")
_RULES = (
    (re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"), "<uuid>"),
    (re.compile(r"order_[0-9A-Za-z\-]+"), "order_<redacted>"),
    (re.compile(r"(?<![0-9A-Za-z])[0-9A-F]{8}(?![0-9A-Za-z])"), "<ref>"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "<email>"),
    (re.compile(r"(?<![0-9A-Za-z])(?:\+20[ -]?|0)1[0125]\d{8}(?![0-9A-Za-z])"), "<phone>"),
    # «<child> - <story> (AR) [A5]» and «… — ModuleX.pptx»: keep the story, drop the child
    (re.compile(r"[^\\/\"'\n<>]{1,60}? - (?=[^\\/\"'\n]{1,120}\((?:AR|EN)\) \[(?:A4|A5)\])"), "<child> - "),
)


def redact(text: str, secrets: tuple[str, ...] = ()) -> str:
    for secret in secrets:
        if secret and len(secret) >= 6:
            text = text.replace(secret, "<secret>")
    for rx, repl in _RULES:
        text = rx.sub(repl, text)
    return text


def _secrets() -> tuple[str, ...]:
    return tuple(v for v in (os.environ.get(n, "").strip() for n in SECRET_ENVS) if v)


def build_report(root: Path | str | None = None, *, out_dir: Path | None = None, proofs_dir: Path | None = None,
                 sections: dict[str, Any] | None = None, include_probe: bool = True, probe_kwargs: dict | None = None,
                 extra_secrets: tuple[str, ...] = ()) -> dict:
    from .anchors import verify
    from .apply import manifests, plan
    from .discover import discover
    from .probe import probe

    found = discover(root)
    data: dict[str, Any] = dict(sections or {})
    data.setdefault("discover", found)
    data.setdefault("anchors", verify(found))
    if include_probe:
        data.setdefault("probe", probe(found, **(probe_kwargs or {})))
    data.setdefault("patches", {"plan": plan(found["root"], with_diffs=False), "manifests": manifests(found["root"])})
    secrets = _secrets() + tuple(extra_secrets)
    files: dict[str, bytes] = {}
    for name, obj in data.items():
        files[f"{name}.json"] = redact(json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True, default=str),
                                       secrets).encode("utf-8")
    pdir = Path(proofs_dir) if proofs_dir else _latest_proofs()
    if pdir and (pdir / "proof_report.json").is_file():
        files["proofs/proof_report.json"] = (pdir / "proof_report.json").read_bytes()  # signed bytes: verbatim
        files["proofs/proof_report.sig.json"] = (pdir / "proof_report.sig.json").read_bytes()
        files["proofs/NOTE.txt"] = (b"proof_report.json is kept byte-identical so its Ed25519 signature verifies; "
                                    b"it was written without customer data (template copies, synthetic child name).\n"
                                    )
    log = kit_home() / "kit.log.jsonl"
    if log.is_file():
        files["logs/kit.log.jsonl"] = redact(log.read_text(encoding="utf-8", errors="replace"), secrets).encode("utf-8")
    files["README.txt"] = (
        f"MAG device report · Kit {KIT_VERSION} · {now_iso()}\n"
        "تقرير الجهاز: anchors / probe / patches / proofs / logs — من غير أسرار ومن غير بيانات عملاء.\n"
        "Device report: anchors, probe, patches, proofs, logs — no secrets, no customer data.\n"
        "Verify proofs: mxstudio.kit._keys.verify(proof_report.json bytes, proof_report.sig.json).\n").encode()
    for name, blob in files.items():
        if name.startswith("proofs/"):
            continue
        text = blob.decode("utf-8", "replace")
        if any(s and len(s) >= 6 and s in text for s in secrets):
            raise RuntimeError(f"secret survived redaction in {name}")
    out_dir = Path(out_dir) if out_dir else kit_home() / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"MAG_DEVICE_REPORT_{today_stamp()}.zip"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in sorted(files):
            z.writestr(name, files[name])
    path.write_bytes(buf.getvalue())
    log_event("report", path=str(path))
    return {"result": "ok", "path": str(path), "members": sorted(files)}


def _latest_proofs() -> Path | None:
    base = kit_home() / "proofs"
    if not base.is_dir():
        return None
    dirs = sorted(d for d in base.iterdir() if (d / "proof_report.json").is_file())
    return dirs[-1] if dirs else None
