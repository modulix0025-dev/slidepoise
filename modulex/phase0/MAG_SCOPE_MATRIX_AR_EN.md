# MAG_SCOPE_MATRIX — مصفوفة النطاق والعقود / Scope & Contract Matrix

**Status: DRAFT for operator approval (Gate 0 STOP).**

مهم: الملفات بتاعة OM والـConsole والـStore في الجدول ده مأخوذة من البريف §3، **مش من الكود**. السبب إن الكود ده مش متاح في الجلسة. لما يتقري، أي سطر هيختلف هيتصحّح هنا قبل أي كود.

Important: the OM/Console/Store file paths below come from brief §3, **not from code**, because that code is not available in this session. Every row marked ⏳ is re-checked against the real tree before Phase 1 starts. Rows about the SlidePoise fork were verified against the code (✅).

Systems: **STU** = ModuleX Magazine Studio (new), **FORK** = `vendor/slidepoise`, **OM** = OrderManagement, **CON** = Execution Console, **STO** = ModuleX Store.

## 1. Feature → owner → files → flag → contract → test → tier

| # | Feature | Owner | Files that change | Flag (default) | Contract | Test that proves it | Tier | Src |
|---|---|---|---|---|---|---|---|---|
| F1 | Shaping-correct AR text fit, bidi, fonts by family | FORK | `reconstruction/text_fit.py` (+ new `textshape.py`), `scene.py` (px→pt) | — (Studio only) | M4 source | known-answer widths vs HarfBuzz; a test fails if BASIC layout is used for Arabic; double-space family name preserved | P0 | ✅ |
| F2 | Portrait A4/A5 + bleed + safe zone + book furniture | FORK | `scene_to_pptx.mjs:771-774` (physical size input), `scene.py:557`, `measure_visual_scene.py:177`, `canvas.py`, `defineFrameMaster` (mirrored folios, folio off) | — | — | rendered A5 = 14.8×21.0 cm trim (+bleed canvas); sldSz EMU exact | P0 | ✅ |
| F3 | `<p:ph type="pic">` placeholders; `child_name` single run | FORK | new scene kind in `artifacts.py:114`, `scene_to_pptx.mjs`, `postprocess_pptx.py` | — | M1/M2 shape | Console's real `deck_picture_slots` = contract; OM's real `generate_story()` count > 0 and exact | P0 | ✅ fork / ⏳ OM+CON functions |
| F4 | Gendered + bilingual payloads | FORK | scene/semantic map data model | — | M1 | 4 payloads re-fitted independently, golden JSON | P0 | ✅ |
| F5 | Children's-book profiles | FORK | `profiles/modulex-*` (`profile.json` 2.0.0 + catalogs, CI preflight rules) | — | M3 (theme) | `preflight_catalogs.py` green | P0 | ✅ |
| F6 | Studio app, loopback server, worker, Crossbar skin | STU | new `ModuleX_MagazineStudio/` | — | M0 | non-loopback refused; CSRF; `CREATE_NO_WINDOW` asserted on every Popen; no `js_api=` grep | P0 | new |
| F7 | Any-provider LLM/image + manual mode; DPAPI keys | STU | `providers/*`, `secrets_dpapi.py` | — | — | DPAPI round-trip (Windows) / documented skip; secret never in a response (grep test) | P0 | new |
| F8 | Budget guard + spend dashboard | STU | `budget.py`, UI | — | — | ceiling refusal test, jsdom click | P0 | new |
| F9–F11 | Story Desk, Art Desk, Reconstruction review | STU (+FORK) | Studio UI and jobs | — | — | jsdom flows + fixture runs (no paid call in CI) | P0 | new |
| F12 | Variant Forge (A4↔A5 ×0.7071, gender, language, names) | STU | `forge.py` | — | M1/M2 | geometry known answers; names accepted by the real `resolve_variant()`/`template_resolver` | P0 | ⏳ resolver rules |
| F13 | Validators (real OM/CON functions + licence gate) | STU | `validators/*` (imports OM/CON functions **read-only, by path**) | — | — | each validator has a failing fixture (negative control) | P0 | ⏳ |
| F14 | Approval, signed publish, rollback | STU + OM + CON | `MAG_OM_APPLY.py`, `MAG_CONSOLE_APPLY.py`: loopback candidate endpoints/folders; activation through existing `story_engine.add_story()` / CON story-contract approval | `MODULEX_MAG_PUBLISH` (off) | **M0, M1, M2** | HMAC replay/forgery refusal; rollback byte-identical; `--revert` byte-identical | P0 | ⏳ |
| F15 | Themes as store options | STU + (STO or OM, owner TBD) | `MAG_STORE_APPLY.py` | `MODULEX_MAG_THEMES` (off) | **M3** | candidate import + operator confirm | P1 | ⏳ catalog owner |
| F16 | Dedication / أنا مين / certificate / QR / coloring / class magazine / bilingual | STU (templates); OM only for QR link resolution | template kinds; QR resolver behind a flag | `MODULEX_MAG_PAGE_KINDS` (off) | M1 | each kind passes F13 validators | P2 | ⏳ |
| F17 | Editor real text-fit + refusal before overflow | OM (P149-b) | `app/editor/deck.py` (call-out only), vendored `mx_textfit/` | `MODULEX_MAG_TEXTFIT` (off) | **M4** | long Arabic text refused; flag-off byte-identical | P1 | ⏳ |
| F18 | Safe-zone overlay + face-in-safe-zone warning | OM editor UI (OM or STO, TBD) | editor static UI + OpenCV face check (warning only) | `MODULEX_MAG_SAFEZONE` (off) | M4 | jsdom overlay + warning fixture | P1 | ⏳ UI location |
| F19 | Single-page live preview | OM | editor route + cache by content hash; `deck_pdf.py` **untouched** (frozen) | `MODULEX_MAG_PAGE_PREVIEW` (off) | — | preview = page N of full export (pixel diff tolerance) | P1 | ⏳ |
| F20 | «اعتماد البروفة للطباعة» bound to print job | OM | editor jobs + additive column/table; print portal display | `MODULEX_MAG_PROOF_APPROVAL` (off) | — | approve → job binds that sha; edit → new version needs new approval; sent-job rule unchanged | P1 | ⏳ |
| F21 | Preflight v2 | OM (library) | `app/printing/preflight.py` calls vendored `mx_preflight2/`; `print_service.py` **unchanged** | `MODULEX_MAG_PREFLIGHT2` (off) | **M5** | 1 good + 9 named bad PDFs | P1 | ⏳ |
| F22 | CMYK/PDF-X, crop marks, saddle-stitch | OM (library) + Ghostscript | vendored `mx_impose/` | `MODULEX_MAG_PRINT_DERIVATIVES` (off) | M5 | page-pairing known answers (16 A5 → 4 A4 sheets, both sides) | P2 | ⏳ GS licence |
| F23 | Visual QA gate | CON (`qc_agent.py`/`qc_store.py`) + OM print hold | additive blockers; AI advisory never changes state | `MODULEX_MAG_VISUAL_QA` (off) | — | each blocker injected → job held with reason; advisory → no state change | P1 | ⏳ |
| F24 | Flipbook, social carousel, institution decks | STU (+FORK as designed) | Studio outputs | — | — | consent flag enforced | P2 | new |
| F25 | Installer (online + offline), Doctor, direct link | STU build | `build/MagazineStudio.iss`, `.spec`, `.github/workflows/studio-release.yml`, `tests/windows_sandbox/*.wsb` | — | — | CI on `windows-latest` (upstream CI already has a Windows matrix ✅) | P0 | ⏳ MarketX precedent |
| F26 | Signed auto-update, R2 mirror, code-signing hook | STU | updater + `latest.json` Ed25519 | — | — | forged signature refused; rollback | P2 | new |

