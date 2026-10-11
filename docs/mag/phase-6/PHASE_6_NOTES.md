# PHASE_6_NOTES — المرحلة 6: علم الألوان والذوق · Phase 6: colour science & taste

> 2026-10-11 · owner paths: `mxstudio/colour/`, `tests/mag/colour/`, `catalog/palettes/`, `docs/mag/phase-6/` · no shared file edited.

## 1 · الخلاصة · Summary

**AR:** بقى عندنا طبقة ألوان كاملة بتقيس وما بتحكمش: OKLCH/OKLab (مرجعها coloraide)، هارمونيات بلفّ الـhue مع تثبيت الفاتح/الغامق والتشبّع، استخراج باليتة من الرسمة المقبولة (k-means موزون بالمساحة في OKLab، والبشرة والألوان المحايدة كل واحدة لوحدها)، أدوار ثابتة للمجلة كلها (خلفية، أساسي، ثانوي، لمسة، كلام، حدود)، قياس القراءة على البكسلات الحقيقية تحت كل مربع كلام (WCAG 2.x و APCA وكمان مقياس للزحمة) ولو مش مقروء بيقترح معالجة (حدّ/ظل، طبقة شفافة، سحابة) **من غير ما يلمس الرسمة**، أمان الطباعة بـICC (FOGRA39 أو GRACoL، والمشغّل يختار) مع تحذير ΔE2000 وحد الحبر وإرشاد الأسود الغني، محاكاة عمى الألوان (Machado 2009)، 90 باليتة للأطفال متراجعة كلها، وناقد ذوق بيقارن اتنين اتنين بأكتر من حكم وبيشرح أسبابه **ومابيقفلش على ذوق ومابينشرش لوحده**، وذاكرة ذوق بتتعلّم من موافقة/رفض المشغّل وبتطلّع نسبة الاتفاق مع الوقت.

**EN:** A complete measuring (not judging) colour layer: OKLCH/OKLab with coloraide as reference; harmonies by OKLCH hue rotation at controlled L/C; palette extraction from accepted art (area-weighted OKLab k-means with skin and near-neutrals separated); deck-level roles; readability measured on the actual pixels under each text box (WCAG 2.x, APCA, busy-ness) with an automatically proposed — and simulated — treatment that never alters the art; ICC print safety (FOGRA39 default, GRACoL or any operator CMYK profile) with ΔE2000 warnings, ink-limit blocking and rich-black guidance; Machado 2009 CVD simulation with a "meaning never by colour alone" check; 90 curated kids' palettes each validated live; a pairwise, order-swapped, ensemble visual critic that explains itself and can never block on taste or publish; a SQLite taste memory with few-shot retrieval, reranker weights and agreement-over-time.

## 2 · اللي اتبنى · What was built

| Brief item | Where | Status |
|---|---|---|
| OKLCH/OKLab (coloraide) + vectorised image paths | `mxstudio/colour/oklch.py` | ✅ scalar = coloraide; numpy path (Ottosson matrices, Bradford D50 Lab) cross-checked ≤ 2e-4 |
| CIEDE2000 | `mxstudio/colour/delta_e.py` | ✅ all 34 Sharma 2005 pairs to 1e-4 |
| Harmonies (analogous, complementary, split-complementary, triadic, tetradic, square) at controlled L/C | `harmony.py` | ✅ out-of-gamut members fitted at constant L,h and *reported* (`in_gamut`) |
| Palette extraction (area-weighted k-means in OKLab; skin & near-neutral separate) | `extract.py` | ✅ deterministic (seeded k-means++); medoid = a real art colour; host mask beats heuristic |
| Deck roles background/primary/secondary/accent/text/outline + cross-page consistency | `roles.py` | ✅ text/background < 4.5 is blocking; drift is advisory |
| WCAG 2.x + APCA 0.0.98G-4g | `contrast.py` | ✅ implemented from the published constants; all reference pairs exact |
| Readability over real art + busy-ness + treatment proposal | `readability.py` | ✅ none → outline/shadow → soft scrim (min alpha solved) → cloud bubble; each proposal simulated and `verified` |
| Print safety: ICC CMYK, ΔE2000 warning, TAC, rich black | `print_safety.py` + `catalog/palettes/icc/` | ✅ profiles sha256-pinned, CC0, self-contained |
| CVD simulation (Machado 2009) | `cvd.py` | ✅ matrices 0.0–1.0, equals coloraide; blocking only when meanings collapse **and** no other cue |
| ≥ 80 curated palettes, tagged, each checked | `palettes.py`, `catalog/palettes/kids_palettes{.seeds,}.json` | ✅ **90** palettes, 0 failing |
| Visual critic (rubric, pairwise, ensemble ≥ 2, reasons, never blocks/publishes) | `critic.py` | ✅ judge = injected callable; `vision_judge(transport)` adapter for the real provider |
| Taste memory + reranker + agreement over time | `taste_memory.py` | ✅ SQLite in `app_home()/taste_memory.sqlite`; `agreement_report()` scaffold |

