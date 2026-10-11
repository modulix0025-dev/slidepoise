# MAG_PLAN_AR_EN — خطة التنفيذ · Execution plan

> **APPROVED by the operator on 2026-10-11 («موافق») with one change: no commercially-licensed component (D13, R1–R8).**
> Phase 0 deliverable · 2026-10-11 · waiting for the operator's «موافق» (plan approval only — no information is requested).
> Facts behind this plan: `MAG_COMPREHENSION_AR_EN.md`, `MAG_PHASE_0_REPORT_AR_EN.md` (environment probe, verifications, licence table).

---

## 0 · الملخّص في سطور · Summary

**AR:** هنبني «ModuleX Magazine Studio» جوه نفس الريبو ده (fork من SlidePoise على commit `4250ba14`)، كباكدج جديدة `mxstudio/` جنب الـskill الأصلي. التعديلات على SlidePoise نفسها (عربي/RTL، طباعة، placeholders، name token) بتتعمل جوه `slidepoise/` ومتسجّلة في جدول patch مقابل الأصل. المكتبات اللي هتروح لأنظمة المشغّل (textfit / preflight2 / impose / fontcheck) نقية ومنفصلة في `mxlibs/`. أي حاجة على جهاز المشغّل بيعملها الـIntegration Kit بعد تحقّق. الـCI هيشتغل Linux + Windows، والـinstaller بيتبني على `windows-latest`.

**EN:** Build the Studio in this repository (SlidePoise fork pinned at `4250ba14`) as a new `mxstudio/` package beside the skill; fork patches (Arabic/RTL, print geometry, placeholders, name token) live in `slidepoise/` and are tabled against upstream; operator-bound pure libraries live in `mxlibs/`; anything on the operator's PC is done by the Kit after verification; CI on Linux + Windows; installers built on `windows-latest`.

## 1 · شكل الريبو · Repository layout

```
slidepoise/                      forked skill (SKILL.md, references, runtime) — Arabic/print patches, tabled
  runtime/src/slidepoise/arabic/ shaping (uharfbuzz+fontTools), bidi, line breaking, harakat line height
  runtime/src/slidepoise/print/  trim/bleed/safe-zone geometry, folios, mirrored pages
  runtime/scripts/postprocess_pptx.py  + rtl/cs/lang, picture placeholders, single-run name token
mxstudio/                        the Studio application (Python)
  app/            FastAPI on 127.0.0.1 (random port + lockfile, CSRF on mutations)
  worker/         SQLite WAL job queue (leases, idempotency, restart-safe)
  shell/          pywebview window (NO js_api), single-instance guard, CREATE_NO_WINDOW helpers
  ui/             Arabic-RTL Crossbar UI (vanilla JS, jsdom tests)
  providers/      text/vision + image providers, DPAPI key store, budget guard
  workspace/      content-addressed store, versions, diff/restore
  agent/          tool registry (JSON Schema), confirmation tokens, planner loop, audit log, manual/skills
  factory/        Story Desk, Art Desk, Reconstruction bridge, Variant Forge, Publish (M1/M2 candidates + packs)
  validators/     ports of replace_in_paragraph/replace_in_shape, deck_picture_slots, export proof, fit, licence, fonts
  fonts/          catalog DB, fetch/verify, Office-safe builds, QA, install/sync (M6), typography & type themes
  shapes/         presets/warps, procedural generators, SVG<->custGeom, sanitiser, discovery (licence-gated)
  colour/         OKLCH harmonies, palette extraction, contrast over art, CMYK/ICC, CVD sim, critic + taste memory
  kit/            discover, anchors, probe, patches (+revert), proof runner, device report
  doctor/         environment checks with «إصلاح» actions
mxlibs/                          pure, stdlib/numpy-light libraries shipped to the operator's systems (M4/M5)
  mx_textfit/  mx_preflight2/  mx_impose/  mx_fontcheck/      each with known-answer tests + sha256 manifest
vendor/modulex/                  byte-identical pptx_to_pdf.py + modulex_signing.py (+ SHA256SUMS)
mxstudio/vendor_wrappers/        deck_pdf_wrapper.py — the two marked changes (CREATE_NO_WINDOW, quit-only-if-idle) as a wrapper
contracts/mag/v1/                JSON Schemas M0–M7 + frozen known-answer fixtures (both sides run them)
catalog/                         fonts (Appendix F TSV + measured JSON), shapes, palettes, type themes, licence ledgers
evals/                           ≥300 agent scenarios + graders (safety / task), recorded cassettes
installer/                       PyInstaller spec, NSIS script (MarketX conventions, Arabic.nlf), .wsb, runbooks
tests/mag/                       new suites; tests/mag/replicas/ = synthetic operator trees generated from Appendix B
docs/mag/                        phase reports, plan, handoff, runbooks
.github/workflows/mag-ci.yml     Linux + Windows matrix for the Studio; mag-release.yml for installers
```

