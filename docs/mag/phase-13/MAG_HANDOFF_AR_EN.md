# MAG_HANDOFF_AR_EN — تسليم استوديو ModuleX للمجلات · ModuleX Magazine Studio handoff

> 2026-10-11 · branch `claude/adoring-mccarthy-zgg4ek` · app version `0.2.0` · release tag to push: `mxs-v0.2.0`
> كل مرحلة ليها تقرير عربي/إنجليزي + `SHA256SUMS` في `docs/mag/phase-N/` وtag محلي `mag-phase-N` (الـproxy رفض push الـtags — اتسجّل في تقرير المرحلة 0).

---

## ٠ · «مستحيل يغلط» · "Impossible to err"

**AR:** مفيش موديل ذكاء اصطناعي معصوم من الغلط، وإننا نقول غير كده يبقى كذب، والبرنامج ده رافض يقوله. اللي البرنامج ده بيبنيه بدل كده هو نظام **أخطاء المساعد فيه ماتقدرش توصل لعميل ولا لمطبعة**: كل حركة للمساعد بتعدّي على فحوصات حتمية (deterministic validators)، كل خطوة مالهاش رجوع محتاجة تأكيد المشغّل، كل إصدار متقفّل ورا مجموعة اختبارات تقييم متقاسة، وكل ادعاء وراه إثبات.

**EN:** No AI model is infallible, and claiming otherwise would be a lie this program refuses to tell. What this program builds instead is a system in which **agent mistakes cannot reach a customer or a printer**: every agent action goes through deterministic validators, every irreversible action needs the operator's confirmation, every release is gated by a measured evaluation suite, and every claim is backed by a proof.

---

## ١ · إيه اللي موجود · What exists

| Area | What it does | Phase report |
|---|---|---|
| Arabic print engine (fork of SlidePoise `4250ba14`) | HarfBuzz shaping, RTL text, harakat-aware line height, A4/A5 + bleed/safe geometry, real picture placeholders | `phase-1/` |
| Studio shell | loopback-only FastAPI + Arabic RTL UI, CSRF session, human-only confirmation tokens, SQLite job queue, content-addressed workspace with immutable approvals, budget guard | `phase-2/` |
| Template Factory | story → 8 variants (A4/A5 × boy/girl × ar/en), operator rules ported verbatim, LibreOffice text proofs, signed publish pack | `phase-3/` |
| Fonts | 214 families (206 certified for print), licence ledger, Office-safe builds, 33 type themes, customer font choice | `phase-4/` |
| Shapes & drawing | 187 Office presets, 41 warps, 18 generators, SVG → editable geometry, licence-gated discovery, canvas | `phase-5/` |
| Colour & taste | 90 kids' palettes, CMYK print checks (free ICC), colour-blind checks; taste is advisory | `phase-6/` |
| New page kinds & products | about-me, certificate, QR back, colouring, bilingual, class magazine plan, Store candidates (M3) | `phase-7/` |
| Integration Kit + libraries | discovery, anchors, additive flagged patches, receivers; `mx_textfit`, `mx_preflight2`, `mx_impose`, `mx_qagate` | `phase-8/` |
| Pre-print QA gate | named blockers per order; AI checks advisory only | `phase-9/` |
| Studio Agent | typed tools only, manual + playbooks, 331-scenario eval suite, model qualification | `phase-10/` |
| Marketing & sales | watermarked flipbook, 4:5/1:1 carousels with consent gate, 16:9 Arabic sales deck | `phase-11/` |
| Release | PyInstaller + NSIS (online/Full), Ed25519-signed updates + rollback, Doctor, first-run wizard | `phase-12/` |
| **Start here + MCP** | the Studio's first page: write a request, attach design pictures, revise in plain words; the assistant looks at every build preview; irreversible steps wait in «طلبات الموافقة». MCP server (`mxstudio-cli.exe mcp`) lets Claude Desktop / Claude Code drive the Studio | `phase-14/` |

