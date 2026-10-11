"""CMYK print derivative of an approved RGB magazine PDF (pikepdf + LittleCMS via Pillow ImageCms + pypdfium2).

Rules enforced:

* The approved RGB PDF stays the record; it is opened read-only and never
  overwritten. The CMYK file is a *derived artefact*, linked to the record by
  the source sha256 (in the returned record and in the derivative's DocInfo).
* Vector colour: DeviceRGB operators ``rg``/``RG`` become ``k``/``K``; ``cs``/``CS``
  selecting an RGB space become DeviceCMYK and the following ``sc``/``scn`` values
  are converted. Colours go through LittleCMS (sRGB -> the press ICC profile),
  then the total area coverage is capped at ``tac_limit`` % by reducing C, M, Y.
* Images: 8-bit RGB (DeviceRGB, CalRGB, ICCBased N=3) and Indexed-RGB palettes
  are converted with the same transform and re-encoded losslessly (Flate);
  soft masks are kept.
* Pages that cannot be converted exactly (shadings, patterns, transparency
  groups, soft-mask/blend-mode graphics states, RGB inline images, unsupported
  colour spaces or images) are rasterised from the ORIGINAL page with
  pypdfium2 at ``raster_dpi`` (600 by default), converted, and flagged in the
  record. Fonts on those pages become pixels; the record says so.
* An OutputIntent carrying the ICC profile is added. The file is NOT claimed
  to be PDF/X: no GTS_PDFXVersion is written and the record says
  ``pdfx_certified: false``.
"""

from __future__ import annotations

import zlib
from pathlib import Path

import numpy as np
import pikepdf

from ._pdfutil import icc_facts, media_rect, same_file, sha256_file

_RGB_NAMES = {"/DeviceRGB", "/RGB", "/CalRGB"}
MAX_DEPTH = 12

NOTE_AR = "ده ملف CMYK مشتق للمطبعة — الملف المعتمد هو الـRGB الأصلي ومربوط بيه بالـsha256. مش PDF/X معتمد."
NOTE_EN = (
    "CMYK print derivative — the approved RGB file stays the record and is linked by sha256. "
    "Not a certified PDF/X file."
)


class ColourConverter:
    """sRGB (or a given RGB profile) -> press CMYK through LittleCMS, with a TAC cap."""

    def __init__(
        self,
        icc_profile,
        tac_limit: float = 300.0,
        source_profile=None,
        intent: str = "relative",
        black_point_compensation: bool = True,
    ):
        from PIL import ImageCms

        data = Path(icc_profile).read_bytes()
        self.icc_bytes = data
        self.icc = icc_facts(data)
        if self.icc["colour_space"] != "CMYK":
            raise ValueError(f"the output profile must be CMYK, got {self.icc['colour_space']!r}")
        src = ImageCms.getOpenProfile(str(source_profile)) if source_profile else ImageCms.createProfile("sRGB")
        dst = ImageCms.getOpenProfile(str(icc_profile))
        # LittleCMS intent numbers (0-3) and the BPC flag (0x2000): same values in every Pillow release.
        intents = {"perceptual": 0, "relative": 1, "saturation": 2, "absolute": 3}
        if intent not in intents:
            raise ValueError(f"unknown rendering intent {intent!r}; known: {sorted(intents)}")
        flags = 0x2000 if black_point_compensation else 0
        self.intent = intent
        self._cms = ImageCms
        self._transform = ImageCms.buildTransform(src, dst, "RGB", "CMYK", renderingIntent=intents[intent], flags=flags)
        self.tac_limit = float(tac_limit)
        self.max_tac_seen = 0.0
        self.tac_capped = 0
        self._cache: dict[tuple, tuple] = {}

    def _cap(self, cmyk: np.ndarray) -> np.ndarray:
        """Cap total coverage (in % of 255-scaled channels) by reducing C, M, Y; K is preserved."""
        values = cmyk.astype(np.float64)
        total = values.sum(axis=-1) / 255.0 * 100.0
        self.max_tac_seen = max(self.max_tac_seen, float(total.max()) if total.size else 0.0)
        over = total > self.tac_limit + 1e-6
        if np.any(over):
            self.tac_capped += int(over.sum())
            k = values[..., 3] / 255.0 * 100.0
            cmy = values[..., :3].sum(axis=-1) / 255.0 * 100.0
            factor = np.where(over & (cmy > 0), np.clip((self.tac_limit - k) / np.maximum(cmy, 1e-9), 0, 1), 1.0)
            values[..., :3] *= factor[..., None]
        return np.clip(np.floor(values + 1e-9), 0, 255).astype(np.uint8)

    def pixels(self, rgb: np.ndarray) -> np.ndarray:
        """HxWx3 uint8 RGB -> HxWx4 uint8 CMYK (TAC-capped)."""
        from PIL import Image

        image = Image.fromarray(np.ascontiguousarray(rgb, dtype=np.uint8), "RGB")
        out = self._cms.applyTransform(image, self._transform)
        return self._cap(np.asarray(out))

    def colour(self, r: float, g: float, b: float) -> tuple[float, float, float, float]:
        key = tuple(int(round(min(1.0, max(0.0, float(v))) * 255)) for v in (r, g, b))
        hit = self._cache.get(key)
        if hit is None:
            cmyk = self.pixels(np.array([[key]], dtype=np.uint8))[0, 0]
            hit = tuple(round(int(v) / 255.0, 4) for v in cmyk)
            self._cache[key] = hit
        return hit