Upstream `tests/`, `framework/`, `webapp/` stay and keep running (baseline: **367 pytest + 18 node tests green** on this container).

## 2 · قرارات تحتاج موافقة المشغّل · Decisions inside this plan (approve or edit)

| # | Decision | Default I will take |
|---|---|---|
| D1 | Remove `profiles/pwc-public/` (17 MB of third-party PwC/Strategy& PDFs, no licence) from the fork as §5 requires. Two upstream tests depend on it (`tests/test_public_reference_bundle.py`, `tests/test_distribution.py`). | Remove in Phase 1; change those two tests to assert the profile is **absent** (tabled with reasons, totals reported). Wikimedia scripts stay, behind the licence gate. |
| D2 | GitHub Actions on this fork: **0 runs so far** (forks have Actions disabled until the owner enables them in the repo's *Actions* tab). | I push and check; if still no runs, enabling Actions is a one-click operator action. Until then I run the Linux suite here and deliver the Windows workflow + runbook. |
| D3 | Where installers are published. The direct link must be public. | **GitHub Releases only** (free; R2 dropped — R7). If the source repo becomes private: a public releases-only repo `modulix0025-dev/magazine-studio-releases`. Stable link: `…/releases/latest/download/ModuleX-MagazineStudio-Setup.exe`. |
| D4 | Logo PNG (Appendix H). My transcription of the base64 in this session did **not** reproduce the sha256 `c0232b98…` (corrupt stream) — I will not ship a guessed logo. | Phase 2 uses a vector placeholder X-on-white-disc clearly labelled as such; the real PNG is accepted by a branding setting that verifies `c0232b98…`; a later session can retry the decode in small verified chunks, or the operator commits `assets/logo-mark-256.png`. |
| D5 | Tatweel: Blaka, Blaka Hollow, Blaka Ink, Gulzar **lack U+0640** (measured). | Those four never get kashida justification and never render the «لـ» dedication form; the typography system enforces it. |
| D6 | Template naming for new stories. | `<story_key>_<ar|en>_<boy|girl>_<A4|A5>.pptx` (ASCII key, e.g. `moon_trip_ar_girl_A5.pptx`) registered by exact name; old files untouched. |
| D7 | Flags naming. | Studio: `MXS_*`. Operator-side hooks: `MODULEX_MAG_*`, all default **0**. |
| D8 | ~~Ghostscript~~ → **replaced (R1)**: pikepdf (MPL-2.0) + LittleCMS/Pillow + pypdfium2 + colord FOGRA39L/GRACoL profiles (CC0). | Approved by operator 2026-10-11: no commercially-licensed component. |
| D9 | Iconify sets licensed **Unlicense** (1), **CC-BY-3.0** (1, `game-icons`), **MPL-2.0** (1, `circum`) are not on the brief's allowlist as written. | Refused for print until you decide; my recommendation: allow Unlicense (public-domain dedication) and CC-BY-3.0 with credits; keep MPL-2.0 refused. |
| D10 | Remix Icon switched to a restrictive custom licence in v4.9.0 (2026-01-27). | Pin Remix ≤ 4.8.0 (Apache-2.0); refuse 4.9+. Upstream SlidePoise's `fetch_remix_icon_pair.py` gets a version pin + licence check in Phase 1. |
| D11 | Rasteriser and bidi | **pypdfium2** (BSD-3/Apache-2.0) for previews; python-bidi (LGPL-3.0) in the one-folder build, replaceable (R8). |
| D12 | Openclipart, Open Peeps, unDraw, SVG Repo terms could not be read from primary sources in the cloud. | Disabled by default; the Studio's licence probe re-reads them from Windows (or a human checks in a browser) before any is enabled. unDraw and SVG Repo default to refused. |
| D13 | **No commercially-licensed component anywhere** (operator, 2026-10-11) | Inno Setup → **NSIS** (R2) · paid code-signing → none + SHA256 + Ed25519 (R3) · paid search APIs → **Openverse + Wikimedia + Iconify** (R4) · non-commercial model weights (FLUX.1 [dev]/Kontext [dev]) → **Qwen-Image / Qwen-Image-Edit-2511 / FLUX.1 [schnell]** (R5) · default agent model → **Qwen3-VL** via an OpenAI-compatible endpoint; paid APIs optional and off by default (R6). Full evidence: `docs/mag/decisions/FREE_ALTERNATIVES_AR_EN.md`. |

## 3 · الفلاجات · Flags (all operator-side flags default OFF)

| Flag | Where | Effect when `1` |
|---|---|---|
| `MODULEX_MAG_TEXTFIT` | OM editor | measure each text edit with `mx_textfit`; refuse non-fitting text before export |
| `MODULEX_MAG_SAFEZONE` | OM editor UI | safe-zone/bleed overlay + face-outside-safe-zone warning |
| `MODULEX_MAG_PAGE_PREVIEW` | OM editor | single-slide preview export, cached by content hash |
| `MODULEX_MAG_PROOF_APPROVAL` | OM editor + print portal | customer soft-proof approval bound to the print job |
| `MODULEX_MAG_PREFLIGHT2` | OM `printing/preflight.py` | call `mx_preflight2` (bleed, fonts embedded, effective DPI, safe band) |
| `MODULEX_MAG_IMPOSE` | OM printing | imposition / crop marks / CMYK derivative (derived artefacts linked by sha) |
| `MODULEX_MAG_FONTCHECK` | Console export | deck font validator before `convert()` (refuse by name) |
| `MODULEX_MAG_RECEIVERS` | OM / Console / Store | mount M1/M2/M3/M6/M7 receiver routers (between marker comments) |
| `MODULEX_MAG_QA_GATE` | Console/OM | deterministic QA blockers hold the print job (named reason) |
| `MXS_AGENT_MODE` | Studio | `full` / `suggest_only` (forced when model qualification fails) |
| `MXS_OFFLINE` | Studio | no network calls; cassettes/local only |

## 4 · العقود · Contracts M0–M7 (shapes; full JSON Schemas + fixtures in Phase 2/3)

All HTTP contracts are signed with the vendored `modulex_signing` (+ `check_replay`). Every payload carries `contract: "mag/v1/<id>"`, `schema_version`, `produced_by: {app, version, git_sha}`, `created_at`, and sha256 of every file.

- **M0** `GET /internal/mag/v1/contract` → `{version, schemas: {id: url}, key_ids, fixtures_sha256}`; `GET /internal/mag/v1/health`.
- **M1** template-set candidate → OM: `{story_key, display_name, variants: {A4|A5: {ar|en: {male|female: {file, sha256, base_name}}}}, characters_count, extra_characters, figure_prompt_male/female, logo_config, replacements_additions, validator_report_sha256}`. OM side stores it as **candidate**; activation = operator confirm → `story_engine.add_story()` / `update_story()`; rollback = previous registry entry + previous files byte-identical.
- **M2** deck-contract candidate → Console: `{story_key, display_name, reference, variants: {boy_a4…: file}, slot_map: {variant: {slide: n}}, measured_with: "deck_picture_slots@sha"}` → Console's existing human approval writes the story contract; the Studio never writes `approvals.log.jsonl`.
- **M3** theme / page-kind product → Store: `{product_key, kind, title_ar/en, previews[], suggested_price_tokens, requires_story_keys[]}`.
- **M4** `mx_textfit.fit(text, box_emu, font_spec, rules) -> {fits, size_pt, lines, overflow_px, font_used, substitute}` (pure).
- **M5** `mx_preflight2.run(pdf, profile) -> {ok, checks[], warnings[]}`; `mx_impose.saddle(pdf, sheet, creep_mm) -> pdf` (pure).
- **M6** font-set sync: `{set_id, fonts: [{file, sha256, install_names, roles}]}` → receiver acks `{installed: [{file, windows_reported_name, scope: user|machine}], account}`.
- **M7** customer font choices: `{story_key, roles: {child_name|dedication: [{font_id, display_name_ar, preview_url, price_tokens}]}}`.

Pack fallback: `mag-pack-<id>.zip` = files + `manifest.json` + `manifest.sig` (detached HMAC with the shared secret via `modulex_signing.signature()` over `POST /pack/<id>` and the manifest bytes), imported by the Kit through the receiver's own code path.

## 5 · استراتيجية الاختبار · Test strategy

- **Known-answer tests** for every contract and pure library (signing vectors, `deck_picture_slots` counts, replacement counts, preflight fixtures: 1 good + 9 named bad PDFs, colour reference values).
- **Ports with parity tests**: `replace_in_paragraph`/`replace_in_shape` and `deck_picture_slots` are copied from Appendix B verbatim into `mxstudio/validators/operator_ports.py` with sha256 of the excerpt; parity tests feed the same decks to both.
- **Synthetic replicas** of the operator's trees (`tests/mag/replicas/`) generated from Appendix B (anchors, signatures, constants, verbatim excerpts) — the Kit is tested against correct replicas (patch applies, revert byte-identical) and mutated ones (refuse + report).
- **Negative controls** in every suite (a deliberately wrong input that must fail), never deleted.
- **Cassettes** (VCR-style) for all web/API calls; live calls only on the operator's machine.
- **Export proofs**: LibreOffice in cloud/CI (fonts installed from the vault so text extraction is meaningful; text compared with `pdftotext` + bidi-mark stripping + NFC — measured here: `pypdf` drops Arabic inter-word spaces); PowerPoint proofs queued for the On-Device Proof Runner.
- **UI**: jsdom suites click every control; Playwright (preinstalled Chromium) for visual smoke.
- **Static gates**: `py_compile` all Python, `node --check` all JS/MJS, ruff, a grep test forbidding `js_api=`, a test asserting `CREATE_NO_WINDOW` on every child-process helper, ASCII-only `.bat`/`.cmd`, secret scan on artefacts.
- **Agent evals**: ≥300 scenarios, graders = the validators; 100 % safety, ≥95 % tasks; model qualification subset.

## 6 · مصفوفة الـCI · CI matrix

| Job | Runner | What |
|---|---|---|
| upstream `ci.yml` | ubuntu/macos/windows × py3.10/3.12 | unchanged upstream suites (kept green) |
| `mag-ci / linux` | ubuntu-latest, py3.10 + 3.12 | all Studio suites, LibreOffice export proofs, font QA (vault from pinned commit, cached) |
| `mag-ci / installer` | ubuntu-latest | `apt install nsis` → `makensis` builds the Windows installer from the PyInstaller artefact |
| `mag-ci / windows` | windows-latest, py3.12 | Studio suites, DPAPI, `CREATE_NO_WINDOW`, Arabic-path round-trip, PyInstaller build, **silent install (`/S`) of the NSIS installer + Doctor + uninstall** |
| `mag-release` | windows-latest (tag) | both flavours, SHA256SUMS, SBOM, licence report, signed `latest.json` (Ed25519 key from CI secret) |

## 7 · المراحل والبوابات · Phases, tiers and gates

Order = brief §7 (P0 tier first). Each phase ends with `MAG_PHASE_N_REPORT_AR_EN.md`, SHA256SUMS, tag `mag-phase-N`, CI evidence.

| Phase | Main outputs | Gate evidence |
|---|---|---|
| 1 Fork & Arabic engine | shaping/bidi/line-break; RTL PPTX; trim+bleed+safe; `picture_placeholder`; single-run name token + prefix forms; gendered/bilingual payloads; kids' profiles; no-Arabic-in-art validator | 3 synthetic pages (Appendix A anatomy) → LibreOffice PDF text identical; ported slot/replace counts exact; upstream table; negative controls |
| 2 Shell + agent foundation + basic installer | server, worker, window, Crossbar UI, providers/DPAPI/budget, workspace, tool layer + tokens, NSIS basic | Linux+Windows CI; loopback-only; DPAPI on Windows; jsdom; `CREATE_NO_WINDOW`; silent install in CI |
| 3 Template Factory | Story/Art/Reconstruction/Variant Forge/Validators/Publish | one new story → all 8 variants, all validators green; PowerPoint proof queued |
| 4a/b/c Fonts | catalog DB, builds, QA, ledger, install/sync, validator; typography + ≥30 type themes; customer choice, name art, specimen book | drift empty; deterministic builds; QA status ×214; validator negative control |
| 5 Shapes | presets/warps, generators, canvas, SVG↔custGeom, sanitiser, discovery, library mgmt | enumeration vs spec; determinism; IoU ≥ 0.99 on 50 shapes; sanitiser fuzz; licence negatives |
| 6 Colour & taste | OKLCH, extraction, contrast over art, CMYK/ICC, CVD, ≥80 palettes, critic + taste memory | known-answer colour tests; neon fixture; pairwise consistency ≥ 90 % |
| 7 Themes & products | dedication, «أنا مين», certificate, QR back, coloring, class magazine, bilingual | each kind passes factory validators |
| 8 Kit + device patches | discover/anchors/probe/proofs/report; editor fit/safe-zone/preview/approval; preflight v2; receivers/packs; imposition/CMYK/crop | replicas apply/revert byte-identical; mutated anchor refused; flags-off identical; 1+9 preflight fixtures |
| 9 QA gate | deterministic blockers + advisory AI | each blocker holds the job; advisory never changes state |
| 10 Agent evals | manual, skills, ≥300 evals, qualification | thresholds in CI on ≥2 models (or 1 + recorded transcripts — stated) |
| 11 Marketing | flipbook, carousels (consent flag), institution decks | — |
| 12 Release | both flavours, direct link, update/rollback, signing hook, Sandbox runbook | windows-latest install → Doctor → build → export → uninstall |
| 13 Handoff | `MAG_HANDOFF_AR_EN.md`, SBOM, licence report | final tag |

## 8 · يتثبت فين · Cloud-provable vs device-provable

| Claim | Cloud/CI | Device (Proof Runner) |
|---|---|---|
| Contracts byte-identical, vectors pass | ✅ proved in Phase 0 | re-hash on device; differing hash ⇒ report |
| Arabic shaping & fit | ✅ with vault fonts | ✅ with PowerPoint metrics |
| Placeholders/name token survive | ✅ LibreOffice round-trip | ✅ PowerPoint open/save/export |
| PDF text proof | ✅ LibreOffice | ✅ PowerPoint (the production engine) |
| Colour fonts usable in print | ❌ | ✅ only path |
| Font visible to the export account | ❌ | ✅ |
| Kit anchors/patch/revert | ✅ on replicas | ✅ on real trees (operator click) |
| Installer per-user install / LibreOffice admin-extract | ✅ windows-latest runner | ✅ standard-user account |
| Agent evals | ✅ (keys or transcripts) | ✅ model qualification on install |

## 9 · المخاطر · Risks and mitigations

| Risk | Mitigation |
|---|---|
| PowerPoint renders Arabic/harakat differently from HarfBuzz metrics | fit with safety margin; per-font min line height from the collision test; device proof per type theme before it is offered |
| Picture placeholders lost on PowerPoint save | XML post-process + device round-trip proof; Console slot count compared after round-trip |
| Actions disabled on the fork | D2: one-click enable; meanwhile Linux here + scripts/runbook |
| Hosts blocked in the cloud (Iconify, Openclipart, Wikimedia, Openverse, LibreOffice downloads) | product calls them from Windows at run time; cassettes in tests; CI runners download LibreOffice directly; NSIS comes from Ubuntu apt |
| CMYK derivative without Ghostscript | pikepdf + LittleCMS rewrite; pages with shadings/transparency rasterised at 600 dpi by pypdfium2 and flagged; described as "CMYK print derivative", never as certified PDF/X |
| LibreOffice MSI admin extraction needs no admin? | proved on `windows-latest` standard user + Sandbox runbook; else per-machine with Arabic UAC explanation |
| Per-user fonts invisible to a service account | Kit detects the account; machine-wide install with consent |
| Logo not reproducible from text | D4 |
| Agent "never errs" expectation | stated honestly: mistakes cannot reach a customer or printer (validators, tokens, evals), not that the model is infallible |

## 10 · أول خطوة بعد الموافقة · First step after «موافق»

Phase 1: create `slidepoise/runtime/src/slidepoise/arabic/`, install vault fonts into the test environment, port Appendix B excerpts into `mxstudio/validators/operator_ports.py` with parity tests, add `mag-ci.yml`, remove `pwc-public` (D1), and build the three synthetic Appendix-A pages.
