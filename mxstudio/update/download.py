"""Resumable, verified downloads (installer updates, LibreOffice MSI, font vault, shape packs).

Rules:
* bytes land in ``<dest>.part`` with a ``<dest>.part.json`` sidecar naming the URL and the
  expected sha256; a later call resumes with an HTTP ``Range`` request only when the sidecar
  matches, otherwise it starts over;
* the file becomes ``<dest>`` only after size and sha256 match; on mismatch the partial file
  is deleted and :class:`IntegrityError` is raised — nothing unverified is ever kept;
* ``https`` only (the transport is injectable so tests never touch the network);
* progress is reported as facts plus ready-made Arabic/English lines with Arabic-Indic digits.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .errors import IntegrityError, UpdateError

CHUNK = 1 << 16
ARABIC_DIGITS = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")


@dataclass
class Response:
    """What a transport returns: HTTP status, total size if known, and a byte iterator."""

    status: int
    total: int | None
    chunks: Iterator[bytes]


Transport = Callable[[str, int], Response]
Progress = Callable[[dict], None]


def urllib_transport(url: str, offset: int, timeout: float = 60.0) -> Response:
    """Default transport: stdlib urllib (honours HTTPS_PROXY), follows redirects."""
    request = urllib.request.Request(url, headers={"User-Agent": "ModuleX-MagazineStudio-Updater"})
    if offset:
        request.add_header("Range", f"bytes={offset}-")
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        if exc.code == 416:
            return Response(416, None, iter(()))
        raise
    status = response.status
    total = None
    content_range = response.headers.get("Content-Range", "")
    match = re.search(r"/(\d+)$", content_range)
    if match:
        total = int(match.group(1))
    elif response.headers.get("Content-Length"):
        total = int(response.headers["Content-Length"]) + (offset if status == 206 else 0)

    def _iter() -> Iterator[bytes]:
        with response:
            while True:
                block = response.read(CHUNK)
                if not block:
                    return
                yield block

    return Response(status, total, _iter())


def to_digits(text: str, digits: str = "arabic_indic") -> str:
    return text.translate(ARABIC_DIGITS) if digits == "arabic_indic" else text


def progress_line(label_ar: str, label_en: str, done: int, total: int | None, *, digits: str = "arabic_indic",
                  resumed_from: int = 0) -> dict:
    """A progress record the UI can show as-is (Arabic first)."""
    mb_done = done / 1_048_576
    if total:
        pct = int(done * 100 / total)
        ar = f"بننزّل {label_ar}… {to_digits(str(pct), digits)}٪ ({to_digits(f'{mb_done:.1f}', digits)} م.ب من {to_digits(f'{total / 1_048_576:.1f}', digits)})"
        en = f"Downloading {label_en}… {pct}% ({mb_done:.1f} of {total / 1_048_576:.1f} MB)"
    else:
        pct = None
        ar = f"بننزّل {label_ar}… {to_digits(f'{mb_done:.1f}', digits)} م.ب"
        en = f"Downloading {label_en}… {mb_done:.1f} MB"
    if resumed_from:
        ar += " — كمّلنا من مكان ما وقف"
        en += " (resumed)"
    return {"done": done, "total": total, "percent": pct, "ar": ar, "en": en, "resumed_from": resumed_from}


def _sidecar(part: Path) -> Path:
    return part.with_name(part.name + ".json")


def _hash_existing(part: Path) -> tuple[Any, int]:
    digest = hashlib.sha256()
    size = 0
    with open(part, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
            size += len(block)
    return digest, size


def download(url: str, dest: Path, *, sha256: str, size: int | None = None, transport: Transport | None = None,
             progress: Progress | None = None, label_ar: str = "الملف", label_en: str = "the file",
             digits: str = "arabic_indic", cancel: Callable[[], bool] | None = None,
             require_https: bool = True) -> Path:
    """Download ``url`` to ``dest`` (resuming a matching ``.part``), verify, then rename."""
    if require_https and urlparse(url).scheme != "https":
        raise UpdateError("insecure_url", "الرابط لازم يكون https.", "Only https URLs are downloaded.")
    if not re.fullmatch(r"[0-9a-f]{64}", sha256 or ""):
        raise IntegrityError("unpinned", "الملف ده ملوش بصمة sha256 مثبّتة، فمش هننزّله.",
                             "This file has no pinned sha256, so it is not downloaded.")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and verify_file(dest, sha256, size, raise_on_fail=False):
        if progress:
            progress(progress_line(label_ar, label_en, dest.stat().st_size, dest.stat().st_size, digits=digits))
        return dest
    part = dest.with_name(dest.name + ".part")
    meta = {"url": url, "sha256": sha256}
    offset = 0
    digest = hashlib.sha256()
    if part.is_file():
        try:
            old = json.loads(_sidecar(part).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            old = {}
        if old == meta:
            digest, offset = _hash_existing(part)
        else:
            part.unlink()
    _sidecar(part).write_text(json.dumps(meta), encoding="utf-8")
    transport = transport or urllib_transport
    try:
        response = transport(url, offset)
    except OSError as exc:
        raise UpdateError("offline", "مش قادرين نوصل للسيرفر دلوقتي — هنحاول تاني بعدين.",
                          f"Could not reach the server ({type(exc).__name__}).") from exc
    resumed_from = 0
    if offset and response.status == 206:
        resumed_from = offset
        mode = "ab"
    elif offset and response.status == 416 and size and offset >= size:
        mode = None  # server says nothing left: the part is complete
    else:
        if response.status not in (200, 206):
            raise UpdateError("http_error", f"السيرفر رجّع {response.status}.", f"Server returned HTTP {response.status}.")
        offset = 0
        digest = hashlib.sha256()
        mode = "wb"
    total = response.total or size
    done = offset
    if mode:
        with open(part, mode) as handle:
            try:
                for block in response.chunks:
                    if cancel and cancel():
                        raise UpdateError("cancelled", "التنزيل اتوقف — هيكمّل من نفس المكان بعدين.",
                                          "Download paused; it will resume from the same byte later.")
                    handle.write(block)
                    digest.update(block)
                    done += len(block)
                    if size and done > size:
                        break
                    if progress:
                        progress(progress_line(label_ar, label_en, done, total, digits=digits,
                                               resumed_from=resumed_from))
            except OSError as exc:
                raise UpdateError("interrupted", "التنزيل اتقطع — هيكمّل من نفس المكان المرة الجاية.",
                                  f"Download interrupted ({type(exc).__name__}); it resumes next time.") from exc
    actual_size = part.stat().st_size
    if (size and actual_size != size) or digest.hexdigest() != sha256:
        part.unlink(missing_ok=True)
        _sidecar(part).unlink(missing_ok=True)
        raise IntegrityError("sha256_mismatch",
                             "الملف اللي نزل مش مطابق للبصمة المثبّتة واتمسح — مش هنستخدمه.",
                             "The downloaded file does not match its pinned sha256/size and was deleted.")
    os.replace(part, dest)
    _sidecar(part).unlink(missing_ok=True)
    return dest


def verify_file(path: Path, sha256: str, size: int | None = None, *, raise_on_fail: bool = True) -> bool:
    path = Path(path)
    ok = path.is_file() and (not size or path.stat().st_size == size)
    if ok:
        digest, _ = _hash_existing(path)
        ok = digest.hexdigest() == sha256
    if not ok and raise_on_fail:
        raise IntegrityError("sha256_mismatch", f"الملف {path.name} مش مطابق للبصمة.",
                             f"{path.name} does not match its recorded sha256.")
    return ok
