"""Shape library (SQLite): tags, favourites, usage, text search, sketch/similarity search.

Rules
* An asset enters only with complete provenance and a print-allowed licence decision; assets
  from AI, vectorising, discovery or packs also need ``approved_by`` (the operator).
* Tags: ``theme``, ``age``, ``mood`` (free text) and ``style`` in ``flat | hand-drawn | outline | 3D``.
* Similarity is a *measurement* (log Hu moments + rotation-invariant contour spectrum on a
  normalised raster) used to rank search results - it never accepts or rejects anything.
* Text search folds Arabic spelling variants (alef forms, ta marbuta, alef maqsura, tashkeel).
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from .custgeom import CustomGeometry
from .discovery.base import ORIGINAL_WORK, Provenance, licence_gate
from .raster import rasterize_geometry

STYLES = ("flat", "hand-drawn", "outline", "3D")
NEEDS_APPROVAL = {"ai", "vectorized", "discovered", "pack"}
ORIGINS = {"preset", "generator", "canvas", "svg", "ai", "vectorized", "discovered", "pack"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS assets (
  id TEXT PRIMARY KEY, name_ar TEXT, name_en TEXT, origin TEXT NOT NULL,
  geometry_json TEXT NOT NULL, custgeom_xml TEXT NOT NULL,
  theme TEXT, age TEXT, mood TEXT, style TEXT, tags_json TEXT NOT NULL DEFAULT '[]',
  palette_json TEXT NOT NULL DEFAULT '[]', stroke_width_pt REAL, corner_radius REAL,
  licence TEXT NOT NULL, licence_status TEXT NOT NULL, credits_required INTEGER NOT NULL DEFAULT 0,
  provenance_json TEXT NOT NULL, approved_by TEXT, created_at TEXT NOT NULL,
  favourite INTEGER NOT NULL DEFAULT 0, use_count INTEGER NOT NULL DEFAULT 0, last_used TEXT,
  descriptor_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS uses (
  asset_id TEXT NOT NULL REFERENCES assets(id), book_id TEXT NOT NULL, page TEXT, used_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS uses_book ON uses(book_id);
"""

_DIACRITICS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")


def fold_text(text: str) -> str:
    """Search normalisation: lower-case, Arabic letter variants folded, tashkeel/tatweel removed."""
    t = _DIACRITICS.sub("", (text or "").lower())
    t = re.sub("[إأآٱ]", "ا", t).replace("ة", "ه").replace("ى", "ي").replace("ؤ", "و").replace("ئ", "ي")
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s-]", " ", t)).strip()


# ------------------------------------------------------------------ descriptors
def normalised_mask(mask: np.ndarray, size: int = 128) -> np.ndarray:
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return np.zeros((size, size), np.uint8)
    crop = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1].astype(np.uint8)
    h, w = crop.shape
    s = (size - 8) / max(h, w)
    small = cv2.resize(crop * 255, (max(1, round(w * s)), max(1, round(h * s))), interpolation=cv2.INTER_AREA)
    out = np.zeros((size, size), np.uint8)
    oy, ox = (size - small.shape[0]) // 2, (size - small.shape[1]) // 2
    out[oy:oy + small.shape[0], ox:ox + small.shape[1]] = (small >= 128).astype(np.uint8)
    return out


def descriptor(mask: np.ndarray) -> dict:
    """Log-scaled Hu moments + 16-coefficient contour spectrum (rotation/start invariant)."""
    m = normalised_mask(mask)
    hu = cv2.HuMoments(cv2.moments(m, binaryImage=True)).flatten()
    log_hu = [float(-math.copysign(1.0, v) * math.log10(abs(v))) if v != 0 else 0.0 for v in hu]
    contours, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    spectrum = [0.0] * 16
    if contours:
        c = max(contours, key=cv2.contourArea).reshape(-1, 2).astype(np.float64)
        if len(c) >= 8:
            seg = np.sqrt((np.diff(np.vstack([c, c[:1]]), axis=0) ** 2).sum(1))
            s = np.concatenate([[0], np.cumsum(seg)])
            t = np.linspace(0, s[-1], 128, endpoint=False)
            xs = np.interp(t, s, np.append(c[:, 0], c[0, 0]))
            ys = np.interp(t, s, np.append(c[:, 1], c[0, 1]))
            r = np.hypot(xs - xs.mean(), ys - ys.mean())
            r = r / (r.mean() or 1.0)
            f = np.abs(np.fft.rfft(r))[1:17] / len(r)
            spectrum = [float(v) for v in f]
    return {"hu": log_hu, "spectrum": spectrum, "fill": float(m.mean())}