def _get(dictionary, key, default=None):
    try:
        if dictionary is not None and key in dictionary:
            return dictionary[key]
    except (TypeError, ValueError, pikepdf.PdfError):
        return default
    return default


def _is_rgb_space(cs, resources=None, depth: int = 0) -> bool:
    if cs is None or depth > 6:
        return False
    if isinstance(cs, pikepdf.Name):
        if str(cs) in _RGB_NAMES:
            return True
        named = _get(_get(resources, "/ColorSpace"), str(cs))
        return named is not None and _is_rgb_space(named, resources, depth + 1)
    if isinstance(cs, pikepdf.Array) and len(cs):
        head = str(cs[0])
        if head == "/ICCBased":
            return int(_get(cs[1], "/N", 0)) == 3
        return head in _RGB_NAMES
    return False


def _space_kind(cs, resources=None, depth: int = 0) -> str:
    """'rgb', 'safe' (gray/CMYK/Lab-free device spaces), 'indexed_rgb', or 'unsupported'."""
    if cs is None:
        return "safe"
    if _is_rgb_space(cs, resources, depth):
        return "rgb"
    if isinstance(cs, pikepdf.Name):
        name = str(cs)
        if name in ("/DeviceGray", "/G", "/DeviceCMYK", "/CMYK", "/CalGray"):
            return "safe"
        named = _get(_get(resources, "/ColorSpace"), name)
        return _space_kind(named, resources, depth + 1) if named is not None and depth < 6 else "unsupported"
    if isinstance(cs, pikepdf.Array) and len(cs):
        head = str(cs[0])
        if head == "/ICCBased":
            return "safe" if int(_get(cs[1], "/N", 0)) in (1, 4) else "unsupported"
        if head in ("/Indexed", "/I"):
            base = _space_kind(cs[1], resources, depth + 1)
            return "indexed_rgb" if base == "rgb" else ("safe" if base == "safe" else "unsupported")
        if head in ("/Separation", "/DeviceN"):
            alt = cs[2]
            return "safe" if _space_kind(alt, resources, depth + 1) == "safe" else "unsupported"
        if head == "/CalGray":
            return "safe"
    return "unsupported"


def _is_pattern(cs, resources) -> bool:
    if str(cs) == "/Pattern":
        return True
    named = _get(_get(resources, "/ColorSpace"), str(cs)) if isinstance(cs, pikepdf.Name) else cs
    return isinstance(named, pikepdf.Array) and len(named) > 0 and str(named[0]) == "/Pattern"


