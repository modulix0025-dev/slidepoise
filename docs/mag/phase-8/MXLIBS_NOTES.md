# MXLIBS_NOTES — مكتبات الطباعة النقية · Pure print libraries (mx_textfit, mx_preflight2, mx_impose)

> 2026-10-11 · owner paths: `mxlibs/mx_textfit/`, `mxlibs/mx_preflight2/`, `mxlibs/mx_impose/`, `mxlibs/build_manifests.py`, `mxlibs/__init__.py`, `tests/mag/mxlibs/`, `docs/mag/phase-8/MXLIBS_NOTES.md` · no shared file edited · brief §6.7 + M4/M5.

## 1 · الخلاصة · Summary

**AR:** عملنا 3 مكتبات صغيرة "نقية" هتتنسخ زي ما هي (byte-for-byte) جوه سيستم الطلبات بتاع المشغّل (OrderManagement). المكتبات دي **بتقيس وبتطلّع حقايق وأخطاء ليها أسامي** — عمرها ما بتكتب حالة الطباعة ولا بتحكم على شكل التصميم:

1. **`mx_textfit`**: النص اللي العميل كتبه هيدخل في المربع ولا لأ؟ الرد واحد من: «داخل تمام» / «هيصغر لـ N نقطة» / «النص ده أطول من المكان المتاح — قصّره شوية». بيدوّر على الخط بالاسم بالظبط (حتى المسافتين في `Blabeloo  MagdySoliman`)، وبيقيس بـ HarfBuzz، ولو مش موجود بـ Pillow+raqm، ولو مش موجود بيقيس تقريبي **وبيقول إنه تقريبي**. السطر بيتكسر عند المسافات بس — عمره ما بيقسم كلمة عربي.
2. **`mx_preflight2`**: فحص ملف الـPDF قبل المطبعة: المقاس، النزيف (بنرسم حواف الصفحة ونشوف الرسمة داخلة في النزيف ولا واقفة عند حد القص)، الهامش الآمن، الخطوط مدمجة، دقة كل صورة بالمقاس اللي هتتطبع بيه، التشفير، عدد الصفحات، ملف صور بس، وألوان RGB/CMYK مقارنة ببروفايل المطبعة.
3. **`mx_impose`**: علامات القص، ترتيب الدبّوس (saddle-stitch) للتجليد من اليمين (عربي) ومن الشمال، تعويض الـcreep، ونسخة CMYK مشتقة بـ pikepdf + LittleCMS (من غير Ghostscript الممنوع). **الملف المعتمد RGB هو السجل**، ونسخة الـCMYK مربوطة بيه بالـsha256 — ومش بنقول عليها PDF/X معتمد.

**EN:** Three small pure libraries, vendored verbatim into the operator's OrderManagement system. They measure and return facts plus *named* failures; they never write print state (OM `print_service.py` stays the only writer) and never issue a visual verdict.

- `mx_textfit` — `fit(text, box_emu, font, rules)` → fits / will shrink to N pt / does not fit, with Egyptian-Arabic messages; exact family-name font resolution; HarfBuzz → Pillow+raqm → approximate (flagged); whitespace-only breaking; PPTX paragraph box extraction for editor ids `t-<slide>-<shape_id>-<para>` (stdlib XML, python-pptx not needed).
- `mx_preflight2` — `run(pdf_path, profile)` → `{"ok","failed","checks":[{"id","ok","ar","en","detail"}],"warnings",…}` with 11 named checks.
- `mx_impose` — crop marks, saddle-stitch imposition (LTR and RTL, creep), and `cmyk_derivative` (DeviceRGB → DeviceCMYK operators and images via LittleCMS, TAC cap, OutputIntent, 600 dpi raster fallback flagged per page, sha256 link to the approved RGB record, `pdfx_certified: false`).

Tests: **75 passed** in `tests/mag/mxlibs/` (27 textfit, 20 preflight, 18 impose, 10 vendoring), each suite with negative controls; ~9 s on Linux CI.

## 2 · اللي اتبنى · What was built

