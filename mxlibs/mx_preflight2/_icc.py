"""Read the two ICC facts a preflight needs: the profile description and its colour space.

Rule enforced: profiles are identified by their bytes (sha256) and their own
header/description tag, never by a file name.
"""

from __future__ import annotations

import hashlib
import struct


def colour_space(data: bytes) -> str:
    """ICC header data colour space signature, e.g. 'RGB', 'CMYK', 'GRAY'."""
    if len(data) < 20:
        return ""
    return data[16:20].decode("latin-1").strip()


def description(data: bytes) -> str:
    """The profile's 'desc' tag (ICC v2 textDescriptionType or v4 multiLocalizedUnicodeType)."""
    try:
        count = struct.unpack(">I", data[128:132])[0]
        for i in range(min(count, 256)):
            sig, offset, size = struct.unpack(">4sII", data[132 + 12 * i : 144 + 12 * i])
            if sig != b"desc":
                continue
            tag = data[offset : offset + size]
            kind = tag[:4]
            if kind == b"desc":
                length = struct.unpack(">I", tag[8:12])[0]
                return tag[12 : 12 + length].split(b"\x00", 1)[0].decode("latin-1", "replace").strip()
            if kind == b"mluc":
                records = struct.unpack(">I", tag[8:12])[0]
                if records:
                    _lang, _country, rlen, roff = struct.unpack(">2s2sII", tag[16:28])
                    return tag[roff : roff + rlen].decode("utf-16-be", "replace").strip("\x00 ")
    except (struct.error, IndexError):
        return ""
    return ""


def facts(data: bytes) -> dict:
    return {
        "sha256": hashlib.sha256(data).hexdigest(),
        "description": description(data),
        "colour_space": colour_space(data),
        "bytes": len(data),
    }
