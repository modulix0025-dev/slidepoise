# MAG_PHASE_2_REPORT_AR_EN — المرحلة 2: هيكل الاستوديو · Phase 2: Studio shell

> 2026-10-11 · branch `claude/adoring-mccarthy-zgg4ek` · local tag `mag-phase-2`

## 1 · الخلاصة · Summary
**AR:** الاستوديو بقى برنامج حقيقي: سيرفر محلي على `127.0.0.1` بس (أي جهاز تاني بيترفض)، كل تعديل محتاج جلسة الشاشة + CSRF، صف مهام بيكمّل بعد أي وقوع، مساحة عمل بنسخ ومعتمَد مايتغيّرش، مفاتيح مشفّرة (DPAPI على ويندوز) ومابترجعش أبدًا، حدّ لمصاريف الـAI، مزوّدين مجانيين افتراضيًا (D13)، وأدوات الـAgent بـschema وتوكن تأكيد بشري لأي خطوة مالهاش رجوع وسجل لكل حاجة. الواجهة عربي RTL بتصميم Crossbar أبيض وأسود، ومتجرّبة في Chromium حقيقي.

**EN:** The Studio is now a real application: loopback-only server, session + CSRF on every mutation, restart-safe job queue, versioned workspace with immutable approvals, write-only DPAPI secrets, AI budget guard, D13 free provider defaults, schema-validated agent tools with single-use human confirmation tokens and a full audit log. Arabic RTL Crossbar UI tested in a real Chromium.

## 2 · اللي اتبنى · What was built
| Piece | Module | Rule it enforces |
|---|---|---|
| Child processes | `mxstudio/proc.py` | CREATE_NO_WINDOW, PYTHONUTF8=1, no stdin; paths in env. A static test fails on any direct `subprocess` use in `mxstudio/`. |
| Paths & settings | `mxstudio/config.py` | program outside `C:\المشروع`; app state in `%LOCALAPPDATA%\ModuleX\MagazineStudio`; workspace default `C:\المشروع\ModuleX_MagazineStudio_Data` |
| Secrets | `mxstudio/secrets.py` | DPAPI (`CryptProtectData`, per user) on Windows; only `sha256[:8]` fingerprints leave the store |
| Workspace | `mxstudio/workspace.py` | content-addressed blobs, versions, diff, restore; approved versions immutable and named |
| Queue & worker | `mxstudio/worker.py`, `mxstudio/jobs.py` | SQLite WAL, leases + heartbeat, idempotency keys, retries, crash recovery |
| Budget | `mxstudio/budget.py` | estimate → per-job / per-day ceilings (Arabic messages) → record; self-hosted = 0 |
| Providers | `mxstudio/providers/` | OpenAI-compatible (Qwen3-VL default), remote ComfyUI (Qwen-Image / Qwen-Image-Edit-2511 / FLUX.1 [schnell]), manual exchange; **non-commercial weights refused** (patterns from `catalog/licence_policy.json`) |
| Agent tools | `mxstudio/agent/tools.py`, `catalog.py` | JSON Schema validation, irreversible ⇒ token minted only by the human UI session, bound to tool+args, 10-min expiry, single use; redacted audit; `customer_photo.ai_edit` always refuses (operator rule) |
| Server | `mxstudio/app/server.py`, `runner.py`, `features.py` | loopback-only middleware, session cookie + `X-MXS-CSRF`, M0 `/internal/mag/v1/contract` + `/health`, random port + lockfile, single instance, token-protected shutdown, feature areas mount independently |
| Window | `mxstudio/shell/launcher.py` | pywebview window options pinned — never a JavaScript bridge |
| UI | `mxstudio/ui/` | Arabic RTL default + English toggle, day/night, Crossbar tokens (Appendix I), confirmation dialog for irreversible tools |
| CLI | `python -m mxstudio serve|open|shutdown|status|worker|doctor|kit|update|firstrun|factory|fonts|evals` | non-interactive, JSON output |

## 3 · الأدلة · Evidence
- `tests/mag/core/` + `tests/mag/test_windows_rules.py`: **24 tests** — non-loopback peer refused; CSRF missing/forged refused; secrets never in any response, settings or audit; agent cannot mint a token (no UI session ⇒ 403; `human="agent"` refused); token mismatch / reuse / expiry / forgery refused; lease expiry + crash recovery; idempotent enqueue; retries; budget ceilings; blob tampering detected; ComfyUI placeholder filling; FLUX.1 [dev]-family workflow refused; Arabic path through env to a child; no direct subprocess; no JS bridge; `.bat`/`.cmd` ASCII + quoted `start` titles.
- `tests/mag/browser/studio_ui.test.mjs` (`npm run test:mag-browser`): real Chromium — RTL + `lang=ar`, all 11 tabs, provider/budget/key forms saved and read back, the key value never in the page, language toggle, irreversible tool opens the human dialog and "لأ" cancels. 0 page errors.
- Screenshots: `evidence/ui_home_ar.png`, `evidence/ui_settings_ar.png`.

## 4 · لسه مش متثبّت · Unverified
| Item | How |
|---|---|
| DPAPI round-trip on Windows | `mag-ci / windows` once Actions are enabled; on device via Doctor |
| pywebview window on Windows (WebView2) | installed-app smoke test in `mag-release` + Sandbox runbook (Phase 12) |
| Logo PNG | still the labelled placeholder (Phase 0, D4) |