| Brief item | Where | Status |
|---|---|---|
| `fit(text, box_emu, font, rules)` → `{fits, size_pt, lines, overflow_pt, font_used, substitute, method}` + verdicts in Egyptian Arabic | `mx_textfit/fit.py` | ✅ verdicts `fits` · `will_shrink` · `does_not_fit` (reasons `height`, `word_too_wide`, `too_many_lines`, `too_many_chars`) · `missing_glyphs` · `font_missing` |
| Exact family-name resolution (internal double spaces kept) | `mx_textfit/fonts.py`, `_sfnt.py` | ✅ stdlib `name`/`OS/2`/`head`/`hhea`/`cmap` reader (no fontTools needed to resolve); single-space name is a *different* font (negative control) |
| HarfBuzz → Pillow(raqm) → fontTools advance widths flagged `approximate` | `mx_textfit/measure.py` | ✅ HarfBuzz and raqm agree exactly; fallbacks proven by hiding `uharfbuzz` / raqm / fontTools in tests |
| Whitespace-only breaking; never split Arabic words | `fit.wrap` | ✅ NBSP / figure space / narrow NBSP never break; a too-wide word is a named overflow |
| Helper: box size + font of an editor paragraph from a PPTX | `mx_textfit/pptx_box.py` | ✅ `paragraph_box`, `fit_paragraph_edit`; inheritance run → shape lstStyle → layout/master placeholder → master txStyles / presentation defaultTextStyle → theme fonts (`+mn-cs`, Arab script font); insets, `normAutofit` (fontScale, lnSpcReduction), `spAutoFit` (height not a limit), group scaling, spcBef/spcAft |
| Editor limits (MAX_LINES 30, per-paragraph cap `min(2000, max(80, 2·len+40))`) | `fit.char_limit`, `EDITOR_MAX_LINES` | ✅ |
| Preflight checks (size ± tol + 2×bleed, bleed coverage by raster, safe band incl. important boxes, fonts embedded, image DPI by CTM, encryption, page count, image-only, colour facts vs printer) | `mx_preflight2/` | ✅ 11 checks: `readable, encryption, file_size, page_count, page_size, bleed, safe_zone, fonts_embedded, image_only, image_dpi, colour_space` |
| Crop marks | `mx_impose/marks.py` | ✅ 1:1 placement, bleed kept, marks offset ≥ bleed, registration colour (Separation /All), TrimBox/BleedBox set |
| Saddle-stitch (16 A5 → 4 A4 sheets duplex = 8 sides, LTR/RTL, creep mm) | `mx_impose/saddle.py` | ✅ LTR outer front 16\|1, back 2\|15; RTL mirrored 1\|16, 15\|2; blanks padded; creep linear 0 → creep_mm, monotonic |
| `cmyk_derivative(pdf_in, pdf_out, icc_profile, tac_limit=300)` | `mx_impose/cmyk.py` | ✅ operators, `cs/sc/scn` on RGB/ICC-RGB spaces, Form XObjects, Type3 glyphs, 8-bit RGB images and Indexed-RGB palettes; OutputIntent with the ICC stream; raster fallback at 600 dpi flagged; sha link |
| MANIFEST.json per lib + builder | `mxlibs/build_manifests.py` | ✅ deterministic, `--check`, `--verify <dir>`; CRLF conversion is detected as tampering |
| Gate fixtures: 1 good + 9 named bad | `tests/mag/mxlibs/_mxfixtures.py` + `test_mx_preflight2.py` | ✅ built with pikepdf (embedded Tajawal TrueType, RGB images at chosen DPI); each bad file fails **only** its own check (wrong-size also moves text out of the A5 safe area — a real second finding) |

## 3 · الواجهات العامة · Public APIs

```python
# mx_textfit  (requires Pillow; optional uharfbuzz, fontTools)
fit(text, box_emu=(w, h), font={"family", "size_pt", "bold", "italic", "line_spacing", "line_spacing_pt",
    "fallback_families"}, rules={"min_size_pt", "max_lines", "inset_emu", "allow_shrink", "grow_height",
    "reserved_height_pt", "max_chars"}, *, resolver=None, font_dirs=None, font_files=None, method="auto") -> dict
paragraph_box(pptx_path, "t-<slide>-<shape_id>-<para>", *, slide_base=1, para_base=0) -> dict
fit_paragraph_edit(pptx_path, para_id, new_text, rules=None, *, original_text=None, **fit_kwargs) -> dict
char_limit(original_text) -> int;  FontResolver(directories, files).resolve(family, bold, italic)

# mx_preflight2  (requires pikepdf, pypdfium2, numpy, Pillow)
run(pdf_path, profile=None, **overrides) -> {"ok", "failed", "checks", "warnings", "sha256", "bytes", "pages",
                                              "page_size_mm", "facts"}
make_profile(size="A5", trim_mm=None, tolerance_mm=1.0, bleed_mm=3.0, safe_mm=5.0, expected_pages=None,
             min_dpi=150, warn_dpi=300, colour="rgb"|"cmyk"|"any", icc_path=None, important_boxes=[...],
             check_text_in_safe=True, raster_dpi=150, max_bytes=500 MiB, password=None)

# mx_impose  (requires pikepdf, pypdfium2, numpy, Pillow)
crop_marks(pdf_in, pdf_out, *, bleed_mm=None, mark_len_mm=5.0, offset_mm=None, margin_mm=2.0) -> record
saddle_stitch_order(n_pages, binding="ltr"|"rtl") -> [{"sheet", "side", "left", "right", ...}]
creep_offsets(n_sheets, creep_mm) -> [0.0, ..., creep_mm]
impose_saddle(pdf_in, pdf_out, *, binding="ltr", sheet="auto", creep_mm=0.0, duplex="short_edge") -> record
cmyk_derivative(pdf_in, pdf_out, icc_profile, tac_limit=300, *, source_profile=None, raster_dpi=600,
                intent="relative", black_point_compensation=True, output_condition=None,
                force_raster_pages=None) -> record
```

