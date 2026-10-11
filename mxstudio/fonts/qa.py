"""Font QA: measured facts → ``certified_print`` / ``screen_only`` / ``rejected`` with named reasons.

What is measured (deterministically, per family, on the upright regular file):

* **coverage** — Arabic base letters, harakat, tatweel, Arabic-Indic digits and
  Arabic punctuation (AR fonts); basic Latin letters, digits and punctuation
  (all fonts); whether the Arabic-Indic digits are drawn with the same outlines
  as the Western ones (they then *look* Western — the Zain observation);
* **shaping corpus** — ≥200 common Egyptian boy/girl names (Arabic for AR
  fonts, the Latin spelling for EN fonts) shaped with HarfBuzz through the fork
  runtime (``slidepoise.arabic.shaping``): .notdef count, Arabic joining
  actually applied, and the dedication form «إهداء لـ<name>»;
* **harakat collisions** — vowelized lines are shaped and every glyph is
  rasterised (non-zero winding, 160 px/em); ink overlap of mark/mark and
  mark/base glyph pairs is counted, and the inter-line requirement (deepest
  descent + highest ascent of any two lines) gives the per-font minimum safe
  line spacing as a multiple of the Office single-line box;
* **embedding** — OS/2 fsType via the licence ledger;
* **colour** — COLR/SVG/CBDT/sbix fonts are quarantined for print.

Status rule: any *blocking* finding → ``rejected``; else any *quarantine*
finding → ``screen_only``; else ``certified_print`` (deterministic checks
passed). *Limit* findings narrow the roles a certified font may take. The
on-device export proof (PowerPoint export on the operator's PC: font embedded
in the PDF, extracted text equals input) is recorded as **pending** — it is
never claimed here. These are measurements, not a visual verdict: the host
Agent / operator still looks at the specimen pages.
"""
from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from fontTools.pens.recordingPen import RecordingPen
from fontTools.ttLib import TTFont

from slidepoise.arabic.fit import min_safe_line_spacing
from slidepoise.arabic.fonts import FontFace
from slidepoise.arabic.shaping import _hb_font, _shape_run, directional_runs, font_metrics, shape

from mxstudio.fonts.build_catalog import sha256_file
from mxstudio.fonts.ledger import embedding_permission
from mxstudio.fonts.paths import HARAKAT_JSON, NAMES_JSON

