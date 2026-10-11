# MAG_PHASE_0_REPORT_AR_EN — المرحلة 0: الفهم والتحقّق والخطة · Phase 0: understand, verify, plan

> 2026-10-11 · branch `claude/adoring-mccarthy-zgg4ek` · tag `mag-phase-0` · **STOP — waiting for the operator's «موافق» on `MAG_PLAN_AR_EN.md`.**
> Deliverables: `MAG_COMPREHENSION_AR_EN.md` (30 checks answered) · `MAG_PLAN_AR_EN.md` (layout, flags, contracts M0–M7, tests, CI, decisions D1–D12) · this report · `evidence/` · `SHA256SUMS`.

## 1 · فحص البيئة · Environment probe

| Item | Result |
|---|---|
| Container | Ubuntu 24.04.5, 4 vCPU, 15 GB RAM, Python 3.13.16, Node 22.22.0 |
| LibreOffice | **24.2.7.2 already installed** (`/usr/bin/soffice`); Poppler `pdftoppm`/`pdftotext` present; no Ghostscript |
| PowerPoint | none (as expected) — every PowerPoint claim goes to the On-Device Proof Runner |
| github.com (git) / api.github.com / raw.githubusercontent.com | ✅ reachable |
| pypi.org / files.pythonhosted.org / registry.npmjs.org | ✅ reachable |
| api.iconify.design, openclipart.org, commons.wikimedia.org, kenney.nl, openmoji.org, download.documentfoundation.org, jrsoftware.org (Inno), ghostscript.com, Ghostscript GitHub release downloads | ❌ blocked by the proxy (403) — **not a product blocker**: the installed Studio calls them from Windows; tests use recorded cassettes; CI runners download Inno/LibreOffice directly |
| WebFetch to the blocked hosts | ❌ ENOTFOUND (tried by the licence agent) |
| GitHub Actions on `modulix0025-dev/slidepoise` | ⚠️ workflows exist (`ci.yml`, `release.yml`) but **0 runs ever** — on a fork, Actions stay disabled until the owner enables them (repo → *Actions* tab → "I understand… enable"). The push of this phase will show whether runs start. |
| Push rights to the branch | ✅ (this report was pushed) |

## 2 · التحقّق من الأصل · Upstream verification

- Repository HEAD = `4250ba14d5d673a3215e7707b5d52f67cdf1154e`; `git ls-remote https://github.com/henryhyw/slidepoise` → `HEAD` and `refs/heads/main` are the **same commit today** (no upstream drift). Version 0.8.2, MIT.
- §5 facts confirmed in code: `text_fit.py` `FONT_PATHS` is Latin-only (Arial/Liberation/DejaVu), no RTL/bidi/Arabic/HarfBuzz anywhere in the runtime; `scene_to_pptx.mjs` uses `pptx.defineLayout({name:"SLIDEPOISE_CUSTOM"…})` and never emits picture placeholders; runtime CLI has `measure, build-contract, compile-scene, reconstruct-slide, render-pptx, render-deck, bundle-deck, verify-bundle, render-preview, render-deck-preview, audit-text`; `profiles/pwc-public/` ships 17 MB of PwC/Strategy& material with an explicit "no licence asserted" NOTICE (removal = plan D1; two upstream tests reference it).
- PptxGenJS **4.0.1** (installed) supports `rtlMode` (`rtl="1"`) and `lang` on runs — fewer XML post-processing steps than the brief assumed; picture placeholders still need lxml post-processing.
- **Baseline tests on this container:** upstream pytest **367 passed**, `npm test` **18 passed**, 0 failures, 0 skips.

## 3 · العقود المنسوخة حرفيًا · Verbatim contracts

| File | Expected sha256 (brief) | Measured | Self-test |
|---|---|---|---|
| `vendor/modulex/modulex_signing.py` | `a2f1db60…347e` | **identical** | `--selftest`: register, assign, heartbeat, drain, health → **5/5 PASS**, exit 0 |
| `vendor/modulex/pptx_to_pdf.py` | `2920eb32…7eee` | **identical** | used for the LibreOffice test below |