`important_boxes` use canvas millimetres with a **top-left** origin (the same frame as `slidepoise.print_geometry`): `{"page": 2, "box_mm": [x, y, w, h], "label": "child name"}`.

## 4 · قرارات وأرقام افتراضية · Defaults and why

| Default | Value | Reason |
|---|---|---|
| Shrink step | 0.5 pt, from the declared size down to `min_size_pt` | same as the Phase-1 runtime fitter; results equal `slidepoise.arabic.fit_text` exactly (tested) |
| Line height | max(Windows ascent+descent × spacing, ink height × 1.08) | harakat never collide; exact `spcPts` spacing wins |
| Insets | PowerPoint defaults 0.1″ / 0.05″ (91440 / 45720 EMU) | read from `bodyPr` when present |
| `allow_shrink` | off unless the shape has `normAutofit` | the editor keeps the first run's size; shrinking is only real when PowerPoint will shrink |
| `font_missing` | reported, never a silent substitute | a fallback is used only when the caller names it, and `substitute` says so |
| Preflight tolerance | ±1 mm (as OM P129) | trim + 2 × bleed when bleed > 0 |
| Bleed test | raster at 150 dpi; per side, positions where ink touches the trim edge must have ≥ 90 % ink through the bleed band; > 5 % gaps fails | a white design edge needs no bleed and passes |
| Safe band | 5 mm inside trim, 0.3 mm tolerance; text runs from pdfium text layer + declared important boxes | text in the bleed is reported as zone `bleed`, otherwise `safe_band` |
| DPI | fail < 150 (OM OK_DPI), warn < 300 (OM IDEAL_DPI); images < 3 mm ignored | effective DPI = pixels ÷ placed size from the CTM (q/Q/cm, nested Form `/Matrix`, UserUnit) |
| Printer colour | `rgb` (the approved record is RGB) | `cmyk` additionally requires an OutputIntent whose ICC sha256 equals the printer's profile |
| CMYK intent | relative colorimetric + black-point compensation, FOGRA39L (CC0) | neon green (57,255,20) → C60 M0 Y93 K0; sRGB black → 300 % TAC (the profile's own ink limit) |
| Raster fallback | 600 dpi, Flate, from the **original** page | reasons recorded per page: shading, pattern, transparency group, soft-mask/blend mode, RGB inline image, unsupported colour space, colour-key mask, premultiplied matte |
| Converted images | Flate (lossless) | avoids the Adobe-inverted CMYK JPEG ambiguity; larger files, exact pixels |

## 5 · حدود معروفة · Known limits (honest)

- **AR:** القياس بيستخدم سطر واحد بخط الفقرة المعدّلة لكل الشكل؛ لو الشكل فيه فقرات بأحجام مختلفة النتيجة تقريبية (بنحسب مسافات قبل/بعد الفقرات). اتجاه النص الرأسي والأعمدة جوه المربع مش مدعومين.
- **EN:** A shape body is measured with the edited paragraph's font for every paragraph (spcBef/spcAft are added). Vertical text, columns and per-run size changes inside one frame are not modelled. Mixed Arabic/Latin lines are measured with one font (the `cs` face for RTL text, `latin` otherwise); PowerPoint uses both — the difference is small for Tajawal-class fonts but it is not zero.
- Text-overflow vs PowerPoint's own layout (its line breaker, kerning and autofit rounding) is **pending on-device proof** (below).
- `mx_preflight2` ignores annotation appearance streams for colour and DPI, and does not open tiling patterns for DPI. Spot colours are warnings, not failures.
- `cmyk_derivative` leaves annotations untouched, keeps DeviceGray as is (prints on K), and treats 16-bit RGB, JPX without a colour space and colour-key masks by rasterising the page. Constant alpha and image soft masks are kept (blending now happens in CMYK) and listed under `approximations`.
- The derivative is **not** PDF/X: it has an OutputIntent (`/S /GTS_PDFX`) but no `GTS_PDFXVersion`, no TrimBox enforcement and no PDF/X validation.
- Imposition clips each page to its cell at the spine; on an A4 sheet two A5 pages leave 0.5 mm per outer side, so the outer bleed is mostly lost — use `sheet="SRA3"` (or a custom size) when the press needs bleed on the imposed sheet.

## 6 · التوصيل بسيستم المشغّل · Integration (behind flags, default OFF)

The Kit already vendors these libs (`mxstudio/kit/patches/p_textfit.py`, `p_preflight2.py`) and calls exactly `paragraph_box` / `fit` / `char_limit` and `run(path, {"size", "bleed_mm", "expected_pages", "max_bytes"})` — the APIs above match those call sites.

Notes for the Kit owner (not edited by me — shared files):

1. **Safe-zone default in OM context:** with `bleed_mm=0` the page *is* the trim, and the default `safe_mm=5` flags any text closer than 5 mm to the edge. If the operator's templates place folios or decorations nearer the edge, `profile_from()` in `payloads/preflight2/hook.py` should pass an explicit `safe_mm` (or `check_text_in_safe=False` until the templates are measured).
2. **Line endings:** MANIFEST sha256 covers bytes. A `.gitattributes` rule `mxlibs/** -text` (shared file) would stop a Windows checkout with `core.autocrlf=true` from breaking verification; `verify_manifest` reports such a copy as `mismatched` (tested).
3. **CI:** add `python mxlibs/build_manifests.py --check mx_textfit mx_preflight2 mx_impose` to the mag CI job (shared workflow file).
4. `MODULEX_MAG_IMPOSE` (Kit's flag list) can point at `mx_impose`; it is vendor-ready.

Flags stay default OFF; P129 `preflight.run` remains the gate and `print_service.py` the only writer of print state.

## 7 · لسه محتاج إثبات على جهاز المشغّل · Pending on-device proof

| Claim | Proof Runner step |
|---|---|
| `fit` agrees with PowerPoint's own wrap/shrink for the real templates and `Blabeloo  MagdySoliman` | Phase 8a On-Device Proof Runner, step `export`: for each template paragraph, run `mx_textfit.fit_paragraph_edit` with the original text and with text +30 %, export through PowerPoint (vendored `pptx_to_pdf`), compare the PDF line count per paragraph (pdfium) with `line_count`; any disagreement is recorded, not hidden |
| Paragraph-id convention (`slide` 1-based in presentation order, `para` 0-based) equals OM `app/editor/deck.py` | Proof Runner step `generate_story`: take ids from a real editor session payload and assert `paragraph_box(...)["text"]` equals the editor's text for every id |
| `mx_preflight2` on PowerPoint exports (fonts embedded as PowerPoint subsets, DPI of placed photos) | Proof Runner step `preflight_v2` (already wired in `mxstudio/kit/proofs.py`): record the full result for one exported template per size |
| Arabic Windows paths for pikepdf/pypdfium2 (`C:\المشروع\…`) | Proof Runner: run `pytest tests/mag/mxlibs -k arabic_paths` on the operator PC (passes on Linux CI) |
| OM's installed versions of Pillow / pikepdf / pypdfium2 support the calls used | Proof Runner: `python -c "import mx_preflight2, mx_impose, mx_textfit"` from OM's venv after vendoring, then `verify_manifest` |
| CMYK derivative on the operator's printer | print the FOGRA39 derivative of one approved magazine and compare with the soft proof (same step as Phase 6 colour proof); adjust `tac_limit` per printer |

## 8 · التشغيل · How to run

```bash
python -m pytest tests/mag/mxlibs -q -p no:cacheprovider
python mxlibs/build_manifests.py mx_textfit mx_preflight2 mx_impose     # after any change to these libs
python mxlibs/build_manifests.py --check mx_textfit mx_preflight2 mx_impose
python mxlibs/build_manifests.py --verify <vendored copy of a lib>
```

Negative controls: single-space font name not resolved; Latin-only subset font → `missing_glyphs`; each of the 9 bad PDFs fails its own check id; the RGB record fails a CMYK printer profile; the CMYK derivative fails a GRACoL printer profile; trim-only page fails `bleed` (and passes with bleed 0); import scan catches a project import; tampered/CRLF/extra/missing files fail `verify_manifest`; stale manifest is reported by `--check`.
