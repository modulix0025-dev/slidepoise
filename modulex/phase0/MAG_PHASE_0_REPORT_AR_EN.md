# MAG_PHASE_0_REPORT — تقرير المرحلة 0 / Phase 0 report

Date: 2026-10-11 · Branch: `claude/zen-bohr-ih40bk` · Mode: **read-only** (no product code written)

## 1. الملخّص / Summary

**عربي:**
- المرحلة 0 خلصت جزئيًا.
- اللي خلص بالكامل: خريطة SlidePoise من الكود نفسه، والـbaseline بتاع اختباراته، وجرد الخطوط والتراخيص، ومسوّدة مصفوفة النطاق. كمان أداة قياس قوالب read-only عليها اختبارات.
- اللي متعملش: قراءة كود OM / Console / Store / MarketX، وقياس الـ20 قالب، والـgolden baseline. السبب إن الكود ده **مش موجود في الجلسة**، ولا على GitHub في الحسابات المتاحة. مفيش أي نتيجة من دول متألّفة.

**English:**
- Phase 0 is partly done.
- Done in full: the upstream map from code, the upstream test baseline, the font/licence inventory, and a draft scope matrix, plus a read-only template anatomy tool with known-answer tests.
- Not done: reading OM, Console, Store and MarketX, measuring the 20 templates, and the golden baseline. That code is **not in this session** and not in any GitHub repository the session can reach. No result for those items was fabricated.

## 2. التسليمات / Deliverables

| Item (brief §4 Phase 0) | File | Status |
|---|---|---|
| 1 Upstream map | `MAG_UPSTREAM_MAP.md` | ✅ done; 7 corrections to brief §3.1 (C1–C7) |
| 2 Read OM/CON/STO/MarketX | — | ⛔ blocked: no access |
| 3 Template anatomy | `tools/mag_template_anatomy.py` + tests | 🔧 tool ready and tested on synthetic decks; **real run pending the operator** |
| 4 Golden baseline | runbook §5 below | ⛔ blocked: needs OM + templates + Windows/PowerPoint |
| 5 Font & licence inventory | `MAG_FONT_LICENCE_INVENTORY.md` | ✅ for upstream; ⏳ presence on the operator PC |
| 6 Scope & Contract Matrix | `MAG_SCOPE_MATRIX_AR_EN.md` | 📝 draft; OM/CON/STO rows from the brief, marked ⏳ |

## 3. أهم الاكتشافات / Key findings (detail in the upstream map §0)

1. **C1, highest impact:** SlidePoise hard-codes the physical page width at 13.333 in in three places (`scene_to_pptx.mjs:771`, `scene.py:557`, `measure_visual_scene.py:177`). Portrait A5 today would come out about 34 × 48 cm. Fixing this is the core of Phase 1 patch 3.
2. **C2:** Pillow already shapes Arabic through libraqm when FriBiDi is loadable (measured 249 px shaped vs 350 px unshaped). On Windows that is not guaranteed, so HarfBuzz stays in the plan, plus a guard test.
3. **C3:** the "schemas" are example files, not JSON Schemas. M0–M5 schemas are written from scratch.
4. **C5:** per-character tracking breaks Arabic joining, so it is disabled for Arabic runs.
5. **C6:** 17 process launches and none hides its window, so all of them get wrapped.
6. **C7:** Remix Icon v4.9.0 uses "Remix Icon License v1.0", not Apache-2.0.
7. The upstream Console has no CSRF and checks only `Origin`. The Studio uses its own server.
8. Upstream CI already runs on `windows-latest`, which gives a real Windows test environment once Actions are enabled on the fork.

## 4. الاختبارات / Tests

| Suite | Env | Before | After | New |
|---|---|---|---|---|
| upstream `pytest` | Linux, Py 3.13.16 | 367 passed (366 + 1 env-fail without `build`) | 367 passed (unchanged; no upstream file touched) | 0 |
| upstream `npm test` | Node 22.22.0 | 18/18 | 18/18 | 0 |
| `modulex/phase0/tools/tests` | Linux, Py 3.13.16 | — | 2 passed | 2 |

- **Second environment (Windows): pending.** Only a Linux container was available.
- **Negative control:** in the anatomy test, slide 2 holds a *filled* picture placeholder (`p:pic`), which must count 0. A mutant that counts every `<p:ph type="pic">`, filled or not, makes `test_known_answers` fail (1 failed / 1 passed). The first mutant I tried did **not** fail, because it read the wrong element. That gap is closed by this second mutant.
- Changed tests: none. Deleted tests: none. Backups: none needed, because no pre-existing file changed.
- New files only:
  - `modulex/phase0/*.md`
  - `modulex/phase0/tools/mag_template_anatomy.py`
  - `modulex/phase0/tools/tests/test_mag_template_anatomy.py`

## 5. Runbook — للمشغّل على جهازه / for the operator on Windows

**A. Template anatomy (≈2 min):**
```bat
set PYTHONUTF8=1
pip install python-pptx lxml Pillow
python mag_template_anatomy.py --templates "C:\المشروع\OrderManagement\story_templates" --console-root "C:\المشروع\ModuleX_Console" --base-name "<base_name عربي>" --base-name "<base_name English>" --output MAG_TEMPLATE_ANATOMY.json
```
- Upload `MAG_TEMPLATE_ANATOMY.json`.
- When `--console-root` is given, slots are counted with the Console's own `deck_picture_slots`. Otherwise the report says `local_reimplementation_unverified`.
- Contact sheets are produced in Phase 0 completion with the Console's `pptx_to_pdf` once its code is readable.

**B. Golden baseline:** the exact script is written **after** `story_engine.py` is read, because `generate_story()` reads its registry from `app_settings` through `pg_kv`, and the DB/app context it needs is unknown here. What it will record:
- For one A4 and one A5 template of each story: the real `generate_story()` with a fixed child name, then the real PDF export.
- For each output: sha256, page count, extracted text, and replacement count.

**C. Fastest unblock:** push `OrderManagement`, `ModuleX_Console`, `ModuleX_Store` and `ModuleX_MarketX` as **private** repositories under `modulix0025-dev`, without `.env`, keys or customer data, and tell me. I'll attach them to the session and finish items 2–4, then update the matrix rows marked ⏳.

## 6. ما لم يُتحقق منه / Not verified (and why)

- Anything about OM / Console / Store / MarketX code (no access).
- Windows behaviour (Pillow FriBiDi DLL, DPAPI, PowerPoint COM, LibreOffice admin-less extraction), because there was no Windows host.
- Font presence and licence of `Blabeloo  MagdySoliman`, `Ubuntu Arabic` and `Calibri` on the operator PC.
- OFL font licences were recalled, not downloaded and read. That check happens in Phase 1 before bundling.

## 7. Gate 0

**STOP.** No product code until the operator writes «موافق» (or edits) on `MAG_SCOPE_MATRIX_AR_EN.md` **and** the access blocker (§5 C, or A plus the code) is resolved. Without the OM/Console code, the M1/M2 contracts and the Phase 3 validators cannot be derived from code, as standing rule 1 requires.