The brief's extraction rule (text between fences, LF, no extra trailing newline) reproduced both hashes on the first write. New suite `tests/mag/test_vendor_contracts.py` (7 tests) pins both hashes and `vendor/modulex/SHA256SUMS`, runs the vectors, verify + `ReplayGuard`, the image-only refusal of `pdf_stats`, and a **negative control** (a one-character mutation of `canonical_string` must change the hash and fail all five vectors).

## 4 · تصدير عربي عبر LibreOffice · Arabic export through LibreOffice (vendored `convert()`)

A synthetic 3-slide A5 (14.8×21.0 cm) deck with an RTL Arabic paragraph containing «إياد», saved under an **Arabic filename** (`عينة_A5.pptx`), converted by the vendored `pptx_to_pdf.convert(..., expect_pages=3)`:

- `probe()` → `{"ok": true, "engine": "soffice"}` (PowerPoint dropped off-Windows, as designed).
- Result → engine `soffice`, **3 pages, 4 font objects, has_text = true**; MediaBox **148.0 × 210.0 mm**.
- Findings that shape Phase 1:
  1. With no Arabic font installed, LibreOffice embedded **FreeSerif/FreeSans** (honest substitution) → CI must install the vault fonts before export proofs.
  2. `pypdf.extract_text()` **dropped the spaces between Arabic words** («كانياماكان…») while `pdftotext` kept them (wrapped in bidi marks U+202A/U+202B/U+202C). Text-equality proofs will use `pdftotext`, strip bidi controls, and compare NFC.

## 5 · مكتبة الخطوط — إعادة القياس · Font catalog re-measured at google/fonts @ `bd8f81dd`

Sparse checkout of exactly the 214 `repo_dir`s (+ `ofl/chakrapetch` for the UI). Script: `tools/phase0/measure_font_catalog.py`; full per-file output (sha256, fsType, axes, colour tables, coverage, GPOS, notdef): `evidence/font_catalog_measured.json`; Appendix F transcribed to `docs/mag/catalog/fonts_appendix_f.tsv`.

| Fact | Brief | Measured |
|---|---|---|
| Families (AR / EN) | 214 (54 / 160) | **214 (54 / 160)** |
| Files / size | 311 ≈ 75.5 MB | **311 / 75,491,712 B (75.5 MB)** |
| Colour (quarantined) | 8 | **8** — Cairo Play, Reem Kufi Fun, Blaka Ink, Reem Kufi Ink, Aref Ruqaa Ink, Bungee Spice, Honk, Nabla |
| Print candidates | 206 | **206** |
| Families with variable files | 47 | **47** |
| OFL / Apache-2.0 | 197 / 17 | **197 / 17** |
| Families declaring RFN | 83 | **83** (per-family flags match Appendix F exactly) |
| Non-zero fsType | Frijole = 8 | **Frijole = 8** only |
| Arabic: GPOS `mark` | 54 | **54** |
| Arabic: missing `mkmk` | Thabit, Ruwudu, Alkalami | **Alkalami, Ruwudu, Thabit** |
| Arabic: «يُوسُف مَرْيَم لا» zero `.notdef` | 54 | **54** |
| Arabic: 36 base letters + 8 harakat + Arabic-Indic digits + `، ؛ ؟ ـ` | 54 | **50 — DRIFT** |

**Drift (the only one):** **Blaka, Blaka Hollow, Blaka Ink, Gulzar lack U+0640 ـ (tatweel/kashida)**; every other coverage item is complete in all 54. Consequence: those four may not be used for the «لـ{name}» dedication form or kashida justification (plan D5). Other observations: RFN lists are not always the family's own name (Reem Kufi → "Josefin Sans"; Readex Pro → "RevReading Lexend"; Andika → "Andika", "SIL"), so renaming checks use the declared list. Pending for Phase 4 (not measured here): harakat collision test, Zain digit forms, render tests of colour fonts, deterministic static builds.

## 6 · التراخيص · Licence verification of shape sources and bundled tools

Full table with commits: `evidence/licence_verification_2026-10-11.md`. Summary:

