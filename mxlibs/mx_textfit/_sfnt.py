"""Minimal stdlib reader for the sfnt tables a fitter needs (name, OS/2, head, hhea, cmap).

Rule enforced: font identity comes from the font's own ``name`` table, never
from the file name, and reading it needs no third-party package. Only the
tables used for family resolution, line metrics and glyph coverage are read,
by seeking, so scanning a whole font folder never loads whole font files.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from functools import lru_cache

_SFNT_TAGS = (b"\x00\x01\x00\x00", b"OTTO", b"true", b"typ1")


class SfntError(ValueError):
    """The file is not a font this reader understands."""


@dataclass(frozen=True)
class SfntInfo:
    names: dict = field(default_factory=dict)  # name id -> string
    weight: int = 400
    italic: bool = False
    upem: int = 1000
    win_ascent: int = 0
    win_descent: int = 0
    hhea_ascent: int = 0
    hhea_descent: int = 0
    line_gap: int = 0

    @property
    def office_line_units(self) -> int:
        """Office lays out single-spaced lines on the Windows ascent + descent box."""
        return max(self.win_ascent + self.win_descent, self.hhea_ascent - self.hhea_descent + self.line_gap, 1)


def _read(handle, offset: int, length: int) -> bytes:
    handle.seek(offset)
    data = handle.read(length)
    if len(data) != length:
        raise SfntError("truncated font file")
    return data


def _offsets(handle) -> list[int]:
    head = _read(handle, 0, 12)
    if head[:4] == b"ttcf":
        count = struct.unpack(">I", head[8:12])[0]
        if count > 1024:
            raise SfntError("implausible collection size")
        return list(struct.unpack(f">{count}I", _read(handle, 12, 4 * count)))
    if head[:4] in _SFNT_TAGS:
        return [0]
    raise SfntError("not an sfnt font")


def _table_bytes(handle, offset: int, wanted: tuple[str, ...]) -> dict[str, bytes]:
    num = struct.unpack(">H", _read(handle, offset + 4, 2))[0]
    directory = _read(handle, offset + 12, 16 * num)
    out: dict[str, bytes] = {}
    for i in range(num):
        tag, _checksum, start, length = struct.unpack(">4sIII", directory[16 * i : 16 * i + 16])
        name = tag.decode("latin-1")
        if name in wanted and length < 64 * 1024 * 1024:
            out[name] = _read(handle, start, length)
    return out


def _decode_name(platform: int, encoding: int, raw: bytes) -> str:
    if platform in (0, 3):
        return raw.decode("utf-16-be", "replace")
    if platform == 1 and encoding == 0:
        return raw.decode("mac_roman", "replace")
    return raw.decode("latin-1", "replace")


def _names(table: bytes | None) -> dict[int, str]:
    if not table:
        return {}
    _fmt, count, string_off = struct.unpack(">HHH", table[:6])
    best: dict[int, tuple[int, str]] = {}
    for i in range(count):
        rec = 6 + 12 * i
        platform, encoding, language, name_id, length, off = struct.unpack(">HHHHHH", table[rec : rec + 12])
        raw = table[string_off + off : string_off + off + length]
        # Preference: Windows en-US, other Windows, Unicode, Mac Roman.
        if platform == 3 and language == 0x409:
            rank = 0
        elif platform == 3:
            rank = 1
        elif platform == 0:
            rank = 2
        elif platform == 1 and language == 0:
            rank = 3
        else:
            continue
        text = _decode_name(platform, encoding, raw)
        if name_id not in best or rank < best[name_id][0]:
            best[name_id] = (rank, text)
    return {name_id: text for name_id, (_rank, text) in best.items()}


def _info(tables: dict[str, bytes]) -> SfntInfo:
    weight, italic, win_ascent, win_descent = 400, False, 0, 0
    os2 = tables.get("OS/2")
    if os2 and len(os2) >= 6:
        weight = struct.unpack(">H", os2[4:6])[0] or 400
        if len(os2) >= 64:
            italic = bool(struct.unpack(">H", os2[62:64])[0] & 1)
        if len(os2) >= 78:
            win_ascent, win_descent = struct.unpack(">HH", os2[74:78])
    upem = 1000
    head = tables.get("head")
    if head and len(head) >= 20:
        upem = struct.unpack(">H", head[18:20])[0] or 1000
    hhea_ascent = hhea_descent = line_gap = 0
    hhea = tables.get("hhea")
    if hhea and len(hhea) >= 10:
        hhea_ascent, hhea_descent, line_gap = struct.unpack(">hhh", hhea[4:10])
    return SfntInfo(
        names=_names(tables.get("name")),
        weight=int(weight),
        italic=italic,
        upem=int(upem),
        win_ascent=int(win_ascent),
        win_descent=int(win_descent),
        hhea_ascent=int(hhea_ascent),
        hhea_descent=int(hhea_descent),
        line_gap=int(line_gap),
    )


def read_all(path: str) -> list[SfntInfo]:
    """Info for every face in a font file (one for .ttf/.otf, n for a collection)."""
    with open(path, "rb") as handle:
        return [_info(_table_bytes(handle, offset, ("name", "OS/2", "head", "hhea"))) for offset in _offsets(handle)]


@lru_cache(maxsize=128)
def info_for(path: str, index: int = 0) -> SfntInfo:
    with open(path, "rb") as handle:
        offsets = _offsets(handle)
        if index >= len(offsets):
            raise SfntError("font index out of range")
        return _info(_table_bytes(handle, offsets[index], ("name", "OS/2", "head", "hhea")))


def _cmap_codepoints(table: bytes | None) -> frozenset[int]:
    """Code points mapped by the best Unicode cmap subtable (formats 4 and 12)."""
    if not table:
        return frozenset()
    _version, count = struct.unpack(">HH", table[:4])
    candidates = []
    for i in range(count):
        platform, encoding, sub = struct.unpack(">HHI", table[4 + 8 * i : 12 + 8 * i])
        fmt = struct.unpack(">H", table[sub : sub + 2])[0]
        if (platform, encoding) in ((3, 10), (0, 4), (0, 6)) and fmt == 12:
            candidates.append((0, sub, fmt))
        elif (platform, encoding) in ((3, 1), (0, 3), (0, 1), (0, 0)) and fmt == 4:
            candidates.append((1, sub, fmt))
    if not candidates:
        return frozenset()
    _rank, sub, fmt = min(candidates)
    points: set[int] = set()
    if fmt == 4:
        seg_x2 = struct.unpack(">H", table[sub + 6 : sub + 8])[0]
        segs = seg_x2 // 2
        ends = struct.unpack(f">{segs}H", table[sub + 14 : sub + 14 + seg_x2])
        starts_at = sub + 16 + seg_x2
        starts = struct.unpack(f">{segs}H", table[starts_at : starts_at + seg_x2])
        deltas = struct.unpack(f">{segs}h", table[starts_at + seg_x2 : starts_at + 2 * seg_x2])
        range_at = starts_at + 2 * seg_x2
        ranges = struct.unpack(f">{segs}H", table[range_at : range_at + seg_x2])
        for s in range(segs):
            for cp in range(starts[s], ends[s] + 1):
                if cp == 0xFFFF:
                    continue
                if ranges[s] == 0:
                    glyph = (cp + deltas[s]) & 0xFFFF
                else:
                    addr = range_at + 2 * s + ranges[s] + 2 * (cp - starts[s])
                    glyph = struct.unpack(">H", table[addr : addr + 2])[0]
                    if glyph:
                        glyph = (glyph + deltas[s]) & 0xFFFF
                if glyph:
                    points.add(cp)
    else:
        groups = struct.unpack(">I", table[sub + 12 : sub + 16])[0]
        for g in range(groups):
            first, last, glyph = struct.unpack(">III", table[sub + 16 + 12 * g : sub + 28 + 12 * g])
            if last - first > 0x110000:
                continue
            points.update(range(first if glyph else first + 1, last + 1))
    return frozenset(points)


@lru_cache(maxsize=32)
def coverage_for(path: str, index: int = 0) -> frozenset[int]:
    with open(path, "rb") as handle:
        offsets = _offsets(handle)
        return _cmap_codepoints(_table_bytes(handle, offsets[index], ("cmap",)).get("cmap"))