SCHEMA = "mx.fonts.qa_status/1"
STATUSES = ("certified_print", "screen_only", "rejected")
ARABIC_BASE = [c for c in range(0x0621, 0x064B) if not 0x063B <= c <= 0x0640]
HARAKAT = [*range(0x064B, 0x0653), 0x0670]
INDIC_DIGITS = list(range(0x0660, 0x066A))
ARABIC_PUNCT = [0x060C, 0x061B, 0x061F]
TATWEEL = 0x0640
LATIN_REQUIRED = [ord(c) for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.,!?'-:;()&"]
PX_PER_EM = 160
CLEARANCE = 0.08
#: Measurement thresholds (documented in PHASE_4_NOTES): a mark pair counts as colliding when the shared ink
#: is at least this share of the smaller glyph's ink and at least MIN_PX pixels at 160 px/em.
MARK_MARK_SHARE = 0.02
MARK_BASE_SHARE = 0.10
MIN_PX = 4
ON_DEVICE_STEP = ("Proof Runner › Fonts › «تصدير حقيقي»: install the certified build per-user, open the specimen "
                  "deck in PowerPoint, export PDF, then check the PDF embeds the font (FontFile2 present, name "
                  "matches) and that extracted text equals the input (mxstudio.validators.pdf_text.text_proof)")

FINDINGS: dict[str, tuple[str, str, str]] = {
    # id: (severity, Egyptian Arabic, English)
    "font_unreadable": ("blocking", "ملف الخط مش بيتقري", "the font file cannot be read"),
    "file_sha256_mismatch": ("blocking", "بصمة الملف مش زي الكتالوج", "file sha256 differs from the catalog"),
    "licence_refused": ("blocking", "الترخيص مش مسموح بيه للطباعة", "licence not allowed for print"),
    "embedding_refused": ("blocking", "الخط ممنوع يتضمّن في PDF (fsType)", "fsType forbids document embedding"),
    "arabic_base_missing": ("blocking", "حروف عربية أساسية ناقصة", "Arabic base letters missing"),
    "latin_basic_missing": ("blocking", "حروف لاتينية أساسية ناقصة", "basic Latin characters missing"),
    "names_notdef": ("blocking", "أسامي من القائمة بتطلع مربعات (.notdef)", "corpus names shape to .notdef"),
    "arabic_joining_not_applied": ("blocking", "الحروف العربية مش بتتوصل", "Arabic joining forms are not applied"),
    "colour_font_quarantined": ("quarantine", "خط ملوّن (COLR/SVG): محجوز للشاشة لحد ما يتثبت في PowerPoint والـPDF",
                                "colour font (COLR/SVG/bitmap tables): screen only until proven in PowerPoint and PDF"),
    "monospace_arabic": ("limit", "خط عربي ثابت العرض: لعناوين المؤثرات بس، مش للنص",
                         "monospaced Arabic: effect titles only, never body"),
    "no_tatweel": ("limit", "مفيهوش تطويل (U+0640): ممنوع في «لـ<الاسم>» والإهداء والكشيدة",
                   "no tatweel U+0640: never for «لـ<name>», dedication or kashida"),
    "harakat_missing": ("limit", "التشكيل ناقص: مينفعش لنص مشكول", "harakat missing: not for vowelized text"),
    "harakat_mark_mark_collision": ("limit", "الحركات بتخبط في بعض (شدة + حركة): مش لنص مشكول",
                                    "marks collide with marks (e.g. shadda + haraka): not for vowelized body"),
    "harakat_mark_base_collision": ("limit", "الحركات بتخبط في الحروف: مش لنص مشكول",
                                    "marks collide with base letters: not for vowelized body"),
    "arabic_indic_digits_missing": ("limit", "الأرقام الهندية (٠١٢) ناقصة", "Arabic-Indic digits missing"),
    "arabic_indic_digits_look_western": ("limit", "الأرقام الهندية مرسومة بأشكال الأرقام الغربية",
                                         "Arabic-Indic digits are drawn with Western digit outlines"),
    "no_gpos_mkmk": ("fact", "مفيش mkmk في GPOS (اتقاس التراكب بالرسم)",
                     "no GPOS mkmk feature (stacking measured by rasterising)"),
    "fsType_editable_embedding": ("fact", "fsType = 8: التضمين مسموح للتعديل", "fsType 8: editable embedding"),
}


def finding(fid: str, detail: str = "") -> dict:
    severity, ar, en = FINDINGS[fid]
    return {"finding": fid, "severity": severity, "ar": ar, "en": en, "detail": detail}


@lru_cache(maxsize=1)
def load_names(path: Path = NAMES_JSON) -> tuple[dict, ...]:
    return tuple(json.loads(Path(path).read_text(encoding="utf-8"))["names"])


@lru_cache(maxsize=1)
def load_harakat_corpus(path: Path = HARAKAT_JSON) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- facts from the font tables
def coverage(font: TTFont) -> dict:
    cmap = font.getBestCmap() or {}
    missing = lambda cps: [f"U+{c:04X}" for c in cps if c not in cmap]  # noqa: E731
    return {"missing_arabic_base": missing(ARABIC_BASE), "missing_harakat": missing(HARAKAT),
            "missing_indic_digits": missing(INDIC_DIGITS), "missing_arabic_punct": missing(ARABIC_PUNCT),
            "has_tatweel": TATWEEL in cmap, "missing_latin": missing(LATIN_REQUIRED)}


def _outline(glyphset, name: str) -> tuple:
    pen = RecordingPen()
    glyphset[name].draw(pen)
    return tuple((op, tuple(args)) for op, args in pen.value), glyphset[name].width


def digit_forms(font: TTFont) -> dict:
    """Which Arabic-Indic digits share their outline with the Western digit (they would *look* Western)."""
    cmap = font.getBestCmap() or {}
    if not all(c in cmap for c in INDIC_DIGITS):
        return {"present": False, "look_western": []}
    glyphset = font.getGlyphSet()
    same = [str(i) for i in range(10) if (0x30 + i) in cmap and (
        cmap[0x30 + i] == cmap[0x660 + i] or _outline(glyphset, cmap[0x30 + i]) == _outline(glyphset, cmap[0x660 + i]))]
    # «١» and «1» are both a single vertical stroke, so sharing that one outline is normal design.
    return {"present": True, "identical_outlines": same, "look_western": [d for d in same if d != "1"]}


def gpos_features(font: TTFont) -> list[str]:
    if "GPOS" not in font or font["GPOS"].table.FeatureList is None:
        return []
    return sorted({rec.FeatureTag for rec in font["GPOS"].table.FeatureList.FeatureRecord})


def arabic_advances(path: Path, names: tuple[dict, ...]) -> dict:
    """Advance widths of the *shaped* (joined) Arabic glyphs of the names corpus; monospace ⇔ ≥95 % share one width.

    The cmap glyphs are not used: many Kufic fonts draw isolated forms on a grid
    and only the contextual forms reveal the real widths.
    """
    widths = [adv for n in names for gid, _c, _x, _y, adv in _shaped(str(path), n["ar"].replace(" ", ""))
              if gid and adv > 0]
    if not widths:
        return {"distinct": 0, "modal_share": 0.0, "monospace": False}
    values, counts = np.unique(widths, return_counts=True)
    share = float(counts.max()) / len(widths)
    return {"distinct": int(len(values)), "modal_share": round(share, 3), "monospace": share >= 0.95}


# --------------------------------------------------------------------------- shaping corpus
def _shaped(path: str, text: str) -> list[tuple[int, int, int, int, int]]:
    """(gid, cluster, x, y_offset, x_advance) in logical run order, via the fork's HarfBuzz helpers."""
    font = _hb_font(path, 0)
    out = []
    pen_x = 0
    for run, rtl in directional_runs(text):
        infos, positions = _shape_run(font, run, rtl)
        for info, pos in zip(infos, positions):
            out.append((info.codepoint, info.cluster, pen_x + pos.x_offset, pos.y_offset, pos.x_advance))
            pen_x += pos.x_advance
    return out


def shaping_corpus(path: Path, script: str, names: tuple[dict, ...]) -> dict:
    key = "ar" if script == "AR" else "en"
    with_notdef = [n[key] for n in names if shape(str(path), 0, n[key]).notdef]
    result = {"names_tested": len(names), "names_with_notdef": with_notdef[:20],
              "names_with_notdef_count": len(with_notdef)}
    if script == "AR":
        alone = [g[0] for g in _shaped(str(path), "ب")]
        joined = [g[0] for g in _shaped(str(path), "ببب")]
        result["joining_applied"] = len(set(joined)) > 1 or (bool(joined) and joined[0] != alone[0])
        dedication = [f"إهداء لـ{n['ar']}" for n in names[:40]]
        result["dedication_notdef"] = sum(shape(str(path), 0, d).notdef for d in dedication)
    return result


# --------------------------------------------------------------------------- rasterising
class _FlattenPen:
    """Collects contours as point lists (curves flattened to 8 segments) for the hb draw API."""

    def __init__(self):
        self.contours: list[list[tuple[float, float]]] = []
        self._cur: list[tuple[float, float]] = []

    def moveTo(self, p):  # noqa: N802 - pen protocol
        self._close()
        self._cur = [p]

    def lineTo(self, p):  # noqa: N802
        self._cur.append(p)

    def qCurveTo(self, *pts):  # noqa: N802
        start = self._cur[-1]
        # hb emits one quadratic segment per call: (control, end)
        control, end = pts[-2], pts[-1]
        for i in range(1, 9):
            t = i / 8
            self._cur.append(((1 - t) ** 2 * start[0] + 2 * (1 - t) * t * control[0] + t * t * end[0],
                              (1 - t) ** 2 * start[1] + 2 * (1 - t) * t * control[1] + t * t * end[1]))

    def curveTo(self, c1, c2, end):  # noqa: N802
        s = self._cur[-1]
        for i in range(1, 9):
            t = i / 8
            a, b, c, d = (1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t * t, t ** 3
            self._cur.append((a * s[0] + b * c1[0] + c * c2[0] + d * end[0],
                              a * s[1] + b * c1[1] + c * c2[1] + d * end[1]))

    def closePath(self):  # noqa: N802
        self._close()

    endPath = closePath  # noqa: N815

    def _close(self):
        if len(self._cur) > 2:
            self.contours.append(self._cur)
        self._cur = []


@dataclass
class GlyphMask:
    mask: np.ndarray  # bool, row 0 = top
    left: int         # px of column 0 relative to the glyph origin
    top: int          # px of row 0 above the baseline

    @property
    def core(self) -> np.ndarray:
        """The mask eroded by one pixel: overlaps of cores are real ink overlaps, not mere contact."""
        if not hasattr(self, "_core"):
            m = self.mask
            core = m.copy()
            core[1:, :] &= m[:-1, :]
            core[:-1, :] &= m[1:, :]
            core[:, 1:] &= m[:, :-1]
            core[:, :-1] &= m[:, 1:]
            core[0, :] = core[-1, :] = False
            core[:, 0] = core[:, -1] = False
            object.__setattr__(self, "_core", core)
        return self._core


def rasterise_contours(contours: list[list[tuple[float, float]]], scale: float) -> GlyphMask | None:
    """Non-zero winding scanline fill at pixel centres."""
    if not contours:
        return None
    edges = []
    for contour in contours:
        pts = np.asarray(contour, dtype=float) * scale
        nxt = np.roll(pts, -1, axis=0)
        edges.append(np.hstack([pts, nxt]))
    e = np.vstack(edges)
    e = e[e[:, 1] != e[:, 3]]
    if not len(e):
        return None
    xmin, xmax = int(np.floor(min(e[:, 0].min(), e[:, 2].min()))), int(np.ceil(max(e[:, 0].max(), e[:, 2].max())))
    ymin, ymax = int(np.floor(min(e[:, 1].min(), e[:, 3].min()))), int(np.ceil(max(e[:, 1].max(), e[:, 3].max())))
    width, height = max(1, xmax - xmin), max(1, ymax - ymin)
    mask = np.zeros((height, width), dtype=bool)
    x0, y0, x1, y1 = e[:, 0], e[:, 1], e[:, 2], e[:, 3]
    direction = np.where(y1 > y0, 1, -1)
    lo, hi = np.minimum(y0, y1), np.maximum(y0, y1)
    centres = np.arange(height) + ymin + 0.5
    for row, yc in enumerate(centres):
        hit = (lo <= yc) & (yc < hi)
        if not hit.any():
            continue
        xs = x0[hit] + (yc - y0[hit]) * (x1[hit] - x0[hit]) / (y1[hit] - y0[hit])
        order = np.argsort(xs)
        xs, winding = xs[order], np.cumsum(direction[hit][order])
        for i in range(len(xs) - 1):
            if winding[i] != 0:
                a = int(np.ceil(xs[i] - xmin - 0.5))
                b = int(np.floor(xs[i + 1] - xmin - 0.5))
                if b >= a:
                    mask[height - 1 - row, max(a, 0):min(b + 1, width)] = True
    return GlyphMask(mask=mask, left=xmin, top=ymax)


class LineRaster:
    """Per-glyph masks of one font, cached by glyph id."""

    def __init__(self, path: Path):
        self.path = str(path)
        self.font = _hb_font(self.path, 0)
        self.upem = self.font.face.upem
        self.scale = PX_PER_EM / self.upem
        self._cache: dict[int, GlyphMask | None] = {}
        tt = TTFont(self.path, lazy=True)
        try:
            gdef = tt["GDEF"].table if "GDEF" in tt else None
            classes = gdef.GlyphClassDef.classDefs if gdef is not None and gdef.GlyphClassDef else {}
            order = tt.getGlyphOrder()
            self.mark_gids = {order.index(name) for name, klass in classes.items() if klass == 3 and name in order}
        finally:
            tt.close()

    def glyph(self, gid: int) -> GlyphMask | None:
        if gid not in self._cache:
            pen = _FlattenPen()
            self.font.draw_glyph_with_pen(gid, pen)
            pen._close()
            self._cache[gid] = rasterise_contours(pen.contours, self.scale)
        return self._cache[gid]

    def line(self, text: str) -> list[tuple[GlyphMask, int, int, bool]]:
        """(mask, x_px, y_px, is_mark) for every inked glyph of the shaped line."""
        out = []
        for gid, cluster, x, y_off, _adv in _shaped(self.path, text):
            if gid == 0:  # .notdef boxes are counted by the coverage/shaping checks, not here
                continue
            mask = self.glyph(gid)
            if mask is None:
                continue
            char = text[cluster] if cluster < len(text) else ""
            is_mark = gid in self.mark_gids if self.mark_gids else unicodedata.category(char) == "Mn"
            out.append((mask, int(round(x * self.scale)) + mask.left, int(round(y_off * self.scale)) + mask.top,
                        is_mark))
        return out


def _line_collisions(glyphs: list[tuple[GlyphMask, int, int, bool]]) -> dict:
    """Count marks whose ink core overlaps another mark's / a base glyph's ink core.

    Cores (masks eroded by 1 px) are compared so that designed contact — e.g.
    Amiri's fatha nested in the shadda bowl — is reported as *touch* (a fact)
    and only real ink overlap counts as a collision.
    """
    left = min(x for _m, x, _y, _k in glyphs)
    right = max(x + m.mask.shape[1] for m, x, _y, _k in glyphs)
    top = max(y for _m, _x, y, _k in glyphs)
    bottom = min(y - m.mask.shape[0] for m, _x, y, _k in glyphs)
    h, w = top - bottom, right - left
    base = np.zeros((h, w), dtype=np.int16)
    marks = np.zeros((h, w), dtype=np.int16)
    base_core = np.zeros((h, w), dtype=np.int16)
    marks_core = np.zeros((h, w), dtype=np.int16)
    placed = []
    for mask, x, y, is_mark in glyphs:
        r0, c0 = top - y, x - left
        sl = (slice(r0, r0 + mask.mask.shape[0]), slice(c0, c0 + mask.mask.shape[1]))
        (marks if is_mark else base)[sl] += mask.mask
        (marks_core if is_mark else base_core)[sl] += mask.core
        placed.append((sl, mask, is_mark))
    mark_mark = mark_base = touches = 0
    worst_mm = worst_mb = 0.0
    for sl, glyph, is_mark in placed:
        if not is_mark:
            continue
        own, core = glyph.mask, glyph.core
        area = int(core.sum()) or int(own.sum()) or 1
        if ((own & ((marks[sl] - own) > 0)).any() or (own & (base[sl] > 0)).any()):
            touches += 1
        mm = int((core & ((marks_core[sl] - core) > 0)).sum())
        mb = int((core & (base_core[sl] > 0)).sum())
        if mm >= MIN_PX and mm / area >= MARK_MARK_SHARE:
            mark_mark += 1
        if mb >= MIN_PX and mb / area >= MARK_BASE_SHARE:
            mark_base += 1
        worst_mm, worst_mb = max(worst_mm, mm / area), max(worst_mb, mb / area)
    ink_rows = np.nonzero((base + marks).any(axis=1))[0]
    return {"mark_mark": mark_mark, "mark_base": mark_base, "touch": touches, "worst_mm": worst_mm,
            "worst_mb": worst_mb,
            "ink_top_px": int(top - ink_rows.min()) if len(ink_rows) else 0,
            "ink_bottom_px": int(top - ink_rows.max() - 1) if len(ink_rows) else 0,
            "marks": sum(1 for _s, _o, k in placed if k)}


def harakat_and_spacing(path: Path, lines: list[str]) -> dict:
    """Mark/mark and mark/base collisions + inter-line minimum safe spacing for these lines."""
    raster = LineRaster(path)
    metrics = font_metrics(str(path), 0)
    office_px = metrics.office_line_units * raster.scale
    per_line = []
    for text in lines:
        glyphs = raster.line(text)
        if glyphs:
            per_line.append({"text": text, **_line_collisions(glyphs)})
    if not per_line:
        return {"lines": 0}
    asc = max(item["ink_top_px"] for item in per_line)
    desc = max(-item["ink_bottom_px"] for item in per_line)
    inter_line = round(max(1.0, (asc + desc) * (1 + CLEARANCE) / office_px), 3)
    face = FontFace(path=str(path), index=0, family="", subfamily="", full_name="", weight=400, italic=False)
    single = max(min_safe_line_spacing(face, item["text"]) for item in per_line)
    return {
        "lines": len(per_line), "marks": sum(i["marks"] for i in per_line),
        "mark_mark_collisions": sum(i["mark_mark"] for i in per_line),
        "mark_base_collisions": sum(i["mark_base"] for i in per_line),
        "marks_touching": sum(i["touch"] for i in per_line),
        "worst_mark_mark_share": round(max(i["worst_mm"] for i in per_line), 3),
        "worst_mark_base_share": round(max(i["worst_mb"] for i in per_line), 3),
        "lines_with_collisions": [i["text"] for i in per_line if i["mark_mark"] or i["mark_base"]][:6],
        "ink_ascent_em": round(asc / PX_PER_EM, 3), "ink_descent_em": round(desc / PX_PER_EM, 3),
        "office_line_em": round(metrics.office_line_units / metrics.upem, 3),
        "collide_at_single_spacing": (asc + desc) > office_px,
        "min_safe_line_spacing": inter_line,
        "single_line_ink_spacing": single,
    }


# --------------------------------------------------------------------------- one font → status
def pick_test_file(fam: dict) -> dict:
    upright = [f for f in fam["files"] if not f.get("italic") and "Italic" not in f["file"]] or fam["files"]
    return min(upright, key=lambda f: (not f.get("variable"), abs(int(f.get("weight_class", 400)) - 400), f["file"]))


def qa_font(path: Path, *, script: str, roles: list[str], licence_ok: bool = True, fs_type: int | None = None,
            expected_sha256: str | None = None, names: tuple[dict, ...] | None = None,
            corpus: dict | None = None) -> dict:
    """All measurements + status for one font file."""
    names = names if names is not None else load_names()
    corpus = corpus or load_harakat_corpus()
    reasons: list[dict] = []
    facts: dict = {"file_sha256": sha256_file(path)}
    if expected_sha256 and facts["file_sha256"] != expected_sha256:
        reasons.append(finding("file_sha256_mismatch", f"{facts['file_sha256']} != {expected_sha256}"))
    try:
        font = TTFont(str(path), lazy=False)
    except Exception as exc:  # noqa: BLE001 - an unreadable file is a finding, not a crash
        return _verdict([finding("font_unreadable", str(exc))], facts, roles, script)
    try:
        cov = coverage(font)
        colour = [t.strip() for t in ("COLR", "SVG ", "CBDT", "sbix") if t in font]
        fs_type = int(font["OS/2"].fsType) if fs_type is None else fs_type
        facts.update({"coverage": cov, "digits": digit_forms(font), "gpos_features": gpos_features(font),
                      "colour_tables": colour, "embedding": embedding_permission(fs_type)})
        if script == "AR":
            facts["arabic_advances"] = arabic_advances(path, names)
    finally:
        font.close()
    if not licence_ok:
        reasons.append(finding("licence_refused"))
    if not facts["embedding"]["pdf"]:
        reasons.append(finding("embedding_refused", facts["embedding"]["reason"]))
    if fs_type & 0x0008:
        reasons.append(finding("fsType_editable_embedding"))
    if colour:
        reasons.append(finding("colour_font_quarantined", ",".join(colour)))
    facts["shaping"] = shaping_corpus(path, script, names)
    if facts["shaping"]["names_with_notdef_count"]:
        reasons.append(finding("names_notdef", ", ".join(facts["shaping"]["names_with_notdef"][:5])))
    if script == "AR":
        if cov["missing_arabic_base"]:
            reasons.append(finding("arabic_base_missing", " ".join(cov["missing_arabic_base"])))
        if not facts["shaping"].get("joining_applied"):
            reasons.append(finding("arabic_joining_not_applied"))
        if not cov["has_tatweel"]:
            reasons.append(finding("no_tatweel"))
        if facts["arabic_advances"]["monospace"]:
            reasons.append(finding("monospace_arabic", f"modal share {facts['arabic_advances']['modal_share']}"))
        if "mkmk" not in facts["gpos_features"]:
            reasons.append(finding("no_gpos_mkmk"))
        if not facts["digits"]["present"]:
            reasons.append(finding("arabic_indic_digits_missing"))
        elif facts["digits"]["look_western"]:
            reasons.append(finding("arabic_indic_digits_look_western", ",".join(facts["digits"]["look_western"])))
        if cov["missing_harakat"]:
            reasons.append(finding("harakat_missing", " ".join(cov["missing_harakat"])))
        facts["harakat"] = harakat_and_spacing(path, corpus["lines_ar"])
        if facts["harakat"].get("mark_mark_collisions"):
            reasons.append(finding("harakat_mark_mark_collision",
                                   f"{facts['harakat']['mark_mark_collisions']} mark pair(s)"))
        if facts["harakat"].get("mark_base_collisions"):
            reasons.append(finding("harakat_mark_base_collision",
                                   f"{facts['harakat']['mark_base_collisions']} mark(s)"))
    else:
        if cov["missing_latin"]:
            reasons.append(finding("latin_basic_missing", " ".join(cov["missing_latin"][:12])))
        facts["spacing_latin"] = harakat_and_spacing(path, corpus["lines_latin"])
    return _verdict(reasons, facts, roles, script)


def _verdict(reasons: list[dict], facts: dict, roles: list[str], script: str) -> dict:
    ids = {r["finding"] for r in reasons}
    severities = {r["severity"] for r in reasons}
    status = "rejected" if "blocking" in severities else "screen_only" if "quarantine" in severities else \
        "certified_print"
    allowed = list(roles)
    if "monospace_arabic" in ids:
        allowed = [r for r in allowed if r in ("title", "effect")]
    if "no_tatweel" in ids:
        allowed = [r for r in allowed if r not in ("handwriting", "dedication")]
    vowel_limits = {"harakat_missing", "harakat_mark_mark_collision", "harakat_mark_base_collision",
                    "monospace_arabic"}
    vowelized_text = (status == "certified_print" and not (ids & vowel_limits)) if script == "AR" else None
    capabilities = {
        "vowelized_text": vowelized_text,
        "vowelized_body": (bool(vowelized_text) and "body" in allowed) if script == "AR" else None,
        "lam_tatweel_dedication": ("no_tatweel" not in ids and status == "certified_print") if script == "AR"
        else None,
        "arabic_indic_digits": not ({"arabic_indic_digits_missing", "arabic_indic_digits_look_western"} & ids)
        if script == "AR" else None,
    }
    return {
        "status": status,
        "reasons": reasons,
        "allowed_roles": allowed if status != "rejected" else [],
        "capabilities": capabilities,
        "min_safe_line_spacing": (facts.get("harakat") or facts.get("spacing_latin") or {}).get(
            "min_safe_line_spacing"),
        "on_device_export_proof": {"status": "pending", "step": ON_DEVICE_STEP},
        "facts": facts,
    }


def qa_family(fam: dict, checkout: Path, ledger_entry: dict | None = None, **kwargs) -> dict:
    test_file = pick_test_file(fam)
    path = Path(checkout) / fam["repo_dir"] / test_file["file"]
    licence_ok = (ledger_entry or {}).get("decision", "bundle_embed") != "refuse"
    result = qa_font(path, script=fam["script"], roles=fam["roles"], licence_ok=licence_ok,
                     expected_sha256=test_file["sha256"], **kwargs)
    return {"id": fam["id"], "family": fam["family"], "script": fam["script"], "tested_file": test_file["file"],
            "tested_variable_default": bool(test_file.get("variable")), **result}


def run_qa(catalog, checkout: Path, ledger: dict | None = None) -> dict:
    entries = {e["family"]: e for e in (ledger or {}).get("families", [])}
    families = [qa_family(fam, checkout, entries.get(fam["family"])) for fam in catalog.families]
    counts = {s: sum(f["status"] == s for f in families) for s in STATUSES}
    return {
        "schema": SCHEMA, "commit": catalog.commit,
        "method": {"px_per_em": PX_PER_EM, "clearance": CLEARANCE, "mark_mark_share": MARK_MARK_SHARE,
                   "mark_base_share": MARK_BASE_SHARE, "min_px": MIN_PX, "names": len(load_names()),
                   "harakat_lines": len(load_harakat_corpus()["lines_ar"])},
        "counts": counts | {
            "vowelized_text_ok": sum(bool(f["capabilities"]["vowelized_text"]) for f in families),
            "vowelized_body_ok": sum(bool(f["capabilities"]["vowelized_body"]) for f in families),
            "on_device_export_proof_pending": len(families)},
        "on_device_export_proof": {"status": "pending", "step": ON_DEVICE_STEP},
        "families": families,
    }


def certified_families(qa: dict, *, status: str = "certified_print") -> set[str]:
    return {f["family"] for f in qa.get("families", []) if f["status"] == status}


def main(argv: list[str] | None = None) -> int:
    import argparse

    from mxstudio.fonts.build_catalog import write_json
    from mxstudio.fonts.catalog import default_catalog
    from mxstudio.fonts.ledger import load_ledger
    from mxstudio.fonts.paths import QA_JSON

    parser = argparse.ArgumentParser(description="Run font QA over the catalog from a google/fonts checkout")
    parser.add_argument("--checkout", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=QA_JSON)
    args = parser.parse_args(argv)
    qa = run_qa(default_catalog(), args.checkout, load_ledger())
    write_json(qa, args.out)
    print(json.dumps(qa["counts"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
