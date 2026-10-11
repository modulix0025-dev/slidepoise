# PHASE_4_NOTES — المرحلة 4: الخطوط · Phase 4: fonts

> 2026-10-11 · google/fonts مثبّت على `bd8f81ddb5c74d5c8897b36ad88b440266245103` · 214 عيلة خط (54 عربي · 160 لاتيني).
> الكود بيقيس ويتحقق ويبني بس؛ أي حكم بصري للـAgent أو المشغّل. أي حاجة متتثبتش غير على جهاز المشغّل (ويندوز + PowerPoint) مكتوبة **pending on-device**.

## 1 · اتعمل إيه · What was built

**AR:** كتالوج خطوط كامل اتبنى من الـbytes نفسها عند الـcommit المثبّت (بصمة sha256 ورابط raw لكل ملف)، ودفتر تراخيص فيه قرار لكل عيلة، وبيلد Office-safe للخطوط المتغيّرة (Regular/Bold بأسماء صح، وإعادة تسمية إجبارية لو فيه اسم محجوز RFN، ونفس المدخل ⇐ نفس البايتات)، وفحص جودة لكل الـ214 (تغطية، تشكيل 216 اسم مصري، اختبار تصادم الحركات بالرسم، إذن التضمين، الخطوط الملوّنة)، وتثبيت ويندوز per-user/machine، وحمولة مزامنة M6، وفاحص خطوط الديك، ونظام تايبوجرافي، و33 ثيم خطوط، واختيار خط اسم الطفل (M7)، و44 preset لـName Art والمؤثرات الصوتية، وكتيّب عيّنات PDF.

**EN:** a catalog re-derived from the bytes at the pinned commit; a per-family licence ledger; deterministic Office-safe static builds with mandatory RFN renaming; QA of all 214 families; Windows install + M6 sync; a deck font validator; the typography grid; 33 type themes; M7 customer choice; 44 native-effect presets; a specimen book.

| Item (brief) | Where | Status |
|---|---|---|
| Catalog DB (sha256, URL, licence, flags, RFN, axes, name table; drift vs appendix + Phase 0) | `mxstudio/fonts/build_catalog.py`, `catalog.py` → `catalog/fonts/catalog.json` | ✅ 214 families · 311 files · 75 491 712 bytes — same totals as Phase 0 |
| Licence ledger (decision per family; RFN ⇒ rename; never sell fonts alone; fsType) | `ledger.py` → `catalog/fonts/font_license_ledger.json` | ✅ 131 `bundle_embed` · 83 `bundle_embed_rename_modified_builds` |
| Office-safe builds (instancer, name IDs 1/2/4/6/16/17, OS/2 + macStyle bits, deterministic, RFN guard) | `office_build.py` → `catalog/fonts/office_builds.json` | ✅ 43 VF families → 100 static files, all 43 rebuilt a second time with identical bytes; 5 (Readex Pro, Baloo Bhaijaan 2, Handjet, Lexend, Nunito) also rebuilt in a fresh process with identical bytes; 6 renamed (`MX Kids F019 Reem Kufi`, `MX Kids F022 Mada`, `MX Kids F033 Readex Pro`, `MX Kids F056`, `MX Kids F065`, `MX Kids F076`); 163 static families install unmodified |
| Font QA → status + named reasons | `qa.py` → `catalog/fonts/qa_status.json`; corpora `egyptian_names.json` (111 boys + 105 girls), `harakat_corpus.json` | ✅ run on all 214 from the checkout |
| Install (per-user / machine, UAC in Arabic, wait for idle, never kill) | `install.py` | ✅ logic + tests with `MemoryBackend`; **Windows path pending on device** |
| M6 sync payload/ack (+ HMAC signing via vendored `modulex_signing`) | `sync.py` | ✅ build/verify/apply/ack; transport endpoint not built here |
| Deck font validator (a:latin/ea/cs/sym, theme `+mj/+mn` resolved, exact names) | `deck_validator.py` | ✅ |
| Typography grid (8 roles × A5/A4 × 3 ages × AR/EN) | `typography.py` | ✅ 96 cells; EN A4 body marked *derived* |
| Type themes ≥30 + validator | `themes.py`, `catalog/fonts/type_themes.json` | ✅ 33 (12 seeds + 21); 0 errors, 10 recorded warnings |
| Customer font choice (M7) | `customer_choice.py` | ✅ payload + fallback note + live preview with `fit_text` |
| Name Art (22) + sound effects (22), native DrawingML | `name_art.py` | ✅ |
| Specimen book PDF | `specimen.py` | ✅ full book generated through LibreOffice (see §3) |