def _gs_reasons(gs) -> list[str]:
    reasons = []
    smask = _get(gs, "/SMask")
    if smask is not None and str(smask) != "/None":
        reasons.append("graphics-state soft mask")
    bm = _get(gs, "/BM")
    if bm is not None:
        names = [str(v) for v in bm] if isinstance(bm, pikepdf.Array) else [str(bm)]
        if not any(n in ("/Normal", "/Compatible") for n in names):
            reasons.append(f"blend mode {names[0].lstrip('/')}")
    return reasons


class _Analysis:
    def __init__(self):
        self.reasons: list[str] = []
        self.streams: list = []  # (form / glyph stream, resources) to rewrite besides the page contents
        self.images: dict = {}  # objgen -> (image stream, resources)
        self.type3_fonts: set = set()
        self.approximations: list[str] = []

    def reason(self, text: str) -> None:
        if text not in self.reasons:
            self.reasons.append(text)


def _analyse(instructions, resources, analysis: _Analysis, depth: int, seen: set) -> None:
    for item in instructions:
        op = str(item.operator)
        operands = item.operands
        if op == "sh":
            analysis.reason("shading")
        elif op in ("cs", "CS") and operands:
            kind = _space_kind(operands[0], resources)
            if _is_pattern(operands[0], resources):
                analysis.reason("pattern colour space")
            elif kind == "unsupported":
                analysis.reason(f"unsupported colour space {str(operands[0])[:30]}")
            elif kind == "indexed_rgb":
                analysis.reason("indexed RGB vector colour")
        elif op == "gs" and operands:
            for reason in _gs_reasons(_get(_get(resources, "/ExtGState"), str(operands[0]))):
                analysis.reason(reason)
            ca = [_get(_get(_get(resources, "/ExtGState"), str(operands[0])), k) for k in ("/ca", "/CA")]
            if any(v is not None and float(v) < 0.999 for v in ca):
                note = "constant alpha kept (blending now happens in CMYK)"
                if note not in analysis.approximations:
                    analysis.approximations.append(note)
        elif op == "INLINE IMAGE" and operands:
            image = operands[0]
            if not getattr(image, "image_mask", False) and str(getattr(image, "colorspace", None)) not in (
                "/DeviceGray",
                "/G",
                "/DeviceCMYK",
                "/CMYK",
            ):
                analysis.reason("inline image not in gray/CMYK")
        elif op == "Do" and operands:
            xobj = _get(_get(resources, "/XObject"), str(operands[0]))
            if xobj is None:
                continue
            subtype = str(_get(xobj, "/Subtype"))
            if subtype == "/Image":
                if bool(_get(xobj, "/ImageMask", False)):
                    continue
                kind = _space_kind(_get(xobj, "/ColorSpace"), resources)
                if _get(xobj, "/ColorSpace") is None:
                    analysis.reason("image without a colour space (JPX)")
                elif kind in ("rgb", "indexed_rgb"):
                    if int(_get(xobj, "/BitsPerComponent", 8)) != 8 and kind == "rgb":
                        analysis.reason("RGB image that is not 8 bits per component")
                    elif isinstance(_get(xobj, "/Mask"), pikepdf.Array):
                        analysis.reason("RGB image with a colour-key mask")
                    elif _get(_get(xobj, "/SMask"), "/Matte") is not None:
                        analysis.reason("soft mask with premultiplied RGB matte")
                    else:
                        analysis.images[xobj.objgen] = (xobj, resources)
                        if _get(xobj, "/SMask") is not None:
                            note = "image soft mask kept (blending now happens in CMYK)"
                            if note not in analysis.approximations:
                                analysis.approximations.append(note)
                elif kind == "unsupported":
                    analysis.reason("image in an unsupported colour space")
            elif subtype == "/Form":
                key = xobj.objgen
                if depth >= MAX_DEPTH or key in seen:
                    continue
                group = _get(xobj, "/Group")
                if group is not None and str(_get(group, "/S")) == "/Transparency":
                    analysis.reason("transparency group")
                form_resources = _get(xobj, "/Resources", resources)
                analysis.streams.append((xobj, form_resources))
                try:
                    inner = pikepdf.parse_content_stream(xobj)
                except pikepdf.PdfError:
                    analysis.reason("unreadable form content")
                    continue
                _analyse(inner, form_resources, analysis, depth + 1, seen | {key})
        elif op == "Tf" and operands:
            font = _get(_get(resources, "/Font"), str(operands[0]))
            if font is not None and str(_get(font, "/Subtype")) == "/Type3" and font.objgen not in analysis.type3_fonts:
                analysis.type3_fonts.add(font.objgen)
                font_resources = _get(font, "/Resources", resources)
                for _name, proc in (_get(font, "/CharProcs") or {}).items():
                    if proc.objgen not in seen:
                        analysis.streams.append((proc, font_resources))
                        try:
                            _analyse(
                                pikepdf.parse_content_stream(proc),
                                font_resources,
                                analysis,
                                depth + 1,
                                seen | {proc.objgen},
                            )
                        except pikepdf.PdfError:
                            analysis.reason("unreadable Type3 glyph")