def descriptor_distance(a: dict, b: dict) -> float:
    """Weighted distance. Only the first Hu invariant is used: the higher ones of near-symmetric
    shapes are ~0 and their logarithms are numerically unstable (a circle vs a hand-drawn circle)."""
    hu = abs(a["hu"][0] - b["hu"][0])
    sp = math.sqrt(sum((x - y) ** 2 for x, y in zip(a["spectrum"], b["spectrum"])))
    return round(hu * 2.0 + sp * 4.0 + abs(a.get("fill", 0) - b.get("fill", 0)) * 2.0, 6)


def geometry_descriptor(geom: CustomGeometry) -> dict:
    side = 256
    h = max(1, round(side * geom.height / geom.width)) if geom.width >= geom.height else side
    w = side if geom.width >= geom.height else max(1, round(side * geom.width / geom.height))
    return descriptor(rasterize_geometry(geom, w, h))


# ------------------------------------------------------------------ library
@dataclass
class Asset:
    id: str
    name_ar: str
    name_en: str
    origin: str
    geometry: CustomGeometry
    tags: list[str]
    theme: str
    age: str
    mood: str
    style: str
    licence: str
    licence_status: str
    credits_required: bool
    provenance: Provenance
    favourite: bool
    use_count: int
    palette: list[str]
    stroke_width_pt: float | None
    corner_radius: float | None

    def to_json(self, with_geometry: bool = False) -> dict:
        d = {"id": self.id, "name_ar": self.name_ar, "name_en": self.name_en, "origin": self.origin,
             "tags": self.tags, "theme": self.theme, "age": self.age, "mood": self.mood, "style": self.style,
             "licence": self.licence, "licence_status": self.licence_status, "credits_required": self.credits_required,
             "provenance": self.provenance.to_json(), "favourite": self.favourite, "use_count": self.use_count,
             "palette": self.palette, "stroke_width_pt": self.stroke_width_pt, "corner_radius": self.corner_radius}
        if with_geometry:
            d["geometry"] = self.geometry.to_json()
            d["custgeom"] = self.geometry.to_xml()
        return d


class LibraryError(ValueError):
    pass