## 2 · حالة الخطوط · QA status counts

| | عدد |
|---|---|
| `certified_print` (كل الفحوص الحتمية عدّت) | **206** |
| `screen_only` (ملوّن، محجوز للشاشة) | **8** — Cairo Play, Reem Kufi Fun, Blaka Ink, Reem Kufi Ink, Aref Ruqaa Ink, Bungee Spice, Honk, Nabla |
| `rejected` | **0** |
| مسموح لنص مشكول (`vowelized_text`) | 36 |
| مسموح لمتن مشكول (`vowelized_body` = نظيف + دور body) | 26 |
| on-device export proof | **pending لكل الـ214** |

Named findings across the catalog: `harakat_mark_base_collision` 14 · `colour_font_quarantined` 8 · `harakat_mark_mark_collision` 5 (Qahiri, Aref Ruqaa, Aref Ruqaa Ink, Amiri, Gulzar) · `no_tatweel` 4 (Blaka, Blaka Hollow, Blaka Ink, Gulzar) · `harakat_missing` 4 · `no_gpos_mkmk` 3 (Thabit, Ruwudu, Alkalami) · `monospace_arabic` 1 (Thabit → title/effect only) · `arabic_indic_digits_look_western` 1 (Zain) · `fsType_editable_embedding` 1 (Frijole, fsType 8 — embedding allowed).

**`certified_print` معناها إن الفحوص الحتمية عدّت، مش إن التصدير الحقيقي من PowerPoint اتثبت.** الخطوة دي pending (§4).

## 3 · اكتشافات اتقاست · Measured findings

1. **Varela Round RFN** — الترخيص بيحجز `'Varela'` **و** `‘Varela Round’` (علامة تنصيص منحنية). Phase 0 قرأ واحد بس؛ الكتالوج اتصلّح وسجّل الـdrift. *The OFL header reserves both names; Phase 0 missed the curly-quoted one.*
2. **Amiri** — الحركات بتتلامس تصميمًا (الفتحة جوه الشدة) وده **مش** بيتحسب تصادم (بنقارن الحبر بعد تآكل 1px). لكن فيه تداخل حقيقي بين حركات حروف متجاورة: في «الحَبْلَ» سكون الباء بيدخل في فتحة اللام. فـAmiri معتمد للطباعة ولمتن **غير مشكول**؛ الثيمات اللي بتستخدمه ليها `ar_body_vowelized` تاني (Scheherazade New / Markazi Text / Noto Naskh Arabic). *Designed contact is not a collision; the «الحَبْلَ» overlap is real, so Amiri is not auto-certified for vowelized body. An operator who reviews the specimen may decide otherwise — that is a visual decision outside this code.*
3. **Rubik / Handjet / Badeen Display / Cairo / Vibes** — حركات فوق نقط الحروف أو جوه الألف (اتشافت بالرسم) ⇒ مش لمتن مشكول.
4. **Ruwudu / Alkalami / Thabit** مفيهمش `mkmk`؛ بالقياس Ruwudu نضيف (مسموح لمتن مشكول)، Alkalami فيه تصادم حركة/حرف، Thabit ناقصه حركات وثابت العرض ⇒ عناوين مؤثرات بس.
5. **Zain** — الأرقام الهندية ٠ و٢–٩ مرسومة **بنفس outline** الأرقام الغربية (الـ«١» = «1» طبيعي في أغلب الخطوط ومش بيتحسب).
6. **Reem Kufi** مش monospace — القياس لازم يكون على الأشكال بعد التشكيل (HarfBuzz)، مش على glyphs الـcmap.
7. **LibreOffice + `a:prstTxWarp`** — أي warp (قوس/موجة/نفخ) بيخلّي LibreOffice 24.2.7.2 يرسم النص كـcurves: الـPDF من غير خط، والمحوّل بتاع المشغّل بيرفضه كـimage-only. الحدود والتدرّج والتوهّج والظل بيفضلوا نص حقيقي (الخط متضمّن والنص بيتقري). ⇒ `presets_for_engine("soffice")` بيستبعد الـwarps؛ مع PowerPoint pending on device.
8. **كتيّب العيّنات كامل عبر LibreOffice** (`docs/mag/phase-4/evidence/specimen_libreoffice_proof.json`): 239 صفحة (206 عيلة + 33 ثيم)، **كل الـ206 خط اتضمّنوا** في الـPDF. الـproof الصارم (`pdf_text.text_proof`) بيعدّي في كل الصفحات اللاتيني و162/239 إجمالًا؛ الصفحات العربي بتقع بس بسبب استخراج النص (مسافات جوه الكلمات المشكولة، ترتيب مكوّنات الـligature). الفحص المرن (نفس الحروف والحركات وعلامات الترقيم) بيعدّي **238/239**؛ صفحة Amiri فيها فتحة + شدة زيادة في الاستخراج (ToUnicode لـglyph مركّب) — يتراجع على تصدير PowerPoint.
9. **Tajawal** اسمه الكامل (ID4) «Tajawal» مش «Tajawal Regular» ⇒ ويندوز هيبلّغ «Tajawal». المقارنة بالأسماء دايمًا بالظبط (مسافات جوه الاسم مهمة: `Blabeloo  MagdySoliman`).

