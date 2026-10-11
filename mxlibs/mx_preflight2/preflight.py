"""Print preflight of a magazine PDF against a printer profile. Pure: reads, never writes.

Rules enforced (each is a *named* check with an Egyptian-Arabic and an English message):

readable        the file opens as a PDF
encryption      no encryption / password (a print shop cannot open a protected file)
file_size       not larger than the profile's max_bytes
page_count      equals the expected page count (when given)
page_size       every MediaBox = trim (+ 2 x bleed when bleed > 0) +/- tolerance
bleed           ink touching the trim edge continues through the bleed band (rasterised with pypdfium2)
safe_zone       no text run and no declared important box outside the safe area (trim inset by safe_mm)
fonts_embedded  every font carries FontFile/FontFile2/FontFile3 (Type3 counts as embedded)
image_only      the document carries at least one font object (an image-only PDF is refused)
image_dpi       effective resolution of every placed image at printed size >= min_dpi
colour_space    colour families used vs the printer profile (rgb / cmyk / any) and its OutputIntent

The result is facts plus named failures. Visual acceptance stays with the
operator; this module never writes print state.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pikepdf

from . import _icc, _pdfwalk, _raster

TRIM_SIZES_MM = {"A4": (210.0, 297.0), "A5": (148.0, 210.0)}
MIB = 1024 * 1024

DEFAULT_PROFILE = {
    "size": "A5",
    "trim_mm": None,
    "tolerance_mm": 1.0,
    "bleed_mm": 3.0,
    "safe_mm": 5.0,
    "expected_pages": None,
    "min_dpi": 150,
    "warn_dpi": 300,
    "min_image_mm": 3.0,
    "colour": "rgb",
    "icc_path": None,
    "important_boxes": [],
    "check_text_in_safe": True,
    "safe_tolerance_mm": 0.3,
    "raster_dpi": 150,
    "bleed_gap_tolerance": 0.05,
    "max_bytes": 500 * MIB,
    "password": None,
}

MSG = {
    "readable": {
        "ok": ("الملف بيتفتح عادي", "The file opens as a PDF."),
        "fail": ("الملف ده مش PDF سليم ومش بيتفتح", "The file is not a readable PDF."),
    },
    "encryption": {
        "ok": ("الملف مش متشفّر", "The file is not encrypted."),
        "fail": (
            "الملف متشفّر أو عليه باسورد — المطبعة مش هتعرف تتعامل معاه. صدّره تاني من غير حماية",
            "The file is encrypted or password-protected — export it again without protection.",
        ),
    },
    "file_size": {
        "ok": ("حجم الملف مناسب ({mb} ميجا)", "The file size is acceptable ({mb} MB)."),
        "fail": (
            "الملف تقيل أوي ({mb} ميجا) والحد {max_mb} ميجا",
            "The file is too large ({mb} MB; limit {max_mb} MB).",
        ),
    },
    "page_count": {
        "ok": ("عدد الصفحات مظبوط ({pages})", "The page count is right ({pages})."),
        "fail": ("عدد الصفحات {pages} والمفروض {expected}", "The file has {pages} pages; {expected} are expected."),
        "skip": ("عدد الصفحات ما اتراجعش (مفيش رقم متوقع)", "Page count not checked (no expected count)."),
    },
    "page_size": {
        "ok": ("مقاس الصفحات مظبوط ({w}×{h} مم)", "Page size is right ({w}×{h} mm)."),
        "fail": (
            "مقاس صفحة {page} هو {w}×{h} مم والمفروض {ew}×{eh} مم (±{tol})",
            "Page {page} is {w}×{h} mm; {ew}×{eh} mm (±{tol}) is expected.",
        ),
    },
    "bleed": {
        "ok": ("الرسمة واصلة لحد آخر النزيف ({bleed} مم)", "Art extends into the {bleed} mm bleed."),
        "fail": (
            "الرسمة واقفة عند حد القص في صفحة {page} (ناحية {side_ar}) ومش داخلة في النزيف {bleed} مم"
            " — هيبان خط أبيض بعد القص",
            "On page {page} the art stops at the trim ({side}) and does not extend into the {bleed} mm bleed"
            " — a white sliver will show after trimming.",
        ),
        "no_area": ("صفحة {page} مفيهاش مساحة نزيف {bleed} مم خالص", "Page {page} has no {bleed} mm bleed area."),
        "skip": ("النزيف مش مطلوب في البروفايل ده", "Bleed is not required by this profile."),
    },
    "safe_zone": {
        "ok": ("مفيش كلام ولا حاجة مهمة قريبة من حافة القص", "Nothing important sits outside the safe area."),
        "fail": (
            "فيه {what} قريب أوي من الحافة في صفحة {page} («{text}») — ممكن يتقص. دخّله جوه الهامش الآمن {safe} مم",
            "Page {page}: {what_en} “{text}” is outside the {safe} mm safe area — it may be trimmed.",
        ),
    },
    "fonts_embedded": {
        "ok": ("كل الخطوط مدمجة في الملف ({count})", "All fonts are embedded ({count})."),
        "fail": (
            "الخط «{name}» مش مدمج في الملف — المطبعة هتحط خط تاني مكانه",
            "The font “{name}” is not embedded — the printer would substitute it.",
        ),
    },
    "image_only": {
        "ok": ("الملف فيه نص حقيقي مش صور بس", "The file carries real text, not only pictures."),
        "fail": (
            "الملف ده صور بس ومفيهوش ولا خط — ده مش ملف المجلة المصدّر من العرض",
            "The file is image-only (no font objects) — it is not the exported magazine deck.",
        ),
    },
    "image_dpi": {
        "ok": (
            "كل الصور دقتها كويسة للطباعة (أقل دقة {dpi})",
            "Every image prints at enough resolution (lowest {dpi} dpi).",
        ),
        "fail": (
            "صورة في صفحة {page} دقتها {dpi} نقطة/بوصة بس والمطلوب {min_dpi} على الأقل — هتطلع مشوشة",
            "An image on page {page} prints at only {dpi} dpi; at least {min_dpi} is required.",
        ),
        "warn": (
            "صورة في صفحة {page} دقتها {dpi} — أقل من المثالي {warn_dpi}",
            "An image on page {page} is {dpi} dpi — below the ideal {warn_dpi}.",
        ),
        "none": ("مفيش صور في الملف", "The file has no images."),
    },
    "colour_space": {
        "ok": ("ألوان الملف مناسبة للمطبعة ({colour})", "Colours match the printer profile ({colour})."),
        "cmyk_in_rgb": (
            "الملف فيه ألوان CMYK والمطبعة مستنية ملف RGB",
            "The file uses CMYK colour but the printer profile expects RGB.",
        ),
        "rgb_in_cmyk": (
            "الملف فيه ألوان RGB والمطبعة مستنية CMYK",
            "The file uses RGB colour but the printer profile expects CMYK.",
        ),
        "no_intent": (
            "الملف مفيهوش بروفايل ألوان المطبعة (OutputIntent)",
            "The file has no OutputIntent for the printer.",
        ),
        "intent_mismatch": (
            "بروفايل الألوان في الملف «{found}» مش هو بروفايل المطبعة «{expected}»",
            "The file's colour profile “{found}” is not the printer's “{expected}”.",
        ),
    },
}

SIDE_AR = {"left": "الشمال", "right": "اليمين", "top": "فوق", "bottom": "تحت"}
WARN_MSG = {
    "transparency": (
        "صفحة {page} فيها شفافية ({what}) — راجعها في البروفة",
        "Page {page} uses transparency ({what}) — check it on the proof.",
    ),
    "spot_colour": (
        "الملف فيه ألوان خاصة (Spot) — اتأكد إن المطبعة عاوزاها",
        "The file uses spot colours — confirm the printer expects them.",
    ),
    "trim_box": (
        "صفحة {page} مفيهاش TrimBox — افترضنا إن حد القص في منتصف الصفحة",
        "Page {page} has no TrimBox — the trim was assumed centred.",
    ),
}


def make_profile(size: str | None = None, **overrides) -> dict:
    """A complete profile from the defaults, a named trim size and overrides."""
    profile = dict(DEFAULT_PROFILE)
    if size:
        profile["size"] = size
    profile.update({k: v for k, v in overrides.items()})
    if profile.get("trim_mm") is None:
        key = str(profile.get("size") or "").upper()
        if key not in TRIM_SIZES_MM:
            raise ValueError(f"unknown page size {profile.get('size')!r}; give trim_mm")
        profile["trim_mm"] = TRIM_SIZES_MM[key]
    profile["trim_mm"] = tuple(float(v) for v in profile["trim_mm"])
    if profile.get("colour") not in ("rgb", "cmyk", "any", None):
        raise ValueError("profile colour must be 'rgb', 'cmyk' or 'any'")
    return profile


def _check(check_id: str, ok: bool, key: str, detail: dict | None = None, **values) -> dict:
    ar, en = MSG[check_id][key]
    return {
        "id": check_id,
        "ok": bool(ok),
        "ar": ar.format(**values),
        "en": en.format(**values),
        "detail": detail or {},
        "skipped": key == "skip",
    }


def _warning(warn_id: str, detail: dict | None = None, **values) -> dict:
    ar, en = WARN_MSG[warn_id]
    return {"id": warn_id, "ar": ar.format(**values), "en": en.format(**values), "detail": detail or {}}


def _r(value: float, nd: int = 1) -> float:
    return round(float(value), nd)


def _outside(box: tuple, area: tuple, tolerance: float) -> bool:
    """True when ``box`` (x0, y0, x1, y1) reaches outside ``area`` by more than ``tolerance``."""
    return (
        box[0] < area[0] - tolerance
        or box[1] < area[1] - tolerance
        or box[2] > area[2] + tolerance
        or box[3] > area[3] + tolerance
    )


def _trim_rect(page, media: tuple, trim_mm: tuple, tol: float) -> tuple[tuple, bool]:
    """Trim rectangle in mm (x0, y0, x1, y1): the TrimBox when it has the trim size, else centred."""
    trim_box = _pdfwalk.box_mm(page, "/TrimBox")
    if trim_box is not None:
        w, h = trim_box[2] - trim_box[0], trim_box[3] - trim_box[1]
        if abs(w - trim_mm[0]) <= tol and abs(h - trim_mm[1]) <= tol:
            return trim_box, True
    mx0, my0, mx1, my1 = media
    dx = (mx1 - mx0 - trim_mm[0]) / 2
    dy = (my1 - my0 - trim_mm[1]) / 2
    return (mx0 + dx, my0 + dy, mx1 - dx, my1 - dy), False


def run(pdf_path, profile: dict | None = None, **overrides) -> dict:
    """Preflight ``pdf_path`` against ``profile`` (see ``make_profile``). Never writes anything."""
    profile = make_profile(**{**(profile or {}), **overrides})
    path = Path(pdf_path)
    checks: list[dict] = []
    warnings: list[dict] = []
    facts: dict = {"path": str(path), "profile": {k: v for k, v in profile.items() if k != "password"}}
    try:
        digest, size = hashlib.sha256(), 0
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
                size += len(chunk)
    except OSError as exc:
        checks.append(_check("readable", False, "fail", {"error": str(exc)}))
        return _result(checks, warnings, facts)
    facts["sha256"] = digest.hexdigest()
    facts["bytes"] = size

    try:
        pdf = pikepdf.open(path, password=profile.get("password") or "")
    except pikepdf.PasswordError as exc:
        checks.append(_check("readable", True, "ok"))
        checks.append(_check("encryption", False, "fail", {"error": str(exc), "needs_password": True}))
        return _result(checks, warnings, facts)
    except (pikepdf.PdfError, OSError, ValueError) as exc:
        checks.append(_check("readable", False, "fail", {"error": str(exc)}))
        return _result(checks, warnings, facts)

    with pdf:
        checks.append(_check("readable", True, "ok", {"pdf_version": pdf.pdf_version}))
        encryption = {"encrypted": bool(pdf.is_encrypted)}
        if pdf.is_encrypted:
            try:
                encryption["method"] = str(pdf.encryption.stream)
                encryption["permissions"] = (
                    {k: v for k, v in pdf.allow._asdict().items()} if hasattr(pdf.allow, "_asdict") else str(pdf.allow)
                )
            except Exception:  # noqa: BLE001
                pass
        checks.append(_check("encryption", not pdf.is_encrypted, "fail" if pdf.is_encrypted else "ok", encryption))

        mb = facts["bytes"] / MIB
        max_bytes = int(profile.get("max_bytes") or DEFAULT_PROFILE["max_bytes"])
        checks.append(
            _check(
                "file_size",
                facts["bytes"] <= max_bytes,
                "ok" if facts["bytes"] <= max_bytes else "fail",
                {"bytes": facts["bytes"], "max_bytes": max_bytes},
                mb=_r(mb),
                max_mb=_r(max_bytes / MIB),
            )
        )

        pages = len(pdf.pages)
        facts["pages"] = pages
        expected = profile.get("expected_pages")
        if expected is None:
            checks.append(_check("page_count", True, "skip", {"pages": pages}))
        else:
            ok = pages == int(expected)
            checks.append(
                _check(
                    "page_count",
                    ok,
                    "ok" if ok else "fail",
                    {"pages": pages, "expected": int(expected)},
                    pages=pages,
                    expected=int(expected),
                )
            )

        _page_geometry_checks(pdf, path, profile, checks, warnings, facts)
        _font_checks(pdf, checks, facts)
        _image_and_colour_checks(pdf, profile, checks, warnings, facts)
    return _result(checks, warnings, facts)


def _page_geometry_checks(pdf, path: Path, profile: dict, checks: list, warnings: list, facts: dict) -> None:
    trim_mm = profile["trim_mm"]
    bleed = float(profile.get("bleed_mm") or 0.0)
    tol = float(profile.get("tolerance_mm") or 1.0)
    expected_w, expected_h = (
        trim_mm[0] + 2 * bleed if bleed > 0 else trim_mm[0],
        trim_mm[1] + 2 * bleed if bleed > 0 else trim_mm[1],
    )
    sizes, bad, trims = [], [], []
    missing_trimbox = []
    for index, page in enumerate(pdf.pages):
        media = _pdfwalk.box_mm(page, "/MediaBox")
        w, h = media[2] - media[0], media[3] - media[1]
        if int(page.obj.get("/Rotate", 0) or 0) % 180 == 90:
            w, h = h, w
        sizes.append([_r(w), _r(h)])
        if abs(w - expected_w) > tol or abs(h - expected_h) > tol:
            bad.append({"page": index + 1, "w": _r(w), "h": _r(h)})
        trim, has_box = _trim_rect(page, media, trim_mm, tol)
        trims.append((media, trim))
        if not has_box and bleed > 0:
            missing_trimbox.append(index + 1)
    facts["page_size_mm"] = sizes[0] if sizes else None
    facts["page_sizes_mm"] = sizes
    detail = {"expected_mm": [_r(expected_w), _r(expected_h)], "tolerance_mm": tol, "bad_pages": bad}
    if bad:
        first = bad[0]
        checks.append(
            _check(
                "page_size",
                False,
                "fail",
                detail,
                page=first["page"],
                w=first["w"],
                h=first["h"],
                ew=_r(expected_w),
                eh=_r(expected_h),
                tol=tol,
            )
        )
    else:
        checks.append(_check("page_size", True, "ok", detail, w=_r(expected_w), h=_r(expected_h)))
    if missing_trimbox:
        warnings.append(_warning("trim_box", {"pages": missing_trimbox}, page=missing_trimbox[0]))

    # --- bleed + safe zone need pdfium --------------------------------------------------------
    safe = float(profile.get("safe_mm") or 0.0)
    want_text = bool(profile.get("check_text_in_safe", True))
    boxes = list(profile.get("important_boxes") or [])
    if bleed <= 0 and not want_text and not boxes:
        checks.append(_check("bleed", True, "skip", {}))
        checks.append(_check("safe_zone", True, "ok", {"checked": False}))
        return
    doc = _raster.open_document(str(path), profile.get("password") or None)
    try:
        if bleed <= 0:
            checks.append(_check("bleed", True, "skip", {}))
        else:
            dpi = float(profile.get("raster_dpi") or 150)
            per_page, failure = [], None
            for index, (media, trim) in enumerate(trims):
                image = _raster.render_media(doc, index, dpi)
                sides = _raster.bleed_edges(image, media, trim, dpi, float(profile.get("bleed_gap_tolerance") or 0.05))
                per_page.append({"page": index + 1, "sides": sides})
                if failure is None:
                    for side, info in sides.items():
                        if not info["ok"]:
                            failure = (index + 1, side, info)
                            break
            detail = {"bleed_mm": bleed, "raster_dpi": dpi, "pages": per_page}
            if failure is None:
                checks.append(_check("bleed", True, "ok", detail, bleed=bleed))
            else:
                page_no, side, info = failure
                key = "no_area" if info.get("no_bleed_area") else "fail"
                ar, en = MSG["bleed"][key]
                values = {"page": page_no, "side": side, "side_ar": SIDE_AR[side], "bleed": bleed}
                checks.append(
                    {
                        "id": "bleed",
                        "ok": False,
                        "ar": ar.format(**values),
                        "en": en.format(**values),
                        "detail": {**detail, "first_failure": {"page": page_no, "side": side, **info}},
                        "skipped": False,
                    }
                )

        violations = []
        stol = float(profile.get("safe_tolerance_mm") or 0.3)
        for index, (media, trim) in enumerate(trims):
            mx0, my0 = media[0], media[1]
            trim_local = (trim[0] - mx0, trim[1] - my0, trim[2] - mx0, trim[3] - my0)
            safe_local = (trim_local[0] + safe, trim_local[1] + safe, trim_local[2] - safe, trim_local[3] - safe)
            media_h = media[3] - media[1]
            candidates = []
            if want_text:
                for x0, y0, x1, y1, text in _raster.text_rects(doc, index):
                    candidates.append(("text", text[:60], tuple(v * _raster.MM_PER_PT for v in (x0, y0, x1, y1))))
            for item in boxes:
                if item.get("page") not in (None, index + 1):
                    continue
                x, y, w, h = (float(v) for v in item["box_mm"])  # canvas mm, top-left origin
                candidates.append(("box", str(item.get("label", "box")), (x, media_h - y - h, x + w, media_h - y)))
            for kind, label, box in candidates:
                if _outside(box, safe_local, stol):
                    violations.append(
                        {
                            "page": index + 1,
                            "kind": kind,
                            "text": label,
                            "zone": "bleed" if _outside(box, trim_local, stol) else "safe_band",
                            "box_mm": [_r(v, 2) for v in box],
                        }
                    )
        detail = {"safe_mm": safe, "violations": violations, "text_checked": want_text, "boxes_checked": len(boxes)}
        if violations:
            first = violations[0]
            what_ar = "كلام" if first["kind"] == "text" else "حاجة مهمة"
            what_en = "text" if first["kind"] == "text" else "an important box"
            checks.append(
                _check(
                    "safe_zone",
                    False,
                    "fail",
                    detail,
                    what=what_ar,
                    what_en=what_en,
                    page=first["page"],
                    text=first["text"],
                    safe=safe,
                )
            )
        else:
            checks.append(_check("safe_zone", True, "ok", detail))
    finally:
        doc.close()


def _font_checks(pdf, checks: list, facts: dict) -> None:
    fonts = _pdfwalk.fonts_of(pdf)
    facts["fonts"] = fonts
    missing = [f for f in fonts if not f["embedded"]]
    if missing:
        checks.append(
            _check("fonts_embedded", False, "fail", {"fonts": fonts, "not_embedded": missing}, name=missing[0]["name"])
        )
    else:
        checks.append(_check("fonts_embedded", True, "ok", {"fonts": fonts}, count=len(fonts)))
    has_text = bool(fonts)
    facts["has_text"] = has_text
    checks.append(_check("image_only", has_text, "ok" if has_text else "fail", {"font_objects": len(fonts)}))


def _image_and_colour_checks(pdf, profile: dict, checks: list, warnings: list, facts: dict) -> None:
    from collections import Counter

    placements, families, labels = [], Counter(), Counter()
    transparency = []
    for index in range(len(pdf.pages)):
        page_facts = _pdfwalk.walk_page(pdf, index)
        placements.extend(page_facts.images)
        families.update(page_facts.colour_ops)
        labels.update(page_facts.colour_labels)
        for image in page_facts.images:
            families[image.colour_family] += 1
        if page_facts.transparency:
            transparency.append({"page": index + 1, "what": page_facts.transparency})
    min_side_pt = float(profile.get("min_image_mm") or 0) / 25.4 * 72
    measured = [p for p in placements if max(p.placed_w_pt, p.placed_h_pt) >= min_side_pt]
    images = [p.as_dict() for p in measured]
    facts["images"] = images
    min_dpi, warn_dpi = float(profile.get("min_dpi") or 150), float(profile.get("warn_dpi") or 300)
    if not measured:
        checks.append(_check("image_dpi", True, "none", {"images": []}))
    else:
        worst = min(measured, key=lambda p: p.dpi)
        low = [p.as_dict() for p in measured if p.dpi < min_dpi]
        detail = {"images": images, "min_dpi": min_dpi, "warn_dpi": warn_dpi, "below_min": low}
        if low:
            checks.append(
                _check(
                    "image_dpi",
                    False,
                    "fail",
                    detail,
                    page=low[0]["page"],
                    dpi=int(low[0]["dpi"]),
                    min_dpi=int(min_dpi),
                )
            )
        else:
            checks.append(_check("image_dpi", True, "ok", detail, dpi=int(worst.dpi)))
            soft = [p for p in measured if p.dpi < warn_dpi]
            if soft:
                ar, en = MSG["image_dpi"]["warn"]
                values = {"page": soft[0].page, "dpi": int(soft[0].dpi), "warn_dpi": int(warn_dpi)}
                warnings.append(
                    {
                        "id": "image_dpi",
                        "ar": ar.format(**values),
                        "en": en.format(**values),
                        "detail": {"images": [p.as_dict() for p in soft]},
                    }
                )

    intents = _pdfwalk.output_intents(pdf)
    colour_facts = {
        "families": dict(families),
        "labels": dict(labels),
        "output_intents": intents,
        "transparency": transparency,
    }
    facts["colour"] = colour_facts
    for item in transparency:
        warnings.append(_warning("transparency", item, page=item["page"], what=", ".join(item["what"])))
    if families.get("spot"):
        warnings.append(_warning("spot_colour", {"labels": [k for k in labels if "Separation" in k or "DeviceN" in k]}))

    wanted = profile.get("colour") or "any"
    detail = {**colour_facts, "printer_colour": wanted}
    if wanted == "rgb" and families.get("cmyk"):
        checks.append(_check("colour_space", False, "cmyk_in_rgb", detail))
        return
    if wanted == "cmyk":
        if families.get("rgb"):
            checks.append(_check("colour_space", False, "rgb_in_cmyk", detail))
            return
        if not intents:
            checks.append(_check("colour_space", False, "no_intent", detail))
            return
        icc_path = profile.get("icc_path")
        if icc_path:
            expected = _icc.facts(Path(icc_path).read_bytes())
            detail["printer_icc"] = expected
            if not any(i.get("profile_sha256") == expected["sha256"] for i in intents):
                found = intents[0].get("profile_description") or intents[0].get("identifier") or "?"
                checks.append(
                    _check(
                        "colour_space",
                        False,
                        "intent_mismatch",
                        detail,
                        found=found,
                        expected=expected["description"] or os.path.basename(str(icc_path)),
                    )
                )
                return
    checks.append(_check("colour_space", True, "ok", detail, colour=wanted.upper() if wanted != "any" else "any"))


def _result(checks: list, warnings: list, facts: dict) -> dict:
    failed = [c["id"] for c in checks if not c["ok"]]
    return {
        "ok": not failed,
        "failed": failed,
        "checks": checks,
        "warnings": warnings,
        "sha256": facts.get("sha256"),
        "bytes": facts.get("bytes"),
        "pages": facts.get("pages"),
        "page_size_mm": facts.get("page_size_mm"),
        "facts": facts,
    }