class ShapeLibrary:
    def __init__(self, path: str | Path = ":memory:") -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), timeout=30)
        self.db.row_factory = sqlite3.Row
        if path != ":memory:":  # the window and MCP servers open this file at the same time
            from mxstudio.sqlite_util import BUSY_TIMEOUT_MS, _wal  # noqa: PLC0415
            self.db.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
            _wal(self.db)
        self.db.executescript(_SCHEMA)
        try:
            self.db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS assets_fts USING fts5(id UNINDEXED, body)")
            self.fts = True
        except sqlite3.OperationalError:  # pragma: no cover - SQLite built without FTS5
            self.fts = False
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    # -------------------------------------------------------------- write
    def add(self, *, geometry: CustomGeometry, origin: str, provenance: Provenance, name_ar: str = "",
            name_en: str = "", tags: list[str] | None = None, theme: str = "", age: str = "", mood: str = "",
            style: str = "flat", palette: list[str] | None = None, stroke_width_pt: float | None = None,
            corner_radius: float | None = None, approved_by: str = "") -> str:
        if origin not in ORIGINS:
            raise LibraryError(f"unknown origin {origin!r}")
        if style not in STYLES:
            raise LibraryError(f"style must be one of {STYLES}")
        if origin in NEEDS_APPROVAL and not (approved_by or provenance.approved_by).strip():
            raise LibraryError("operator approval is required before this asset enters the library")
        missing = provenance.missing()
        if missing:
            raise LibraryError(f"provenance incomplete: {missing}")
        decision = licence_gate(provenance.licence, attribution_required=provenance.credits_required)
        if not decision.printable:
            raise LibraryError(f"licence refused for print: {provenance.licence} ({decision.reason_en})")
        if not geometry.parts:
            raise LibraryError("empty geometry")
        asset_id = uuid.uuid4().hex[:16]
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        desc = geometry_descriptor(geometry)
        tags = sorted({t.strip() for t in (tags or []) if t and t.strip()})
        self.db.execute(
            "INSERT INTO assets (id,name_ar,name_en,origin,geometry_json,custgeom_xml,theme,age,mood,style,tags_json,"
            "palette_json,stroke_width_pt,corner_radius,licence,licence_status,credits_required,provenance_json,"
            "approved_by,created_at,descriptor_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (asset_id, name_ar, name_en, origin, geometry.dumps(), geometry.to_xml(), theme, age, mood, style,
             json.dumps(tags, ensure_ascii=False), json.dumps(palette or []), stroke_width_pt, corner_radius,
             provenance.licence, decision.status, int(decision.credits_required),
             json.dumps(provenance.to_json(), ensure_ascii=False), approved_by or provenance.approved_by, now,
             json.dumps(desc)))
        if self.fts:
            body = fold_text(" ".join([name_ar, name_en, theme, age, mood, style, " ".join(tags), provenance.title]))
            self.db.execute("INSERT INTO assets_fts (id, body) VALUES (?, ?)", (asset_id, body))
        self.db.commit()
        return asset_id

    def add_original(self, geometry: CustomGeometry, origin: str, *, author: str, source_url: str, **kw) -> str:
        """Studio-made shapes (generator, canvas, preset) - provenance is the Studio itself."""
        data = geometry.dumps().encode("utf-8")
        import hashlib

        prov = Provenance(source=f"mxstudio:{origin}", source_url=source_url, author=author, licence=ORIGINAL_WORK,
                          licence_url="", retrieved_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                          sha256=hashlib.sha256(data).hexdigest(), title=kw.get("name_en", ""))
        return self.add(geometry=geometry, origin=origin, provenance=prov, **kw)

    def set_favourite(self, asset_id: str, on: bool = True) -> None:
        self._require(asset_id)
        self.db.execute("UPDATE assets SET favourite=? WHERE id=?", (int(bool(on)), asset_id))
        self.db.commit()

    def set_tags(self, asset_id: str, tags: list[str]) -> None:
        self._require(asset_id)
        tags = sorted({t.strip() for t in tags if t and t.strip()})
        self.db.execute("UPDATE assets SET tags_json=? WHERE id=?", (json.dumps(tags, ensure_ascii=False), asset_id))
        if self.fts:
            row = self.db.execute("SELECT * FROM assets WHERE id=?", (asset_id,)).fetchone()
            body = fold_text(" ".join([row["name_ar"] or "", row["name_en"] or "", row["theme"] or "", row["age"] or "",
                                       row["mood"] or "", row["style"] or "", " ".join(tags)]))
            self.db.execute("UPDATE assets_fts SET body=? WHERE id=?", (body, asset_id))
        self.db.commit()

    def record_use(self, asset_id: str, book_id: str, page: str | int | None = None) -> int:
        self._require(asset_id)
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        self.db.execute("INSERT INTO uses (asset_id, book_id, page, used_at) VALUES (?,?,?,?)",
                        (asset_id, str(book_id), None if page is None else str(page), now))
        self.db.execute("UPDATE assets SET use_count=use_count+1, last_used=? WHERE id=?", (now, asset_id))
        self.db.commit()
        return int(self.db.execute("SELECT use_count FROM assets WHERE id=?", (asset_id,)).fetchone()[0])

    # -------------------------------------------------------------- read
    def _require(self, asset_id: str) -> None:
        if not self.db.execute("SELECT 1 FROM assets WHERE id=?", (asset_id,)).fetchone():
            raise KeyError(asset_id)

    def _row(self, row) -> Asset:
        return Asset(id=row["id"], name_ar=row["name_ar"] or "", name_en=row["name_en"] or "", origin=row["origin"],
                     geometry=CustomGeometry.from_json(json.loads(row["geometry_json"])),
                     tags=json.loads(row["tags_json"]), theme=row["theme"] or "", age=row["age"] or "",
                     mood=row["mood"] or "", style=row["style"] or "", licence=row["licence"],
                     licence_status=row["licence_status"], credits_required=bool(row["credits_required"]),
                     provenance=Provenance.from_json(json.loads(row["provenance_json"])),
                     favourite=bool(row["favourite"]), use_count=int(row["use_count"]),
                     palette=json.loads(row["palette_json"]), stroke_width_pt=row["stroke_width_pt"],
                     corner_radius=row["corner_radius"])

    def get(self, asset_id: str) -> Asset:
        row = self.db.execute("SELECT * FROM assets WHERE id=?", (asset_id,)).fetchone()
        if not row:
            raise KeyError(asset_id)
        return self._row(row)

    def all(self) -> list[Asset]:
        return [self._row(r) for r in self.db.execute("SELECT * FROM assets ORDER BY created_at, id")]

    def favourites(self) -> list[Asset]:
        return [self._row(r) for r in self.db.execute("SELECT * FROM assets WHERE favourite=1 ORDER BY id")]

    def most_used(self, limit: int = 20) -> list[Asset]:
        return [self._row(r) for r in self.db.execute(
            "SELECT * FROM assets WHERE use_count>0 ORDER BY use_count DESC, id LIMIT ?", (int(limit),))]

    def uses_in_book(self, book_id: str) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM uses WHERE book_id=? ORDER BY used_at", (book_id,))]

    def search_text(self, query: str, *, style: str | None = None, theme: str | None = None, age: str | None = None,
                    favourites_only: bool = False, limit: int = 50) -> list[Asset]:
        terms = [t for t in fold_text(query).split() if t]
        ids: list[str] | None = None
        if terms:
            if self.fts:
                q = " AND ".join('"' + t.replace('"', "") + '"*' for t in terms)
                ids = [r[0] for r in self.db.execute("SELECT id FROM assets_fts WHERE assets_fts MATCH ? ORDER BY rank",
                                                     (q,))]
            else:  # pragma: no cover
                ids = [a.id for a in self.all() if all(t in fold_text(" ".join([a.name_ar, a.name_en, *a.tags]))
                                                       for t in terms)]
        rows = []
        for a in (self.all() if ids is None else [self.get(i) for i in ids]):
            if style and a.style != style:
                continue
            if theme and fold_text(a.theme) != fold_text(theme):
                continue
            if age and a.age != age:
                continue
            if favourites_only and not a.favourite:
                continue
            rows.append(a)
        if ids is None:
            rows.sort(key=lambda a: (-a.favourite, -a.use_count, a.id))
        return rows[: int(limit)]

    def search_similar(self, *, mask: np.ndarray | None = None, geometry: CustomGeometry | None = None,
                       limit: int = 10) -> list[tuple[float, Asset]]:
        """Rank by shape similarity to a sketch (mask) or a geometry; smaller distance = closer."""
        if mask is None and geometry is None:
            raise ValueError("give a sketch mask or a geometry")
        target = descriptor(mask) if mask is not None else geometry_descriptor(geometry)
        scored = []
        for r in self.db.execute("SELECT id, descriptor_json FROM assets"):
            scored.append((descriptor_distance(target, json.loads(r["descriptor_json"])), r["id"]))
        scored.sort()
        return [(d, self.get(i)) for d, i in scored[: int(limit)]]