**The Studio is never in the per-order path.** Orders stay on the operator's deterministic path (`generate_story()` → Console injection → `pptx_to_pdf`). The Studio contributes only pure libraries (`mxlibs/`, sha256-pinned) and signed packs.

---

## ٢ · رابط التحميل · Download link

Stable direct links (GitHub Releases, free):

* Online: `https://github.com/modulix0025-dev/slidepoise/releases/latest/download/ModuleX-MagazineStudio-Setup.exe`
* Offline (Full): `https://github.com/modulix0025-dev/slidepoise/releases/latest/download/ModuleX-MagazineStudio-Setup-Full.exe`

**AR (بصراحة):** الروابط الثابتة دي **لسه مش شغّالة** — هتشتغل بعد أول إصدار (Release)، والنشر قرارك (الـtag push اترفض من بيئة الكلاود، والنشر التلقائي لإصدار عام اتمنع). **لكن الـEXE اتبنى فعلًا** على GitHub Actions (run `38107836852`) وموجود كـartifact اسمه `installers` في صفحة الـrun (محتاج تسجيل دخول للريبو): `https://github.com/modulix0025-dev/slidepoise/actions/runs/38107836852`. اختبار ويندوز نضيف: النسخة الأونلاين ثبّتت والدكتور عدّى واتشالت والبيانات فضلت؛ التثبيت كمستخدم عادي من غير أدمن نجح. النسخة الكاملة لسه من غير LibreOffice (TO-PIN) فالفحص بتاعها في الدكتور أحمر. لو الريبو هيفضل private: ريبو إصدارات عام + `vars.MXS_RELEASE_REPO` و`secrets.MXS_RELEASE_TOKEN`.

**EN (honest):** the stable links resolve only after the first published release, which is the operator's decision (tag pushes are refused from the cloud and auto-publishing a public release was blocked). The installers **are built**: release run `38107836852` (artifact `installers`, both flavours + SHA256SUMS). Clean windows-latest smoke: online install → Doctor (required checks) → uninstall keeps the workspace — PASS; standard-user per-user install — PASS; Full flavour Doctor FAIL only because the LibreOffice MSI is still TO-PIN. Upstream `release.yml` now uses `make_latest: false`, so `releases/latest` stays the Studio's. Code signing: no paid certificate; SmartScreen warns until the free SignPath Foundation route is configured (documented in `phase-12/CLEAN_INSTALL_RUNBOOK_AR_EN.md`).

---

## ٣ · الفلاجات وقيمها الافتراضية · Every flag and its default

### Operator-side (installed only by the Kit, each patch separately, every one **default OFF**, `"1"` turns it on)

| Flag | System | What it enables | Rollback |
|---|---|---|---|
| `MODULEX_MAG_TEXTFIT` | OM editor | refuse customer text that does not fit (`mx_textfit`) | `mxstudio kit revert --patch P-TEXTFIT` |
| `MODULEX_MAG_SAFEZONE` (+ `MODULEX_MAG_SAFE_MM`) | OM editor | keep faces/text inside the safe zone | `… --patch P-SAFEZONE` |
| `MODULEX_MAG_PAGE_PREVIEW` | OM editor | per-page preview image | `… --patch P-PREVIEW` |
| `MODULEX_MAG_PROOF_APPROVAL` | OM | customer proof approval sidecar | `… --patch P-PROOF` |
| `MODULEX_MAG_PREFLIGHT2` | OM printing | preflight v2 checks (`mx_preflight2`) | `… --patch P-PREFLIGHT2` |
| `MODULEX_MAG_RECEIVERS` | OM / Console / Store | mount the M0–M7 receivers | `… --patch P-RECEIVERS` |

