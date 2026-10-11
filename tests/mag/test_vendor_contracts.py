"""The two operator contracts are vendored byte-identically, never re-derived.

Appendix C/D of the brief give the sha256 of the operator's originals. If either
file changes by one byte these tests fail; the negative controls prove the checks
can fail.
"""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import pytest

VENDOR = Path(__file__).resolve().parents[2] / "vendor" / "modulex"
EXPECTED = {
    "pptx_to_pdf.py": "2920eb32048e286604a60fe98229763f3932898b3c8150f08f3cd2b1539d7eee",
    "modulex_signing.py": "a2f1db607288413e6e631dca8f63e523e6916612d6ec97af55906dfe509d347e",
}


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_vendored_file_is_byte_identical(name):
    assert hashlib.sha256((VENDOR / name).read_bytes()).hexdigest() == EXPECTED[name]


def test_sha256sums_manifest_matches():
    lines = (VENDOR / "SHA256SUMS").read_text(encoding="ascii").splitlines()
    listed = {line.split()[1]: line.split()[0] for line in lines if line.strip()}
    assert listed == EXPECTED


def test_signing_selftest_five_vectors():
    signing = _load("mx_vendor_signing", VENDOR / "modulex_signing.py")
    rows = signing.selftest()
    assert [r["name"] for r in rows] == ["register", "assign", "heartbeat", "drain", "health"]
    assert all(r["ok"] for r in rows)


def test_signing_verify_and_replay_guard():
    signing = _load("mx_vendor_signing", VENDOR / "modulex_signing.py")
    body = b'{"x":1}'
    headers = signing.sign("s3cret", "POST", "/internal/mag/v1/health", body, timestamp=1700000000)
    ok, why = signing.verify(secret="s3cret", method="POST", path="/internal/mag/v1/health", body=body,
                             timestamp=headers[signing.HEADER_TS], signature=headers[signing.HEADER_SIG],
                             now=1700000010)
    assert ok, why
    guard = signing.ReplayGuard(ttl_seconds=300, max_entries=10)
    assert signing.check_replay(headers[signing.HEADER_SIG], guard=guard, now=1700000010, env={})[0]
    assert not signing.check_replay(headers[signing.HEADER_SIG], guard=guard, now=1700000011, env={})[0]


def test_negative_control_mutated_signing_copy_fails(tmp_path):
    """A one-character change to the canonical string must break the vectors and the hash."""
    src = (VENDOR / "modulex_signing.py").read_text(encoding="utf-8")
    mutated = src.replace('return "\\n".join([method.upper(), path, str(timestamp), body_hash])',
                          'return "\\n".join([method.upper(), path, str(timestamp), body_hash, ""])', 1)
    assert mutated != src, "mutation anchor not found — the negative control would be vacuous"
    path = tmp_path / "modulex_signing.py"
    path.write_text(mutated, encoding="utf-8")
    assert hashlib.sha256(path.read_bytes()).hexdigest() != EXPECTED["modulex_signing.py"]
    rows = _load("mx_mutated_signing", path).selftest()
    assert not any(r["ok"] for r in rows)


def test_pdf_stats_refuses_image_only_pdf_and_accepts_fonts():
    conv = _load("mx_vendor_pptx_to_pdf", VENDOR / "pptx_to_pdf.py")
    image_only = b"%PDF-1.4\n1 0 obj << /Type /Page /Resources << /XObject << /Im0 2 0 R >> >> >> endobj\n"
    with_font = image_only + b"3 0 obj << /Type /Font /BaseFont /NotoNaskhArabic >> endobj\n"
    assert conv.pdf_stats(image_only)["has_text"] is False
    assert conv.pdf_stats(with_font)["has_text"] is True
    assert conv.pdf_stats(b"not a pdf")["ok"] is False