def _rewrite(instructions, resources, conv: ColourConverter, counts: dict) -> list:
    out = []
    stack = []
    fill_rgb = stroke_rgb = False
    for item in instructions:
        op = str(item.operator)
        operands = list(item.operands)
        if op == "q":
            stack.append((fill_rgb, stroke_rgb))
        elif op == "Q":
            if stack:
                fill_rgb, stroke_rgb = stack.pop()
        elif op in ("rg", "RG") and len(operands) == 3:
            cmyk = conv.colour(*(float(v) for v in operands))
            out.append(pikepdf.ContentStreamInstruction(list(cmyk), pikepdf.Operator("k" if op == "rg" else "K")))
            counts["operators"] += 1
            continue
        elif op in ("cs", "CS") and operands:
            is_rgb = _is_rgb_space(operands[0], resources)
            if op == "cs":
                fill_rgb = is_rgb
            else:
                stroke_rgb = is_rgb
            if is_rgb:
                out.append(pikepdf.ContentStreamInstruction([pikepdf.Name.DeviceCMYK], pikepdf.Operator(op)))
                counts["colour_spaces"] += 1
                continue
        elif (
            op in ("sc", "scn", "SC", "SCN")
            and len(operands) == 3
            and (fill_rgb if op in ("sc", "scn") else stroke_rgb)
        ):
            cmyk = conv.colour(*(float(v) for v in operands))
            out.append(pikepdf.ContentStreamInstruction(list(cmyk), pikepdf.Operator(op)))
            counts["operators"] += 1
            continue
        out.append(item)
    return out


def _convert_image(xobj, conv: ColourConverter, resources) -> str:
    """Convert one RGB / Indexed-RGB image stream in place. Returns 'image' or 'palette'."""
    cs = _get(xobj, "/ColorSpace")
    if _space_kind(cs, resources) == "indexed_rgb":
        if isinstance(cs, pikepdf.Name):
            cs = _get(resources, "/ColorSpace")[str(cs)]
        hival = int(cs[2])
        lookup = cs[3]
        table = lookup.read_bytes() if isinstance(lookup, pikepdf.Stream) else bytes(lookup)
        table = table[: 3 * (hival + 1)].ljust(3 * (hival + 1), b"\x00")
        rgb = np.frombuffer(table, dtype=np.uint8).reshape(1, hival + 1, 3)
        cmyk = conv.pixels(rgb).reshape(-1).tobytes()
        xobj.ColorSpace = pikepdf.Array([pikepdf.Name.Indexed, pikepdf.Name.DeviceCMYK, hival, pikepdf.String(cmyk)])
        return "palette"
    image = pikepdf.PdfImage(xobj).as_pil_image().convert("RGB")
    cmyk = conv.pixels(np.asarray(image))
    xobj.write(zlib.compress(cmyk.tobytes(), 6), filter=pikepdf.Name.FlateDecode)
    xobj.ColorSpace = pikepdf.Name.DeviceCMYK
    xobj.BitsPerComponent = 8
    for key in ("/Decode", "/DecodeParms", "/Intent"):
        if key in xobj:
            del xobj[key]
    return "image"


