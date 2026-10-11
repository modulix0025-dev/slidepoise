# KIT_NOTES — «ربط أنظمتي» · The Integration Kit

> Phase 8 · owner of `mxstudio/kit/`, `mxstudio/receivers/`, `tests/mag/kit/` · 2026-10-11
> **AR:** الملف ده بيشرح الـKit: بيدوّر على أنظمتك، بيتأكد من نقاط الربط، بيفحص (قراءة بس)، وبيركّب باتشات صغيرة جنب الكود بتاعك — كل باتش ورا فلاج مقفول افتراضيًا، وبموافقتك على كل باتش لوحده، ويرجع زي ما كان بالبايت.
> **EN:** What the Kit does, per-patch anchors/flags/files/revert, and the exact on-device runbook. Everything below was proved on **synthetic replicas** (Arabic root folder «المشروع») in the cloud; what only the operator's PC can prove is marked **pending on-device proof** with the step that proves it.

---

## 1 · الأوامر · Commands

Non-interactive, JSON on stdout, exit `0` done · `2` refused/blocked (named reason) · `1` error.
In the Studio: menu «ربط أنظمتي» (tools `kit.*`; `kit.apply`/`kit.revert` need a human confirmation token from the screen **and** the plan's confirm code).

```
mxstudio kit discover                      # systems by marker files under the root (default C:\المشروع)
mxstudio kit verify                        # anchors (signatures, verbatim bodies, constants, sha256)
mxstudio kit probe [--no-network] [--base-name X]
mxstudio kit plan [--patch P-…]            # ready/blocked + confirm code + diff per patch
mxstudio kit apply --patch P-… --confirm <code> [--dry-run] [--no-tests]
mxstudio kit revert --patch P-… [--cascade]
mxstudio kit status
mxstudio kit proofs [--engines powerpoint,soffice] [--limit N] [--story "<display name>"] [--no-story]
mxstudio kit report [--out DIR]            # MAG_DEVICE_REPORT_<date>.zip
mxstudio kit pack-build --kind m1|m2|m6|m7 --document doc.json --id <pack-id> [--file name=path] --out pack.zip
mxstudio kit pack-import --pack pack.zip --system OM|Console
```
Global: `--root <dir>` (or the Studio setting / `MXS_PROJECT_ROOT`), `--app-file OM=app/main.py` when discovery finds more than one `FastAPI()` module. Arabic paths: prefer the setting or `MXS_PROJECT_ROOT` over argv.

## 2 · القواعد اللي الـKit بيفرضها · Rules the Kit enforces

| Rule | How |
|---|---|
| Anchor mismatch ⇒ no patch | `plan` marks the patch `blocked` with expected/found (+ unified diff for verbatim bodies); `apply` refuses before any write |
| Contract file with a different sha256 = "operator updated it" | status `operator_updated`; device copy is loaded and compared: **5 signing vectors** (`modulex_signing`) or **5 `pdf_stats` known answers** (`pptx_to_pdf`). Same behaviour ⇒ warning only; different ⇒ blocks. Never overwritten |
| Per-patch operator confirmation | 10-hex confirm code = sha256(patch + anchor statuses + before/after sha of every file). It changes whenever the target bytes change (e.g. after another patch touched the same file) → re-run `plan` |
| Frozen files never touched | refused by path at plan time (`OrderManagement/app/utils/config.py`, `OrderManagement/app/editor/deck_pdf.py`, any `modulex_signing.py` / `modulex_pairing.py` / `ui-utils.js`) **and** hashed before/after every apply/revert |
| Flags default OFF | every hook starts with `if os.environ.get("<FLAG>", "0").strip() == "1":` |
| Backups | `<system>\_backup_mag_<patch>_<YYYYMMDD>[_n]\` + `manifest.json` (sha before/after, anchors, tests, frozen hashes). Never inside any `static` folder (checked) |
| Revert byte-identical | restores from backup when the file still has the post-patch sha; else removes exactly our marker block if that reproduces the original sha; else refuses ("drift"). Shared files revert LIFO (`--cascade`) |
| Idempotent | applying an applied patch = `already_applied`; our markers present without a Kit record = `blocked` |
| System tests | `RUN_TESTS.bat` via `proc.run_hidden` before and after; a **new** failure rolls the patch back automatically |
| Children | only `mxstudio.proc.run_hidden` (CREATE_NO_WINDOW, PYTHONUTF8=1, paths in env vars) |

## 3 · نقاط الربط · Anchors (ground truth from the brief)

| Anchor id | File (relative to system) | Check |
|---|---|---|
| OM.story_engine.generate_story | `app/services/story_engine.py` | contains `def generate_story(story_name, child_name, gender, language, output_folder, size="A4"):` |
| OM.story_engine.replace_in_paragraph / replace_in_shape | same | body == verbatim PORT block of `mxstudio/validators/operator_ports.py` (CRLF/trailing-space insensitive) |
| OM.story_engine.resolve_variant / add_story | same | signature line contains |
| OM.editor.deck.constants | `app/editor/deck.py` | EMU_PER_CM=360000, IDEAL_DPI=300, OK_DPI=150, MIN_DPI=72, MIN_SIDE_PX=300, MIN_FRAME_CM=1.5, MAX_TEXT=2000, MAX_LINES=30 (AST) |
| OM.editor.deck.regexes | same | TEXT_RE / IMG_RE patterns (AST) |
| OM.editor.deck.signatures | same | `locate(order)`, `inventory(deck)`, `_set_paragraph(p, new)`, `apply(deck_in, deck_out, texts, images, inv)`, `export_pdf(deck, pdf, expect_pages, attempts=2)` |
| OM.editor.deck.killswitch | same | `MODULEX_P149` present |
| OM.editor.printing.freeze_rebind | `app/editor/printing.py` | `freeze_sent_artifacts(` before `rebind_ready_artifacts(` |
| OM.printing.preflight.run | `app/printing/preflight.py` | `run(path, *, magazine_size='A4', expected_pages=None, expected_sha256=None, output_status=None, require_approved=False, bleed_mm=Decimal('0'), max_bytes=…` |
| OM.printing.print_service.public | `app/printing/print_service.py` | defines `freeze_sent_artifacts`, `rebind_ready_artifacts` (public list reported) |
| OM.app_package / Console.package | `app/__init__.py` / `execution_console/__init__.py` | present, or the code imports through the package name |
| OM.app_object / Console.app_object | discovered | exactly one module-level `X = FastAPI(` (override `--app-file`) |
| OM.signing.sha / Console.signing.sha | `modulex_core/modulex_signing.py` / first copy found | sha256 `a2f1db60…347e` |
| Console.magazine_pptx.* | `execution_console/services/magazine_pptx.py` | `ENTRY_STEM = "modulex_scene_{:02d}"`, `_PH_PIC_RE = …`, `deck_picture_slots` verbatim |
| Console.pptx_to_pdf.sha | `execution_console/services/pptx_to_pdf.py` | sha256 `2920eb32…7eee` |
| Console.story_decks.shape | `story_decks.json` (also looked for under `execution_console/`) | stories → display_name, reference, variants ⊆ {boy_a4, boy_a5, girl_a4, girl_a5} → `.pptx` |
| Store.editor_modules / Store.c11_admin_action | `mxstore/areas/accounts/editor/{ledger,pricing,topup,limits,audit,config,db}.py`, `contracts/*c11_admin_action*` | files exist; schema requires store_id (`^[a-z0-9-]{1,32}$`), actor, reason |
| info only | story_contracts/ (+ approvals.log.jsonl present), qc_agent.py, qc_store.py, Orchestrator signing copy | reported, never gate a patch |

## 4 · الباتشات · Patches

Hook marker format (Python): `# >>> MODULEX_MAG <id> >>>` … `# <<< MODULEX_MAG <id> <<<`. Payloads are new packages (`app/mag_*`) — no existing file other than the hook target is modified.

### P-TEXTFIT — قياس نص العميل · `MODULEX_MAG_TEXTFIT`
- **Anchors:** OM.editor.deck.signatures/constants/regexes/killswitch, OM.app_package.
- **Hook:** top of `apply(deck_in, deck_out, texts, images, inv)` in `OrderManagement/app/editor/deck.py`, after its docstring:
  ```python
  if __import__("os").environ.get("MODULEX_MAG_TEXTFIT", "0").strip() == "1":
      from app.mag_textfit.gate import check_texts as _mx_check_texts
      _mx_check_texts(deck_in, texts, inv)
  ```
- **Payload:** `OrderManagement/app/mag_textfit/{__init__,gate}.py` + `vendor/mx_textfit/` copied verbatim and verified against its `MANIFEST.json` (source and destination).
- **Behaviour (flag on):** every edited frame is measured (`paragraph_box` + `fit` + `char_limit` of the vendored lib); `does_not_fit` / `missing_glyphs` ⇒ `TextDoesNotFit(ValueError)` with `code="MAG_TEXT_OVERFLOW"` and «النص في صفحة N أطول من المكان المخصّص له. من فضلك اختصره شوية وجرّب تاني.» — raised **before** the deck is written. `font_missing` (font invisible to OM's account) is returned as *unmeasured*, not refused.
- **Pending on device:** how the editor route turns a `ValueError` into the customer message (probe lists the `/api/editor` routes); fonts visible to OM's account (probe `process_owners` + fonts).
- **Revert:** `mxstudio kit revert --patch P-TEXTFIT`.

### P-SAFEZONE — منطقة الأمان · `MODULEX_MAG_SAFEZONE`
- **Anchors:** OM.app_object, OM.app_package, OM.editor.deck.signatures.
- **Hook:** module end of OM's FastAPI module (before `if __name__ == "__main__":`): mounts `app.mag_safezone.mount.mount(app)` when the flag is 1.
- **Payload:** `app/mag_safezone/{__init__,geometry,mount,editor_common}.py`, `safezone.js`, `mag_config.json`.
- **Routes:** `GET /api/editor/mag/safezone/<order>` (trim/safe rectangles + frames/text crossing the safe band), `GET /api/editor/mag/safezone.js`; a response middleware inserts one `<script>` tag into editor HTML pages (`MODULEX_MAG_EDITOR_PAGE_PREFIX`, default `/editor`) — no operator HTML/JS or `static` file is edited.
- **Access:** default-deny — loopback only until `MODULEX_MAG_EDITOR_AUTH=<module>:<callable>` names the editor's own access check (chosen on device from the probe's route map).
- **Limits:** no face detection in the order path; a picture frame crossing the safe band is the measurable proxy.

### P-PREVIEW — معاينة صفحة · `MODULEX_MAG_PAGE_PREVIEW`
- **Anchors/Hook:** as P-SAFEZONE (own marker block, own flag).
- **Payload:** `app/mag_preview/{__init__,preview,mount,editor_common}.py`, `mag_config.json`.
- **Route:** `GET /api/editor/mag/preview/<order>/<slide>` → one-slide copy (hidden slide un-hidden in the copy) exported with **OM's own `export_pdf`**; cached as `OrderManagement/mag_cache/preview/<sha256(deck)>-<slide>.pdf`.

### P-PROOF — موافقة العميل على البروفة · `MODULEX_MAG_PROOF_APPROVAL`
- **Anchors:** as P-SAFEZONE + OM.editor.printing.freeze_rebind + OM.printing.print_service.public.
- **Payload:** `app/mag_proof/{__init__,approval,mount,editor_common}.py`, `proof.js`, `mag_config.json`.
- **Routes:** `GET /api/editor/mag/proof/<order>`, `POST /api/editor/mag/proof/<order>/approve {version}` → `{version, timestamp, sha256, actor}`.
- **Binding:** a public `print_service` function named `record_proof_approval` / `attach_proof_approval` / `bind_proof_approval` if the device has one (keyword call); **today none exists**, so the record is stored beside the PDF as `<pdf>.proof_approval.json`. Valid only while the PDF sha256 equals the approved one. Print tables are never written.
- **Pending:** the print portal reading the sidecar (`approval.status(pdf)`) needs one more anchor in the portal code — to be located from the probe's route map, then planned as its own patch.

### P-PREFLIGHT2 — فحص الطباعة v2 · `MODULEX_MAG_PREFLIGHT2`
- **Anchors:** OM.printing.preflight.run, OM.printing.print_service.public, OM.app_package.
- **Hook:** module end of `OrderManagement/app/printing/preflight.py`:
  ```python
  if __import__("os").environ.get("MODULEX_MAG_PREFLIGHT2", "0").strip() == "1":
      from app.mag_preflight2.hook import wrap_run as _mx_wrap_run
      run = _mx_wrap_run(run)
  ```
  Flag read at import (restart OM after changing it). Flag off ⇒ `run` **is the original function object** (proved: identical `co_code`).
- **Payload:** `app/mag_preflight2/{__init__,hook}.py` + `vendor/mx_preflight2/` (manifest-verified).
- **Behaviour:** original `run` first, then `mx_preflight2.run(pdf, {size: magazine_size, bleed_mm: <call's bleed, default 0>, expected_pages, max_bytes})`; checks appended with `source: "mx_preflight2"`; a failing v2 check sets `ok=False`. A crash in v2 is a named check `mag_preflight2_error`.

### P-RECEIVERS — مستقبلات العقود · `MODULEX_MAG_RECEIVERS`
- **Anchors:** OM.app_object, OM.app_package, OM.story_engine.add_story, OM.signing.sha, Console.app_object, Console.package, Console.signing.sha.
- **Hooks:** module end of OM's and the Console's FastAPI modules.
- **Payload:** `mxstudio/receivers/` copied verbatim to `OrderManagement/app/mag_receivers/` (kinds m1, m6, m7) and `ModuleX_Console/execution_console/mag_receivers/` (m2), + `mag_config.json` (system's own `modulex_signing.py` path, candidate store `mag_candidates/`).
- **Routes** (all signed — `verify` then `check_replay`; the signed PATH is the URL path): `GET /internal/mag/v1/health`, `GET /internal/mag/v1/contract`, `POST /internal/mag/v1/{m1/template-set | m2/deck-contract | m6/font-set | m7/font-choices}`, `GET /internal/mag/v1/candidates/<kind>`, `POST /internal/mag/v1/m1/candidates/<id>/activate {operator_confirmation}`.
- **Refusals:** 503 no secret · 401 missing/bad signature or stale (±300 s) · 409 replay · 422 schema/cross-check (named errors) · 403 wrong operator code.
- **Activation (M1 only):** by parameter name onto the device's real `add_story()`/`update_story()` signature; any required parameter the candidate cannot fill ⇒ `blocked` with the list; template files copied only if absent (an existing file with other bytes blocks). M2 stays a candidate: the Console's human approval writes the story contract — the receiver never writes `approvals.log.jsonl`. M6 font installation is never automatic.
- **Schemas:** `mxstudio/receivers/schemas/{m1_template_set,m2_deck_contract,m6_font_sync,m7_font_choices}.schema.json` (draft 2020-12; envelope `contract`, `schema_version`, `produced_by`, `created_at`). Validated on device by a dependency-free subset validator, cross-checked against `jsonschema` in tests.
- **Packs (fallback when no endpoint):** `mag-pack-<id>.zip` = `manifest.json` + `manifest.sig` (`modulex_signing.signature(secret, "POST", "/pack/<id>", ts, manifest_bytes)`) + `document.json` + `files/*`; import verifies signature, every sha256, exact member set, no traversal, then the same ingest path. `mxstudio kit pack-import --system OM|Console`.
- **Note:** if the Console runs as a frozen PyInstaller build (`discover` → `frozen_app_hint`), source hooks act only after the operator's own rebuild; use packs meanwhile.

### Flags with no Kit patch yet (reported by `plan.unwired_flags`)
`MODULEX_MAG_IMPOSE` (mx_impose is vendor-ready; patch not defined this phase), `MODULEX_MAG_FONTCHECK` (the proof runner runs the deck font check on device), `MODULEX_MAG_QA_GATE` (phase 9).

## 5 · الفحص والإثبات والتقرير · Probe, proofs, report

- **Probe (read-only):** per template — slide size (cm), slides, hidden slides, `<p:ph type="pic">` / `<p:pic>` / `<p:sp>` counts, texts, sizes (pt), typefaces (exact, two spaces of «Blabeloo  MagdySoliman» kept), `rtl="1"`; **code points** of every occurrence of each base name (default إياد/جيداء/ليلى/Eyad/Gaidaa + literals in story_engine + `--base-name`) incl. prefix forms (ل/ب/و/ف/ك ± tatweel) and lam-alef presentation forms U+FEF5–U+FEFC, with `literal_match` (would OM's STEP 1 hit it?) and `single_run`; installed fonts (HKLM/HKCU) vs template typefaces (per-user-only flagged); which account owns ports 8000/6060/8200/9000 (PowerShell CIM, fallback `tasklist /v /fo csv`); PowerPoint (registry CurVer) / LibreOffice version; `/api/editor` references and `StaticFiles` mounts; qc_agent.py / qc_store.py / qa_refs; health on 8000/6060/8200/9000; **model licences** in Console ComfyUI workflows (FLUX.1 [dev] / Kontext ⇒ non-commercial, alternative Qwen-Image-Edit-2511 / Qwen-Image / FLUX.1 [schnell]) — report only.
- **Proofs:** template **copies** → vendored `pptx_to_pdf.convert` (PowerPoint first) in a hidden child; pages vs visible slides, font objects, deck typefaces vs PDF fonts (substitution findings), picture-slot map; real `generate_story` dry run under OM's interpreter (`MXS_OM_PYTHON` or `OrderManagement\venv\Scripts\python.exe`), output to temp, synthetic child «تجربة», templates hashed before/after; deck font visibility; `mx_preflight2` on a sample PDF. Signed with the Studio's **Ed25519** key (DPAPI-protected on Windows); verify with `mxstudio.kit._keys.verify`.
- **Report:** `MAG_DEVICE_REPORT_<date>.zip` = discover/anchors/probe/patches JSON + signed proofs + redacted Kit log + README. Redaction: child names in `«<child> - <story> (AR|EN) [A4|A5]»`, UUIDs, `order_<id>`, 8-hex upper refs, e-mails, Egyptian mobiles; secret values of `MODULEX_HMAC_SECRET`/`ORCHESTRATOR_HMAC_SECRET`/`API_HMAC_SECRET` replaced and the archive re-scanned (refuses to write if one survives).

## 6 · خطوات التشغيل على الجهاز · On-device runbook (exact)

AR: كل خطوة بتطلع JSON؛ ابعت التقرير في الآخر. مفيش أي خطوة بتكتب في أنظمتك غير «apply» بعد ما توافق.
EN: Run as the Windows user who normally runs the Studio. Nothing writes into the estate except step 6.

1. **Root:** Studio → الإعدادات → مجلد المشروع = `C:\المشروع` (or set `MXS_PROJECT_ROOT`). `mxstudio kit discover` → OM/Console/Store/Orchestrator `found`; note `frozen_app_hint`.
2. **Anchors:** `mxstudio kit verify` → every anchor `ok`. Any `mismatch`/`operator_updated`: stop for that patch; the JSON carries expected/found/diff and the behaviour comparison.
3. **Probe:** `mxstudio kit probe` → check `templates.files[*].name_occurrences` (any `lam_alef_ligature: true` or `literal_match: false` needs a `replacements` entry), `template_typefaces` (`installed:false` / `user_scope_only:true` with OM run by another account ⇒ install machine-wide with consent), `process_owners`, `office`, `editor.api_editor_refs`, `model_licences.non_commercial`.
4. **Proofs (before any patch):** close nothing — PowerPoint is quit only if the proof started it. `mxstudio kit proofs --engines powerpoint,soffice --story "<display name from story_decks.json>"`. Expect per template `status: exported`, `engine: powerpoint`, no `typeface_not_in_pdf`; `generate_story.status: ran`, `templates_untouched: true`.
5. **Plan:** `mxstudio kit plan` → read each patch's `files`, `diffs`, `blockers`, `confirm_code`.
6. **Apply one patch at a time** (recommended order: P-PREFLIGHT2, P-TEXTFIT, P-SAFEZONE, P-PREVIEW, P-PROOF, P-RECEIVERS): `mxstudio kit apply --patch P-PREFLIGHT2 --confirm <code>`. The Kit runs `RUN_TESTS.bat` before/after (rolls back on a new failure). After a patch that touched the FastAPI module, **re-run `plan`** — the next patch's code changes.
7. **Flags stay OFF.** Restart OM/Console; confirm behaviour unchanged. Turn ONE flag on (system environment, e.g. `MODULEX_MAG_PREFLIGHT2=1`), restart that system, try it, turn it off again if anything looks wrong. For editor extensions decide `MODULEX_MAG_EDITOR_AUTH` from step 3's route map first. For receivers make sure `MODULEX_HMAC_SECRET` (or the system's legacy name) is set.
8. **Report:** `mxstudio kit report` → send `MAG_DEVICE_REPORT_<date>.zip` (in `%LOCALAPPDATA%\ModuleX\MagazineStudio\kit\reports\`).
9. **Revert any time:** `mxstudio kit revert --patch <id>` (add `--cascade` if a later patch shares the file). Expect `byte_identical: true`, `frozen_unchanged: true`. Backups stay in `_backup_mag_*` for audit.

## 7 · الأدلة · Evidence (cloud, synthetic replicas)

`python -m pytest tests/mag/kit -q -p no:cacheprovider` → **103 passed** (LibreOffice proof included). Replicas: `tests/mag/kit/replicas/build_replica.py` (Arabic root «المشروع», verbatim bodies taken from `operator_ports.py`, sha-pinned contract copies, frozen files, templates with «ﻹياد» U+FEF9 and a split-run name, hidden slide, ComfyUI workflows).

Negative controls (each proves a check can fail): 8 anchor mutations block exactly their patches; `operator_updated` with changed behaviour (`pdf_stats`, signing vectors 0/5); wrong confirm code; markers without record; tampered/missing vendored lib; drifted file refuses revert; failing system tests roll back; frozen-path patch refused; flags-on twin differs from pristine twin; bad signature / method-path swap / replay / stale / no secret; schema and cross-check violations; tampered packs (5 kinds) and wrong secret; tampered proof report fails Ed25519; report refuses when a secret survives.

**Pending on-device proof:** PowerPoint export fidelity per template/font; real anchors in the operator's code; process owner/font visibility; real `generate_story` dry run against the live registry (Postgres); `RUN_TESTS.bat` results; PowerPoint placeholder open/save round-trip (not automated this phase); editor error-message path for `TextDoesNotFit`; editor auth callable; print-portal sidecar reader; Console frozen-build status.

## 8 · تغييرات مطلوبة في ملفات مشتركة · Requested shared-file changes

None blocking. `mxstudio/__main__.py` already delegates `kit` to `mxstudio.kit.cli`; `mxstudio/app/features.py` already lists the `kit` area (`mxstudio/kit/api.py` registers the tools, `mxstudio/kit/jobs.py` the worker handlers).