Editor extensions also read `MODULEX_MAG_EDITOR_AUTH=<module>:<callable>` (the editor's own access check, chosen on device; without it they answer loopback clients only) and `MODULEX_MAG_EDITOR_PAGE_PREFIX`.

**Planned flags with no Kit patch yet (honest):** `MODULEX_MAG_QA_GATE` (the `mx_qagate` library is ready; OM's `preflight.run()` receives only the PDF, while the gate also needs the order's deck, approved page count and child name — the probe on your PC shows how OM links them, then the hook becomes its own patch), `MODULEX_MAG_IMPOSE` (`mx_impose` ready, no imposition/CMYK patch), `MODULEX_MAG_FONTCHECK` (Console export font-validator hook). `mxstudio kit plan` lists them as unwired.

Turning a flag off disables the patch instantly. `kit revert` restores the files **byte-identically** (checked by sha256); shared files revert last-in-first-out (`--cascade`). Frozen files are never touched: `OrderManagement/app/utils/config.py`, `OrderManagement/app/editor/deck_pdf.py`, any `modulex_signing.py` / `modulex_pairing.py`, `_willReload` in `ui-utils.js`.

### Studio-side settings (`<app_home>/settings.json`)

| Setting | Default | Meaning |
|---|---|---|
| `agent.mode` | `suggest_only` | `full` only after `python -m mxstudio evals qualify` passes on your model |
| `budget.per_job_usd` / `budget.per_day_usd` | 2.0 / 10.0 USD | AI spend guard; over budget = refused |
| `providers.text_vision`, `providers.image` | disabled | your GPU endpoints (OpenAI-compatible / ComfyUI); keys stored with DPAPI, only `sha256[:8]` shown |
| `workspace` | `C:\المشروع\ModuleX_MagazineStudio_Data\` | content-addressed workspace |
| `discovery.iconify_base_url` | official API | optional self-hosted Iconify mirror |
| Update consent | asked every time | an update installs on next launch only with your consent; rollback is one click (needs confirmation) |

---

## ٤ · العقود · Every contract

All HTTP contracts are signed with the vendored `modulex_signing` (byte-identical, sha `a2f1db60…`) and carry `contract: "mag/v1/<id>"`. Schema URLs are in this repository (branch above) and served live by M0 when the receivers are on.

| Id | Direction | Schema |
|---|---|---|
| M0 | `GET /internal/mag/v1/contract`, `/health` | `mxstudio/receivers/routers.py` (contract version, kinds, sha256 of every schema) |
| M1 | template set → OM (stored as candidate; activation = your confirmation) | `mxstudio/receivers/schemas/m1_template_set.schema.json` |
| M2 | deck contract → Console (Console's own human approval writes the contract) | `mxstudio/receivers/schemas/m2_deck_contract.schema.json` |
| M3 | theme / page-kind product → Store (suggested price only) | `mxstudio/factory/products.py::m3_candidate` |
| M4 | `mx_textfit.fit(...)` (pure library) | `mxlibs/mx_textfit/MANIFEST.json` |
| M5 | `mx_preflight2.run(...)`, `mx_impose.saddle(...)`, `mx_qagate.run_gate(...)` | `mxlibs/*/MANIFEST.json` |
| M6 | font-set sync | `mxstudio/receivers/schemas/m6_font_sync.schema.json` |
| M7 | customer font choices | `mxstudio/receivers/schemas/m7_font_choices.schema.json` |

Pack fallback: `*.magpack.zip` = files + `manifest.json` + `manifest.sig` (`modulex_signing.signature` over the manifest bytes with the shared secret `modulex.hmac`), imported through the receiver's own code path.

---

## ٥ · انشر قصة جديدة في 10 خطوات · Publish a new story in 10 steps

1. افتح الاستوديو ← «القصص والقوالب». · Open the Studio → Stories & templates.
2. اكتب القصة: المفتاح، العنوان عربي/إنجليزي، الصفحات ونوع كل صفحة، النصوص بـ`{NAME}`، الأسماء الأساسية (ولد/بنت). المساعد يقدر يقترح مسودة. · Write the story (key, titles, page kinds, texts with `{NAME}`, base names); the agent may draft.
3. «مكتب الرسم»: البريفات بتطلب رسم **من غير أي حروف**؛ ولّد بموديل مجاني (Qwen-Image / FLUX.1 schnell) على جهاز الـGPU بتاعك أو ارفع الرسم بإيدك. صور العملاء عمرها ما بتتعدّل بالذكاء الاصطناعي. · Art Desk: text-free briefs, free models or manual upload.
4. «ابني»: بيطلع 8 نسخ (A4/A5 × ولد/بنت × عربي/إنجليزي). · Build: 8 variants.
5. الفحوصات بتشتغل لوحدها: قواعد OM الأصلية، أماكن الصور، النص داخل مكانه، إثبات النص بعد التصدير، عدد الصفحات. أي فشل = مانع بالاسم. · Validators run; a failure is a named blocker.
6. **بص بعينك** على صفحة المراجعة (contact sheet) — الحكم البصري ليك. · Look at the contact sheet yourself.
7. اعتمد النسخة (نافذة تأكيد — التوكن بيتعمل من الإنسان بس). · Approve (human-only confirmation).
8. حط السر المشترك `modulex.hmac` مرة واحدة في الإعدادات، وبعدين «جهّز حزمة النشر» (مالهاش رجوع ← تأكيد). · Set `modulex.hmac` once; publish the signed pack (confirmation).
9. `mxstudio kit pack-import --pack <pack.zip> --system OM` (وبعدين `--system Console`) ← بتدخل **مرشّح** (candidate). · Import into OM / Console as a candidate.
10. فعّلها في OM (تأكيدك ← `add_story`)، والكونسول يعتمد عقد الصور (M2)، واعمل أوردر تجريبي كامل. الرجوع = النسخة السابقة من السجل بنفس البايتات. · Activate in OM, approve M2 in Console, run one test order; rollback = previous registry entry.

---

## ٦ · تشغيل الـKit · Running the Kit

```
mxstudio kit discover            # finds OM / Console / Store under C:\المشروع (never asks where)
mxstudio kit verify              # anchors: signatures, verbatim bodies, constants, contract sha256
mxstudio kit probe               # read-only facts (routes, fonts, process owners)
mxstudio kit plan                # per patch: ready/blocked + confirm code + diff
mxstudio kit apply --patch P-TEXTFIT --confirm <code>   # one patch at a time; flag stays OFF
mxstudio kit status
mxstudio kit proofs --engines powerpoint,soffice        # Proof Runner on the device
mxstudio kit report              # MAG_DEVICE_REPORT_<date>.zip to send back
mxstudio kit revert --patch P-TEXTFIT [--cascade]       # byte-identical rollback
```
Details, anchors and backups: `phase-8/KIT_NOTES.md`. A new `RUN_TESTS.bat` failure after a patch rolls it back automatically.

---

## ٧ · حدود المساعد ونتايجه · Agent limits and eval scores

**Limits:** acts only through typed tools (schema-checked); suggestion-only until your model qualifies; cannot approve, publish, roll back or mint confirmation tokens (irreversible tools stop for the human); at most one clarifying question per task; 24 steps per task; tool results are wrapped as DATA and instruction-like text is flagged, never obeyed; cannot edit customer photos with AI; budget guard; licence gate for print assets and model weights; no access to secrets.

**Scores (331 scenarios, `evals/scenarios.json`):**

| Suite | Result | What it proves |
|---|---|---|
| Safety (155) | **155/155 = 100 %** | model-independent guarantees of the tool layer (worst-case scripted attacker, incl. prompt injection through the real loop) |
| Tasks (176) | **176/176** under scripted reference plans | every task is solvable and every grader is correct — **not** a model's skill |
| Model scores | **pending on device** | run `python -m mxstudio evals qualify` after configuring your GPU text/vision endpoint (Qwen3-VL); failing ⇒ the agent stays suggestion-only |

Negative controls (a removed guardrail must turn the suite red) are in `tests/mag/agent/` and `tests/mag/marketing/`. Report: `phase-11/evidence/evals_report_scripted_331.json`.

---

## ٨ · اللي لسه مستني إثبات على الجهاز · Still device-unverified (with the Proof Runner step)

| Item | Proof Runner step |
|---|---|
| Installer (both flavours), Doctor green, uninstall keeps workspace | run `.github/workflows/mag-release.yml` (Actions on) or `phase-12/CLEAN_INSTALL_RUNBOOK_AR_EN.md` §4 in Windows Sandbox; send `C:\ModuleX-Sandbox-Results\` |
| LibreOffice `msiexec /a` as a standard user | runbook §5 |
| Update + rollback between two real versions | runbook §7 |
| PowerPoint export of every certified font; Windows font install | `python -m mxstudio.fonts.specimen --engines powerpoint`; Proof Runner › Fonts |
| Name Art warps and ring warps with Arabic under PowerPoint | Proof Runner › Fonts › Name Art export; shapes proof deck |
| Real anchors in OM/Console/Store, `RUN_TESTS.bat`, process owners | `mxstudio kit verify` → `probe` → `report` |
| Live `generate_story` dry run against the registry | `mxstudio kit proofs --story "<display name>"` |
| Discovery cassettes re-recorded live (APIs blocked from the cloud) | Proof Runner › Shapes › re-record cassettes |
| Sales deck in PowerPoint; flipbook on a phone | open `marketing/sales/*.pptx`; open `flipbook-*/index.html` |
| Model qualification on your GPU | `python -m mxstudio evals qualify` |

---

## ٩ · المطلوب منك (مرة واحدة) · Operator actions (once)

1. GitHub Actions شغّالة (CI و Magazine Studio CI خضر على ويندوز ولينكس وماك). · Actions are on; CI is green on Windows, Linux and macOS.
2. مفتاح التحديثات: `python -m mxstudio.update keygen --out-private key.txt` ← السر `MXS_UPDATE_SIGNING_KEY` والمتغيّر `MXS_UPDATE_PUBLIC_KEY`، وامسح الملف. · Update signing key pair.
3. ثبّت قيم `TO-PIN` في `installer/downloads.json` (LibreOffice، خزنة الخطوط، حزم الأشكال). · Pin the TO-PIN downloads.
4. انشر الإصدار: من GitHub ← Releases ← Draft a new release ← tag جديد `mxs-v0.2.0` على الفرع ← Publish (أو `git tag mxs-v0.2.0 && git push origin mxs-v0.2.0` من جهازك). ده بيشغّل البناء ويرفع الملفات والروابط الثابتة. · Publish: create tag `mxs-v0.2.0` (GitHub UI or git) — the workflow builds, smoke-tests and attaches the installers.
5. في الاستوديو: حط `modulex.hmac` (السر المشترك بتاع أنظمة ModuleX). · Set the `modulex.hmac` secret.
6. اضبط عناوين الـGPU (نص/رؤية: Qwen3-VL؛ صور: Qwen-Image / Qwen-Image-Edit-2511 / FLUX.1 schnell) وبعدين `evals qualify`. · Configure GPU endpoints, then qualify.
7. اللوجو: حط PNG رسمي مكان `mxstudio/ui/logo-placeholder.svg` (اللوجو الأصلي ماتنقلش صح، فاستخدمنا placeholder). · Provide the logo PNG.
8. **تنبيه ترخيص:** لو الكونسول بتاعك بيستخدم FLUX.1 Kontext [dev] — ده ترخيص غير تجاري؛ البديل المجاني Qwen-Image-Edit-2511 (Apache-2.0). الاستوديو بيرفض الموديل ده. · Licence note: FLUX.1 Kontext [dev] is non-commercial; the free replacement is Qwen-Image-Edit-2511.

---

## ١٠ · SBOM وتقرير التراخيص · SBOM and licence report

* `SBOM.cdx.json` (CycloneDX 1.5): Python closure, npm runtime packages, vendored contracts by sha256, 214 fonts, installer payloads.
* `LICENCE_REPORT_AR_EN.md`: code, fonts, shapes, AI models, banned → replacement. **Banned components found: none.**
* Regenerate in the release environment: `python tools/mag_reports.py --out docs/mag/phase-13`.

## ١١ · الاختبارات · Tests

See `MAG_PHASE_13_REPORT_AR_EN.md` for the final run (upstream + `tests/mag` + node + browser) and the static gates.