## 2. Contracts (M0–M5): proposed shape, to be derived from code

| ID | Carrier | Schema (published at `GET /internal/mag/v1/contract`) | Auth |
|---|---|---|---|
| M0 | every side with an endpoint | `{contract_version, schemas{}, key_ids[]}` plus `/health` | none for health; loopback only |
| M1 | Studio → OM candidate | `template_set{story_key, variants{A4:{ar,en},A5:{…}} per gender, files[{name, sha256, bytes}], registry{base_name, characters_count, extra_characters, figure_prompt_male/female, logo_config, display_names}}` | HMAC-SHA256 over the canonical JSON + timestamp + nonce; key from a shared secret file, never sent to a browser |
| M2 | Studio → Console candidate | `story_decks.json` entry plus slot map measured by `deck_picture_slots` plus deck sha256 | same |
| M3 | Studio → catalog owner | `theme/page_kind product{presentation, preview_images[], price_suggestion}` | same |
| M4 | library | `mx_textfit` API: `measure(text, font_family, size_pt, box_emu, rtl) → {lines, fits, shrink_to_pt}` | vendored, sha256 recorded |
| M5 | library | `mx_preflight2.check(pdf, spec) → [named findings]`; `mx_impose.saddle(pdf, sheet) → pdf` | vendored, sha256 recorded |