- **PRINT_OK (primary source read):** Fluent Emoji (MIT), Noto Emoji SVGs (Apache-2.0 — licence moved to `2D/svg/LICENSE`), Tabler (MIT), Phosphor (MIT), Lucide (ISC + MIT for Feather-derived), Kenney (CC0 — check each pack's License.txt), Remix Icon **only ≤ v4.8.0**.
- **PRINT_OK_WITH_CREDITS:** Twemoji graphics (CC-BY-4.0 — npm says MIT, which covers only code), Wikimedia files whose `extmetadata` licence is allowlisted and `Restrictions`/`NonFree` empty.
- **Iconify:** licence is per set (`license.spdx` on all 240): 168 sets OK, 52 OK with credits, 17 refused (BY-SA, GPL, NC), 3 need your decision (D9). Brand-mark sets (`simple-icons`, `logos`) excluded despite CC0.
- **REFUSE for print:** OpenMoji (CC-BY-SA-4.0, screen only), Remix Icon ≥ 4.9.0 (new custom licence forbids libraries), SVG Repo (no machine-readable per-asset licence), unDraw (per secondary quotes forbids packs/competing services).
- **UNVERIFIED (sites unreachable; secondary sources not accepted):** Openclipart, Open Peeps, Iconify API terms page, unDraw primary text — disabled until re-checked from Windows (D12).
- **Bundling:** Ghostscript is AGPL → not bundled (D8); python-bidi is LGPL-3.0 → one-folder build (D11); Poppler GPL → prefer pypdfium2 (D11); LibreOffice MSI redistributable unmodified (MPL-2.0); Inno Setup permissive (commercial licence *requested*).

## 7 · اللوجو · Logo (Appendix H) — not reproduced, honestly

I re-typed the 11 KB base64 from the brief and decoded it: the PNG header and size (256×256, grayscale) were right, but the zlib stream was corrupt and the sha256 was `2444c71e…`, **not** `c0232b98…`. Retyping that much binary text by hand is not reliable, so I deleted the file. Nothing derived from it was committed. Plan D4 says what happens next: a labelled vector placeholder, and a branding setting that accepts the real PNG only when its sha256 matches.

## 8 · اتغيّر إيه · What changed

| Path | What |
|---|---|
| `vendor/modulex/modulex_signing.py`, `pptx_to_pdf.py`, `SHA256SUMS` | operator contracts, byte-identical |
| `tests/mag/test_vendor_contracts.py` | 7 new tests incl. negative control |
| `tools/phase0/measure_font_catalog.py` | evidence script (fontTools + HarfBuzz) |
| `docs/mag/catalog/fonts_appendix_f.tsv` | Appendix F as data |
| `docs/mag/phase-0/*` | comprehension, plan, this report, evidence, SHA256SUMS |

**Tests:** before 367 pytest + 18 node → after **374 pytest** (367 + 7 new) + 18 node, all green; no existing test changed or deleted; `py_compile` and `ruff --select E9,F63,F7,F82` clean on new files.

**What did NOT change, and why:** no file in `slidepoise/`, `framework/`, `webapp/`, `profiles/` or the upstream tests changed, because Phase 0 contains no product code. `pwc-public` is still present (its removal is D1, waiting for your approval). The CI workflows are untouched; `mag-ci.yml` comes in Phase 1/2.

## 9 · لسه مش متثبّت + إزاي يتثبت · Unverified, and how it gets verified

| Item | How |
|---|---|
| Windows CI (DPAPI, installer, `CREATE_NO_WINDOW`) | after Actions are enabled on the fork (D2) — `mag-ci / windows` |
| PowerPoint behaviour of everything | On-Device Proof Runner (Phase 8a), signed proof report |
| Real templates' encoding of «لإياد», live `base_name`s, real anchors | Kit probe on device |
| Openclipart / Open Peeps / unDraw / Iconify API terms | Studio licence probe from Windows, or a human with a browser |
| Logo PNG | D4 |
| pypdfium2 licence | Phase 2 |

## 10 · STOP

Please reply **«موافق»** (or edit any of D1–D12 in `MAG_PLAN_AR_EN.md`). This is plan approval only; nothing about your systems is being asked.
