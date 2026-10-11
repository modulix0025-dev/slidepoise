"""The Studio's Ed25519 proof-signing key (one per Windows user).

Rules: the private key is stored DPAPI-protected (CryptProtectData, current user) on Windows and
as an owner-only file elsewhere; it is never logged or exported. Reports carry the public key and
its fingerprint (``sha256(public)[:8]``) so anyone — e.g. a later cloud session — can verify.
"""
from __future__ import annotations

import ctypes
import hashlib
import os
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from ._util import kit_home


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi(data: bytes, protect: bool) -> bytes:  # pragma: no cover - Windows only
    crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = _Blob()
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    ok = fn(ctypes.byref(blob_in), None, None, None, None, 0x1, ctypes.byref(blob_out))  # UI_FORBIDDEN
    if not ok:
        raise OSError("DPAPI call failed")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def _key_path() -> Path:
    return kit_home() / "keys" / "proof_ed25519.key"


def load_or_create() -> Ed25519PrivateKey:
    path = _key_path()
    if path.is_file():
        raw = path.read_bytes()
        if sys.platform == "win32":
            raw = _dpapi(raw, protect=False)
        return Ed25519PrivateKey.from_private_bytes(raw)
    key = Ed25519PrivateKey.generate()
    raw = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                            serialization.NoEncryption())
    path.parent.mkdir(parents=True, exist_ok=True)
    stored = _dpapi(raw, protect=True) if sys.platform == "win32" else raw
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(stored)
    return key


def public_hex(key: Ed25519PrivateKey) -> str:
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()


def fingerprint(public_key_hex: str) -> str:
    return hashlib.sha256(bytes.fromhex(public_key_hex)).hexdigest()[:8]


def sign(data: bytes) -> dict:
    key = load_or_create()
    pub = public_hex(key)
    return {"alg": "ed25519", "public_key": pub, "fingerprint": fingerprint(pub),
            "signature": key.sign(data).hex(), "sha256": hashlib.sha256(data).hexdigest()}


def verify(data: bytes, sig: dict) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(sig["public_key"])).verify(bytes.fromhex(sig["signature"]),
                                                                                   data)
        return True
    except Exception:  # noqa: BLE001
        return False