## 3 · قرارات وأرقام افتراضية · Defaults and why

| Default | Value | Evidence / reason |
|---|---|---|
| Rendering intent | relative colorimetric, **no** BPC (BPC selectable) | reproduces the measured lead numbers: red → C0 M95 Y100 K0; black → C83 M72 Y45 K100 (TAC 300 %); neon green (57,255,20) → (116,183,60) |
| ΔE2000 print warning | **6.0** (operator-settable) | measured on FOGRA39: neon green 17.5, pure blue 17.1, magenta 16.5, cyan 14.9 → warn; pure red 5.7, yellow 5.9, black 5.7, typical kids' colours (#e63946 1.1, #2a9d8f 0.6) → no noise |
| Ink limit (TAC) | **300 %** per printer (blocking) | FOGRA39/GRACoL coated; registration black 400 % blocks, rich black C60 M40 Y40 K100 = 240 % passes |
| Rich black | text < 24 pt and hairlines: **K100 only**; large dark areas: C60 M40 Y40 K100 | profile-predicted L*: rich 12.2 vs K-only 17.3 |
| Contrast floor (blocking) | WCAG 2.x 4.5 body / 3.0 large (≥ 18 pt or ≥ 14 pt bold), at the **5th percentile** of the pixels under the box | WCAG is normative; APCA shortfall alone is advisory (`text_contrast_apca_low`) |
| APCA advisory levels | |Lc| 75 body, 60 large, 45 headline | APCA "bronze" simple mode |
| Busy-ness buckets | busy: edge density ≥ 0.08 or textured area ≥ 0.35; moderate: ≥ 0.025 / ≥ 0.12 | facts, not a verdict; smooth gradients read as flat |
| CVD distinctness | OKLab ΔE ≥ 0.06 between meanings at severity 1.0 | classic green/red (#2ca02c/#d62728) collapses for deutan (0.041) → blocking unless an icon/label/shape cue is declared |
| Skin heuristic | OKLCH h 20–80°, C 0.03–0.13, L 0.28–0.94 | **overlaps sand, wood, caramel** — the host should pass the character mask (`skin_source` says which was used) |
| Palette build | seeds → roles derived in OKLCH; any role printing > 5.0 ΔE00 pulled in by chroma reduction | 23/90 palettes had one role pulled in (listed in `print_fitted_roles`) |

APCA note: only the published math/constants of APCA-W3 0.0.98G-4g are used (no code copied); results equal the published examples to 1e-9.

## 4 · أدلة البوابة · Gate evidence

`python -m pytest tests/mag/colour -q -p no:cacheprovider` → **138 passed** (Python 3.13 venv, coloraide 8.13, LittleCMS 2.19, Pillow 12.3).

| Gate requirement | Test | Result |
|---|---|---|
| OKLCH vs coloraide reference values | `test_oklch_harmony.py` | red oklch(0.62796 0.25768 29.234) etc.; Ottosson OKLab red; numpy ≡ coloraide ✅ |
| Harmonies | same | hues equal coloraide's complement/triad/split/analogous/square; L and C held to ±0.004 ✅ |
| ΔE2000 Sharma 2005 | `test_delta_e_contrast.py` | **all 34 pairs** ±1e-4, symmetric; negative control: CIE76 misses ≥ 30 pairs ✅ |
| WCAG / APCA reference pairs | same | #777/#fff = 4.48; Lc 106.04 / −107.88 / 63.06 / −68.54 / 58.15 / −56.24 / 91.67 / −93.07 / 8.32 / −7.53 ✅ |
| CMYK warning on a neon fixture | `test_print_safety.py` | neon green ΔE00 > 12, soft-proof ≈ (116,183,60); neon image: 30 % area flagged; muted image: none ✅ |
| CVD fixtures (Machado, severity 1.0) | `test_cvd.py` | pure red under protanopia → linear (0.152286, 0.114503, −0.003882) → #6d5f00; equals coloraide at 1.0/0.55/0.3 ✅ |
| Critic pairwise consistency ≥ 90 % | `test_critic.py` | deterministic fake judge with 4 % hashed position bias: **95.4 %** over 240 order-swapped pairs ✅; negative control "always first" → 0 % and flagged ✅ |
| Agreement report scaffold | `test_taste_memory.py` | weekly series; simulated operator who weights cultural fit: agreement 68 % (week 1, default weights) → 92 % (week 4, learned weights) ✅ |
| Negative controls | every file | unreadable/unprintable/non-distinct palettes fail; tampered ICC refused; non-CMYK profile refused; red/green blocks without cue; malformed judge output abstains ✅ |

## 5 · الدوال اللي السيرفر يعرضها · Functions for the local server

All return plain JSON-able dicts (`test_api_json.py`).

* Palette & roles: `extract.extract_palette(image, k, skin_mask)`, `roles.derive_roles(palette, mode)`, `roles.check_roles(deck)`, `roles.consistency_report(deck, pages)`, `harmony.all_harmonies(base, lightness, chroma)`, `harmony.harmony(base, scheme, lightness, chroma)`.
* Curated: `palettes.list_palettes(theme, age, mood, mode)`, `palettes.get_palette(id)`, `palettes.nearest_palettes(colours)`, `palettes.validate_palette(p)`.
* Readability: `readability.check_page(image, boxes, roles)`, `readability.check_text_box(...)`, `readability.box_mm_to_px(...)`.
* Print: `print_safety.check_colour(c, settings)`, `check_palette`, `check_image`, `check_cmyk`, `soft_proof` (PIL image), `rich_black_guidance(usage, font_size_pt)`, `profile_info`, `known_profiles`; settings = `PrintSettings(profile, intent, black_point_compensation, tac_limit, delta_e_warn)`.
* CVD: `cvd.check_colour_meanings(meanings, cues)`, `cvd.simulate_image(image, kind, severity)` (preview).
* Critic: `critic.review(candidates, judges, judgements, weights, few_shot, context)`, `critic.vision_judge(transport)`.
* Taste: `TasteMemory(path).record(...)`, `.record_review(review, chosen_id, reasons)`, `.few_shot(k, context)`, `.fit_reranker()`, `.latest_weights()`, `taste_memory.agreement_report(memory, bucket)`.

## 6 · المعلّق · Pending

1. **CI dependency (shared file, not edited):** `coloraide==8.13` (MIT) is in `installer/pyinstaller/requirements-windows.txt` but **not** in `pyproject.toml` or the `mag-ci` install line — the colour suite needs it in CI.
2. **Real vision transport:** `critic.vision_judge(transport)` takes a `payload → raw text` callable; wiring it to the configured `providers.text_vision` (OpenAI-compatible Qwen3-VL) belongs to the provider module. Tests use a recorded cassette only.
3. **Pending on-device proof (operator PC + printer):** ΔE thresholds are against ICC predictions, not a physical press sheet. Proof Runner step: print `catalog/palettes` swatch sheet through the operator's chosen printer profile and compare with the soft proof; adjust `delta_e_warn`/`tac_limit` per printer.
4. **Treatment rendering:** proposals are data (`outline_shadow`, `soft_scrim`, `cloud_bubble` with colours, alpha, padding). Drawing them as PowerPoint shapes is the renderer/Art Desk's job (Phase 3 profiles); the host Agent's visual review of the treated page still applies.
5. **Console surfaces:** palette picker, soft-proof side-by-side, agreement chart — UI work for the webapp owner; the JSON scaffolds are ready.
6. **Python 3.10:** code is 3.10-compatible by construction (ruff `--target-version py310` clean); the suite was run on 3.13 here — CI's 3.10 job is the proof.
7. **Licence-policy test:** currently fails on files outside Phase 6 (`installer/pyinstaller/*` mention a banned name, `mxstudio/kit/probe.py`); none of the Phase 6 files trigger it.