## 4 · لسه pending على الجهاز · Pending on-device proof

| What | Proof Runner step |
|---|---|
| تصدير حقيقي من PowerPoint لكل خط معتمد (الخط متضمّن + النص المستخرج = المدخل) | Proof Runner › Fonts › «تصدير حقيقي»: install the certified set per-user, open the specimen deck (`python -m mxstudio.fonts.specimen --out-dir … --engines powerpoint`), check `embedding.missing == []` and every page's text proof |
| تثبيت ويندوز الفعلي (HKCU/HKLM + `AddFontResourceExW` + `WM_FONTCHANGE`) والاسم اللي ويندوز بيبلّغ عنه | Proof Runner › Fonts › «تثبيت وتأكيد» with `WindowsBackend`, then `verify_installed` |
| إن خدمة/حساب تاني مش شايف خطوط per-user، والتحويل لـmachine-wide مع UAC | run the export worker as its real account; compare `plan_install` with what the worker sees |
| PowerPoint المفتوح مش شايف الخطوط الجديدة لحد ما يتفتح تاني | install while PowerPoint is open; export; restart when `after_install` says idle |
| Name Art بالـwarps: هل PowerPoint بيسيب النص قابل للاستخراج في الـPDF؟ | Proof Runner › Fonts › Name Art export (one slide per warp preset) |
| مقاسات EN A4 (مشتقة) | printed proof review by the operator |

## 5 · المتطلبات · Dependencies

No new dependency. Uses fontTools (`varLib.instancer`), uharfbuzz (through `slidepoise.arabic`), numpy, lxml, python-pptx, jsonschema, pikepdf, pypdfium2 (via `mxstudio.validators.pdf_text`), the vendored `pptx_to_pdf.py` and `modulex_signing.py` (imported, not copied). LibreOffice only for the specimen / export tests on Linux (they skip without it). Windows install uses stdlib `ctypes` + `winreg` and `mxstudio.proc.run_hidden` for `tasklist`.

## 6 · إزاي تعيد التوليد · Regenerate

```
export PYTHONPATH=.:slidepoise/runtime/src                                   # repo root
python -m mxstudio.fonts.build_catalog --checkout <google-fonts@bd8f81dd>     # catalog.json
python -m mxstudio.fonts.ledger                                               # font_license_ledger.json
python -m mxstudio.fonts.qa --checkout <google-fonts@bd8f81dd>                # qa_status.json (~45 s)
python -m mxstudio.fonts.office_build --checkout <…> --out-dir <builds>       # office_builds.json (+ determinism re-check)
FONTCONFIG_FILE=<install set> python -m mxstudio.fonts.specimen --out-dir <dir> --engines soffice
python -m pytest tests/mag/fonts -q -p no:cacheprovider                       # 120 tests, no network, no checkout
```

Tests use only `tests/mag/fixtures/fonts` (Tajawal, Amiri) and `tests/mag/fonts/fixtures` (Reem Kufi VF+RFN, Reem Kufi Fun colour, Blaka no-tatweel, Thabit monospace, Chewy Apache), each with its licence file and `PROVENANCE.json`.
