# MAG_PHASE_12_REPORT_AR_EN — المرحلة 12: الإصدار والتثبيت والتحديث · Phase 12: release, installer, updates

> 2026-10-11 · local tag `mag-phase-12` · details: `PHASE_12_NOTES.md`, `CLEAN_INSTALL_RUNBOOK_AR_EN.md`

**AR:** بناء PyInstaller بفولدر واحد + Node محمول ببصمة مثبّتة؛ مثبّت **NSIS** (مجاني، بدل Inno Setup) بنسختين: أونلاين (`ModuleX-MagazineStudio-Setup-<ver>.exe`) وكاملة أوفلاين (`…-Full.exe`)؛ per-user من غير أدمن، البرنامج في `%LOCALAPPDATA%\Programs\ModuleX Magazine Studio` (برّه `C:\المشروع`)، وLibreOffice بيتفك من غير أدمن بـ`msiexec /a`. تحديث تلقائي بـ`latest.json` موقّع **Ed25519** (المفتاح الخاص عمره ما بيدخل الريبو — بيتعمل عند المشغّل ويتحط secret في CI)، تنزيل في الخلفية، تحقق، تثبيت عند التشغيل الجاي **بموافقتك**، ورجوع بزرار واحد. الدكتور: 13 فحص و10 «إصلاح». ويزارد أول تشغيل. Workflow على GitHub Actions: windows-latest يبني ← ubuntu يعمل المثبّتين ← windows يثبّت ويفحص ويشيل ← GitHub Release.

**EN:** One-folder PyInstaller build + pinned portable Node; two-flavour NSIS installer; per-user, program outside the project folder; LibreOffice extracted without admin. Ed25519-signed `latest.json` updates with consent and one-click rollback (the API's rollback is an irreversible tool needing a human confirmation token). Doctor (13 checks, 10 fixers), first-run wizard (secrets stored with DPAPI, only `sha256[:8]` fingerprints ever shown). Release workflow `.github/workflows/mag-release.yml`; upstream `release.yml` now uses `make_latest: false` so `releases/latest/download/ModuleX-MagazineStudio-Setup.exe` stays the Studio's stable link.

Integrated in this commit: `mxstudio/{doctor,update,firstrun}/api.py` (Studio routes/tools), `python -m mxstudio open` runs the update launch hook first, and `mxstudio/runtime_paths.py` so the installed app finds `node/node.exe`, `node/node_modules` (NODE_PATH) and runs the renderer's post-processor through `mxstudio-cli.exe <script.py>` (only scripts inside the packaged skill).

## Evidence
`tests/mag/release/` — 109 tests (manifest signing/verification with negative controls, resumable download, state machine, rollback, Doctor fixers through an injectable context, NSIS script compiled with `makensis` on Linux for both flavours, ASCII-only `.bat`/`.ps1`, frozen-layout path resolution).

## Pending · مستني
(a) a real `mag-release.yml` run — **GitHub Actions are disabled on the fork; the operator enables them**; (b) `msiexec /a` as a standard user; (c) Arabic wizard + SmartScreen (no paid certificate; SignPath Foundation is the free route later); (d) update/rollback between two real versions; (e) TO-PIN entries in `installer/downloads.json` (LibreOffice MSI, font vault, shape packs). Operator secrets: `MXS_UPDATE_SIGNING_KEY` (secret) and `MXS_UPDATE_PUBLIC_KEY` (variable).
