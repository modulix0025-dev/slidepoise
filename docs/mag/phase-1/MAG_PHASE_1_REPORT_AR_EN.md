# MAG_PHASE_1_REPORT_AR_EN — المرحلة 1: الـfork ومحرّك الطباعة العربي · Phase 1: fork & Arabic print engine

> 2026-10-11 · branch `claude/adoring-mccarthy-zgg4ek` · local tag `mag-phase-1` (the session's git proxy refuses tag pushes — see Phase 0 report) · plan approved with D13 (no commercially-licensed component).

## 1 · الخلاصة · Summary

**AR:** الـfork بقى يطلّع صفحة مجلة مطبوعة حقيقية: مقاس A5/A4 طولي بالـbleed، نص عربي RTL متقاس بـHarfBuzz على اسم الخط بالظبط (مع حساب التشكيل)، اسم الطفل في run لوحده، وأماكن صور `<p:ph type="pic">` اللي الـConsole بيعدّها. التحقّق اتعمل **بكود المشغّل نفسه منسوخ حرفيًا** (`replace_in_shape`، `deck_picture_slots`) و**بتصدير LibreOffice** من خلال `pptx_to_pdf.py` المنسوخ: كل كلمة وكل حركة في الديك موجودة في الـPDF. كمان اتشالت ملفات PwC (D1) واتثبّت Remix Icon على 4.8.0 (D10). قواعد Phase 1 كلها خضرا، ومع كل فحص negative control.

**EN:** The fork now emits real print pages: A5/A4 portrait with bleed, RTL Arabic measured with HarfBuzz on the exact family (harakat-aware), the hero name as its own run, and `<p:ph type="pic">` placeholders the Console counts. Validation uses **the operator's own code, copied verbatim**, and a **LibreOffice export** through the vendored `pptx_to_pdf.py`: every word and every haraka of the deck is in the PDF. PwC material removed (D1), Remix Icon pinned to 4.8.0 (D10). Every gate check has a negative control.

## 2 · اللي اتبنى · What was built (§6.1)

| §6.1 item | Where | Status |
|---|---|---|
| 1 Shaping-correct measurement (HarfBuzz + fontTools; bidi runs; whitespace-only breaks; Arabic-Indic/Western digit setting; harakat-aware line height; fonts by family name from Windows font folders + registry, Linux, macOS, `SLIDEPOISE_FONT_DIRS`; names never whitespace-collapsed) | `slidepoise/runtime/src/slidepoise/arabic/{fonts,shaping,fit}.py`; upstream `text_fit._fits` routes RTL copy here | ✅ — bidi is run segmentation by Unicode class (widths are reorder-invariant), so **no LGPL bidi dependency** is needed |
| 2 RTL PPTX output (`rtl="1"`, `algn="r"`, `lang="ar-EG"` on every run, `a:cs` typeface, one `a:pPr` per paragraph) | `scene_to_pptx.mjs` (opt-in `style.direction`) + `runtime/scripts/print_fork_xml.py` via `postprocess_pptx.py` | ✅ |
| 3 Print geometry (portrait A4/A5/custom, bleed 3 mm, safe 5 mm, canvas = trim + bleed, mirrored folios for RTL/LTR books) | `slidepoise/runtime/src/slidepoise/print_geometry.py`; spec `page.canvas_mm` | ✅ — `<p:sldSz>` is exactly 5 544 000 × 7 776 000 EMU for A5+3 mm |
| 4 Picture placeholders (`picture_placeholder` → slide `<p:sp><p:ph type="pic" idx>` + matching layout placeholder, ordered) | renderer marker + `print_fork_xml.apply_picture_placeholders` | ✅ Console rule returns the declared map; python-pptx sees `PicturePlaceholder` and injection keeps the map |
| 5 Name token (one whole run; prefix forms) | `runs` with `role: child_name`; dedication written «لـ<name>» (tatweel) | ✅ OM rule counts exactly; integrity check flags split names |
| 6 Gendered & bilingual payloads on one semantic map | `mxstudio/factory/payloads.py` | ✅ resolve per variant, direction/lang/alignment mirroring, coverage + name-token findings |
| 7 Children's-book profiles | — | ⏳ **moved to Phase 3** with the Art Desk, where treatments (cloud bubble, banner, scroll, sticker, scrim) are generated and reviewed; building them before the Art Desk would be guesswork |
| 8 No Arabic glyphs in generated art | `mxstudio/validators/art_text.py` (OpenCV evidence + named blocking finding `glyph_like_marks_in_text_slot`) | ✅ evidence-level; the host Agent's visual review still looks at every target |

Supporting: `mxstudio/validators/operator_ports.py` (verbatim Appendix B.1/B.4 blocks, sha-pinned; `replay_generate_story` = STEP 1 then STEP 2 in OM's order; `name_run_integrity`), `mxstudio/validators/pdf_text.py` (text proof), `mxstudio/validators/synthetic_story.py` (Appendix-A-shaped pages), `slidepoise/references/print-arabic.md` (+1 routing line in `SKILL.md`), `.github/workflows/mag-ci.yml`.

## 3 · أدلة البوابة · Gate evidence

Synthetic decks built to Appendix A anatomy: ولد A5, بنت A5, ولد A4 — 4 slides each: scene + RTL body with the name, second scene page, dedication, back page with 2 placeholders.

| Gate requirement | Result |
|---|---|
| Console `deck_picture_slots` (verbatim) = declared slot map | `{1: 1, 2: 1, 4: 2}` for all three decks ✅ |
| OM `replace_in_shape` (verbatim) replacement count exact | STEP 1 = 3 paragraphs for all three; «بكل الحب تهدى لـعبد الرحمن» produced by STEP 1 alone ✅ |
| Names whole inside one run | 3/3 occurrences per deck ✅ |
| Arabic text identical after PDF extraction (LibreOffice) | base characters equal **and** harakat multiset equal for all three decks, 4 pages each, Tajawal embedded ✅ |
| Upstream SlidePoise tests | green; every change tabled in §5 ✅ |
| Negative controls | text proof catches a missing word and a missing tanween; slot rule catches a dropped placeholder; integrity flags a name split across runs (and shows OM collapses its runs); a Latin-only subset font reports `.notdef`; payload coverage and wrong name are refused; glyph check flags rendered Arabic and passes clean treatments, gradients and random blobs ✅ |
| Visual inspection (skill maintenance rule 8) | `evidence/ar_girl_A5_libreoffice_sheet.png`, `evidence/ar_girl_A5_p1_libreoffice_zoom.png`: joined letters, tanween placed, RTL punctuation, name in place ✅ |

**Tests:** before this phase 378 pytest (367 upstream + 11 Studio) → after **425 pytest, 0 skipped, 0 failed** (upstream directory 369 = 367 + 1 net from the rewritten reference test + 1 new Remix test; Studio 56) + **18 node** tests. `py_compile` (all Python), `node --check` (all JS/MJS), `ruff --select E9,F63,F7,F82` clean; config and catalog preflights pass; boundary audit's only blocking fact is local `__pycache__` folders (gitignored, removed before commit).

## 4 · اكتشافات اتقاست · Measured findings that change how we work

1. **PptxGenJS 4.0.1** drops `type="pic"` from master placeholders, never emits a slide-level `<p:ph>`, and repeats `<a:pPr>` inside one paragraph when given several runs (invalid OOXML). All three are fixed in the lxml post-processor, opt-in, so upstream decks stay byte-identical.
2. **LibreOffice must never re-save a template**: a LibreOffice PPTX→PPTX round trip replaced every empty picture placeholder with a plain `<p:pic>` carrying LibreOffice's own stand-in image and no `<p:ph>` (slot map `{}`). Exporting to PDF is fine. Pinned by `test_libreoffice_resave_destroys_placeholders`.
3. **OM STEP 2 vs STEP 1:** an `extra` entry keyed on «…لإياد» never fires when the template stores the name literally, because STEP 1 already rewrote it (to «لمحمد»). The factory therefore writes «لـ<name>» so STEP 1 alone produces the operator's wanted «لـ{child_name}». STEP 2 *does* fire when the template stores a lam-alef ligature (U+FEF9) — proven both ways in tests; the Kit will dump the real templates' code points on device.
4. **PDF extraction moves harakat** («كثيرًا» → «كثيًر ا») and `pypdf` drops Arabic inter-word spaces; the text proof compares base characters + mark multiset, which extraction cannot legitimately change.
5. **Empty placeholders print blank** in the PDF — Phase 9's deterministic QA blocker «empty picture placeholder left» is required, not optional.
6. Amiri's Windows line box (1850 + 910 units) is far taller than its ink; Tajawal's is tight enough that fully vowelised text reaches the box at spacing 0.8 — the fitter takes the larger of box and ink automatically.

## 5 · الملفات اللي اتغيّرت في الأصل · Upstream files changed (tabled)

| File | Change | Why |
|---|---|---|
| `slidepoise/runtime/js/scene_to_pptx.mjs` | opt-in: `page.canvas_mm`, `style.direction`, `runs`, `picture_placeholder` | print pages, RTL, name runs, placeholders |
| `slidepoise/runtime/scripts/postprocess_pptx.py` | calls `print_fork_xml` only when a slide carries the new hints; layout pass for placeholders | same |
| `slidepoise/runtime/src/slidepoise/reconstruction/text_fit.py` | RTL copy measured by HarfBuzz (lazy import); Latin path unchanged | §6.1.1 |
| `slidepoise/scripts/fetch_remix_icon_pair.py`, 3 profiles, `framework/defaults/slidepoise-config.json`, `library-sets/catalog.json`, `slidepoise/schemas/reconstruction-handoff.example.json` | Remix Icon 4.9.0 → 4.8.0, licence Apache-2.0, 4.9+ refused | D10 / D13 |
| `profiles/pwc-public/` | **removed** (17 MB third-party documents, no licence) | D1 |
| `README.md`, `slidepoise/references/reference-retrieval.md` | say the collection is not redistributed | D1 |
| `slidepoise/SKILL.md` | +1 line routing to `references/print-arabic.md` | skill is the source of truth |
| `pyproject.toml` | `runtime` extra + `uharfbuzz`, `fonttools` | shaping |

**Tests changed (with reasons):** `tests/test_public_reference_bundle.py` rewritten to prove the same guarantees (portable, hash-verified references; retrieval honours `retrieval_eligible: false`) on a generated catalog, plus a test that the PwC profile is absent; `tests/test_distribution.py` three PwC assertions → one "PwC profile not in the wheel"; `tests/test_remix_icons.py` version 4.9.0 → 4.8.0 and one new refusal test. No test deleted.

**Not changed, and why:** the upstream reconstruction contract / `compile-scene` path does not yet know `picture_placeholder` or payloads; the Template Factory (Phase 3) is where Agent-authored pages get them. Historical example runs under `examples/` still mention the Remix Icon licence of the day they were recorded; they are recorded artefacts, not shipped configuration. The vendored contracts are untouched (sha256 re-checked).

## 6 · لسه مش متثبّت + إزاي · Unverified, and how

| Item | How it gets proven |
|---|---|
| PowerPoint keeps the placeholders/RTL/name runs and exports identically | On-Device Proof Runner (Phase 8a): open → save → `deck_picture_slots` + text proof; PowerPoint export via the vendored engine |
| The Console's own injection binds our placeholders in order | Kit probe + dry run on a copy (Phase 8a); order rule = `order` then document order, `idx` = 1000 + 20·slide + k |
| Windows CI (`mag-ci / windows`) | after Actions are enabled on the fork |
| Real templates' encoding of «لإياد» | Kit probe dumps code points |

## 7 · الخطوة الجاية · Next

Phase 2 — Studio shell (FastAPI on loopback, SQLite WAL worker, pywebview without `js_api`, Crossbar UI in Arabic RTL), providers with DPAPI keys and the free defaults of D13, AI budget guard, workspace, agent tool layer with confirmation tokens, PyInstaller one-folder build feeding the NSIS installer.
