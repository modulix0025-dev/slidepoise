"""API keys: Windows DPAPI per user, never returned, never logged.

The API surface only ever exposes a fingerprint (first 8 hex of sha256). On
Windows the value is encrypted with ``CryptProtectData`` bound to the current
user. Elsewhere (cloud tests, Linux CI) the store keeps the file 0600 and says
so in `backend` — it is a development store, not a protection claim.
"""
from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
import sys
import threading
from pathlib import Path

from mxstudio.config import app_home


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi(data: bytes, protect: bool) -> bytes:  # pragma: no cover - Windows only, exercised on windows CI
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    buffer = ctypes.create_string_buffer(data, len(data))
    blob_in = _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    blob_out = _Blob()
    entropy_raw = b"ModuleX Magazine Studio"
    entropy_buf = ctypes.create_string_buffer(entropy_raw, len(entropy_raw))
    entropy = _Blob(len(entropy_raw), ctypes.cast(entropy_buf, ctypes.POINTER(ctypes.c_char)))
    flags = 0x1  # CRYPTPROTECT_UI_FORBIDDEN
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    ok = fn(ctypes.byref(blob_in), None, ctypes.byref(entropy), None, None, flags, ctypes.byref(blob_out))
    if not ok:
        raise OSError("DPAPI call failed")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


class SecretStore:
    def __init__(self, path: Path | None = None):
        self.path = path or app_home() / "secrets.json"
        self._lock = threading.Lock()
        self.backend = "dpapi" if sys.platform == "win32" else "file-0600-dev"

    def _read(self) -> dict:
        if not self.path.is_file():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        if sys.platform != "win32":
            os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    def _seal(self, value: str) -> str:
        raw = value.encode("utf-8")
        if self.backend == "dpapi":  # pragma: no cover
            raw = _dpapi(raw, True)
        return base64.b64encode(raw).decode("ascii")

    def _open(self, sealed: str) -> str:
        raw = base64.b64decode(sealed)
        if self.backend == "dpapi":  # pragma: no cover
            raw = _dpapi(raw, False)
        return raw.decode("utf-8")

    def set(self, name: str, value: str) -> dict:
        if not name or not value:
            raise ValueError("secret name and value are required")
        with self._lock:
            data = self._read()
            data[name] = {"sealed": self._seal(value), "fingerprint": fingerprint(value), "backend": self.backend}
            self._write(data)
        return self.describe(name)

    def get(self, name: str) -> str | None:
        """Plaintext for in-process provider calls only. Never put this in a response or a log."""
        entry = self._read().get(name)
        return self._open(entry["sealed"]) if entry else None

    def describe(self, name: str) -> dict:
        entry = self._read().get(name)
        if not entry:
            return {"name": name, "set": False}
        return {"name": name, "set": True, "fingerprint": entry["fingerprint"], "backend": entry["backend"]}

    def list(self) -> list[dict]:
        return [self.describe(name) for name in sorted(self._read())]

    def delete(self, name: str) -> bool:
        with self._lock:
            data = self._read()
            existed = data.pop(name, None) is not None
            self._write(data)
        return existed