def _rasterise(pdf: pikepdf.Pdf, page: pikepdf.Page, index: int, source_doc, conv: ColourConverter, dpi: float) -> dict:
    src = source_doc[index]
    try:
        src.set_rotation(0)
        src.set_cropbox(*src.get_mediabox())
        bitmap = src.render(scale=dpi / 72.0, may_draw_forms=True)
        rgb = np.asarray(bitmap.to_pil().convert("RGB"))
    finally:
        src.close()
    cmyk = conv.pixels(rgb)
    height, width = cmyk.shape[:2]
    image = pikepdf.Stream(
        pdf,
        zlib.compress(cmyk.tobytes(), 6),
        Type=pikepdf.Name.XObject,
        Subtype=pikepdf.Name.Image,
        Width=width,
        Height=height,
        ColorSpace=pikepdf.Name.DeviceCMYK,
        BitsPerComponent=8,
        Filter=pikepdf.Name.FlateDecode,
    )
    x0, y0, x1, y1 = media_rect(page)
    page.obj.Resources = pikepdf.Dictionary(XObject=pikepdf.Dictionary(MxRaster=pdf.make_indirect(image)))
    page.obj.Contents = pdf.make_stream(b"q %.4f 0 0 %.4f %.4f %.4f cm /MxRaster Do Q" % (x1 - x0, y1 - y0, x0, y0))
    if "/Group" in page.obj:
        del page.obj["/Group"]
    return {"px": [width, height], "dpi": dpi}


def _count_rgb(pdf: pikepdf.Pdf) -> dict:
    """Post-check: DeviceRGB operators and RGB images still reachable from page content."""
    found = {"operators": 0, "images": 0}

    def walk(instructions, resources, depth, seen):
        for item in instructions:
            op = str(item.operator)
            if op in ("rg", "RG"):
                found["operators"] += 1
            elif op == "Do" and item.operands:
                xobj = _get(_get(resources, "/XObject"), str(item.operands[0]))
                if xobj is None:
                    continue
                if str(_get(xobj, "/Subtype")) == "/Image":
                    if _space_kind(_get(xobj, "/ColorSpace"), resources) in ("rgb", "indexed_rgb"):
                        found["images"] += 1
                elif str(_get(xobj, "/Subtype")) == "/Form" and depth < MAX_DEPTH and xobj.objgen not in seen:
                    walk(
                        pikepdf.parse_content_stream(xobj),
                        _get(xobj, "/Resources", resources),
                        depth + 1,
                        seen | {xobj.objgen},
                    )

    for page in pdf.pages:
        walk(pikepdf.parse_content_stream(page), _get(page.obj, "/Resources"), 0, set())
    return found