Every schema also ships frozen known-answer fixtures that run in both sides' suites.

## 3. ما لن يتغيّر / What will NOT change

- OM `generate_story()` (signature and output), `story_engine` registry writer (still `add_story()`/`update_story()` only), `template_resolver.py` logic.
- Console injection engine (`magazine_pptx.py`), `pptx_to_pdf.py`, story-contract human approval (`approvals.log.jsonl`).
- P149 token economy (`pricing.py`), the P149 kill switch (`MODULEX_P149=0` still wins over every MAG flag).
- P129 print-state ownership: `print_service.py` remains the only writer of `print_jobs` / `print_job_events` / `orders.fulfilment_status`.
- Frozen files: `OrderManagement/app/utils/config.py`, `modulex_pairing.py` (4 systems), `_willReload` in `ui-utils.js`, vendored `editor/deck_pdf.py`.
- Customer photos: no AI alteration (operator decision 2026-09-28).
- No SlidePoise/LLM/image call in the per-order path.
- Upstream SlidePoise behaviour for 16:9 decks. Phase 1 patches are additive: no `print` / `rtl` keys means today's output, proven by the upstream suite staying at 367 / 18.

## 4. أسئلة محتاجة قرار المشغّل / Decisions needed from the operator

1. **الوصول للكود (blocker):** OM و Console و Store و MarketX مش موجودين على GitHub في الحسابات المتاحة للجلسة. فيه طريقتين:
   - (أ) ترفعهم كـ repos خاصة وتضيفهم للجلسة؛
   - (ب) تشغّل `tools/mag_template_anatomy.py` وسكربت الـbaseline على جهازك (الخطوات في التقرير) وترفع النتايج.
2. **الخطوط:** هل `Blabeloo  MagdySoliman` عندك برخصة طباعة تجارية؟ وأي بديل OFL من §2 في جرد الخطوط تختار؟
3. **Ghostscript (AGPL):** نحمّله وقت التثبيت من المصدر الرسمي، ولا تشتري رخصة تجارية، ولا نأجّل CMYK/PDF-X؟
4. **Remix Icon License v1.0:** نستبعده من القوالب المطبوعة لحد ما تراجع الرخصة؟ (المقترح: أيوه.)
5. **رابط التحميل:** repo عام للـreleases بس، ولا Cloudflare R2 على دومينك؟
6. **الكتالوج والمحرّر:** أي نظام بيملك الكتالوج و `/api/editor/*` UI النهاردة (OM ولا Store)؟