def cmyk_derivative(
    pdf_in,
    pdf_out,
    icc_profile,
    tac_limit: float = 300,
    *,
    source_profile=None,
    raster_dpi: float = 600,
    intent: str = "relative",
    black_point_compensation: bool = True,
    output_condition: str | None = None,
    force_raster_pages: list | None = None,
) -> dict:
    """Write the CMYK derivative of ``pdf_in`` to ``pdf_out``. Returns the derivative record."""
    if same_file(pdf_in, pdf_out):
        raise ValueError("pdf_out must differ from pdf_in (the approved RGB file is the record)")
    import pypdfium2 as pdfium

    conv = ColourConverter(icc_profile, tac_limit, source_profile, intent, black_point_compensation)
    source_sha = sha256_file(pdf_in)
    counts = {"operators": 0, "colour_spaces": 0, "images": 0, "palettes": 0}
    pages_record = []
    rasterised = []
    approximations: list[str] = []
    force = set(force_raster_pages or [])
    # Python file handle: Arabic (non-ANSI) Windows paths never reach pdfium as bytes.
    source_doc = pdfium.PdfDocument(open(pdf_in, "rb"), autoclose=True)  # noqa: SIM115
    try:
        with pikepdf.open(pdf_in) as pdf:
            analyses = []
            for index, page in enumerate(pdf.pages):
                analysis = _Analysis()
                group = _get(page.obj, "/Group")
                if group is not None and str(_get(group, "/S")) == "/Transparency":
                    analysis.reason("page transparency group")
                resources = _get(page.obj, "/Resources")
                try:
                    instructions = pikepdf.parse_content_stream(page)
                except pikepdf.PdfError:
                    instructions = []
                    analysis.reason("unreadable page content")
                _analyse(instructions, resources, analysis, 0, set())
                if index + 1 in force:
                    analysis.reason("raster requested")
                analyses.append((analysis, instructions, resources))

            done_images: set = set()
            for analysis, _instructions, _resources in analyses:
                if analysis.reasons:
                    continue
                for key, (xobj, image_resources) in analysis.images.items():
                    if key in done_images:
                        continue
                    try:
                        kind = _convert_image(xobj, conv, image_resources)
                        counts["images" if kind == "image" else "palettes"] += 1
                        done_images.add(key)
                    except Exception as exc:  # noqa: BLE001 - an image we cannot decode forces a raster page
                        analysis.reason(f"image could not be converted ({exc.__class__.__name__})")
                        break

            done_streams: set = set()
            for index, (analysis, instructions, resources) in enumerate(analyses):
                page = pdf.pages[index]
                entry = {"page": index + 1, "mode": "vector"}
                if analysis.reasons:
                    entry.update(
                        mode="raster",
                        reasons=analysis.reasons,
                        **_rasterise(pdf, page, index, source_doc, conv, raster_dpi),
                    )
                    rasterised.append({"page": index + 1, "reasons": analysis.reasons, "dpi": raster_dpi})
                else:
                    before = dict(counts)
                    page.obj.Contents = pdf.make_stream(
                        pikepdf.unparse_content_stream(_rewrite(instructions, resources, conv, counts))
                    )
                    for stream, stream_resources in analysis.streams:
                        if stream.objgen in done_streams:
                            continue
                        done_streams.add(stream.objgen)
                        new = pikepdf.unparse_content_stream(
                            _rewrite(pikepdf.parse_content_stream(stream), stream_resources, conv, counts)
                        )
                        stream.write(zlib.compress(new, 6), filter=pikepdf.Name.FlateDecode)
                    entry["converted_operators"] = counts["operators"] - before["operators"]
                for note in analysis.approximations:
                    if note not in approximations:
                        approximations.append(note)
                pages_record.append(entry)

            icc_stream = pdf.make_stream(conv.icc_bytes)
            icc_stream.N = 4
            condition = output_condition or conv.icc["description"] or Path(icc_profile).stem
            intent_dict = pikepdf.Dictionary(
                Type=pikepdf.Name.OutputIntent,
                S=pikepdf.Name.GTS_PDFX,
                OutputConditionIdentifier=pikepdf.String(condition),
                Info=pikepdf.String(conv.icc["description"] or condition),
                DestOutputProfile=icc_stream,
            )
            pdf.Root.OutputIntents = pikepdf.Array([pdf.make_indirect(intent_dict)])
            pdf.docinfo["/MxDerivedFromSha256"] = pikepdf.String(source_sha)
            pdf.docinfo["/MxDerivative"] = pikepdf.String("CMYK print derivative (not PDF/X certified)")
            remaining = _count_rgb(pdf)
            pdf.save(pdf_out, compress_streams=True)
    finally:
        source_doc.close()

    return {
        "kind": "cmyk_print_derivative",
        "record_is": "source",
        "source_path": str(pdf_in),
        "source_sha256": source_sha,
        "output_path": str(pdf_out),
        "output_sha256": sha256_file(pdf_out),
        "derived_from_sha256": source_sha,
        "icc_profile": {"path": str(icc_profile), **conv.icc},
        "output_condition": condition,
        "intent": conv.intent,
        "black_point_compensation": black_point_compensation,
        "tac_limit": conv.tac_limit,
        "max_tac_seen": round(conv.max_tac_seen, 1),
        "tac_capped_samples": conv.tac_capped,
        "converted": counts,
        "remaining_rgb": remaining,
        "pages": pages_record,
        "rasterised_pages": rasterised,
        "raster_dpi": raster_dpi,
        "approximations": approximations,
        "pdfx_certified": False,
        "note_ar": NOTE_AR,
        "note_en": NOTE_EN,
    }
