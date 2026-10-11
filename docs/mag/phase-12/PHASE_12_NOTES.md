# المرحلة ١٢ — الإصدار والتثبيت والتحديث · Phase 12 — Release, installer, update

> **AR:** المرحلة دي بتسلّم: بناء PyInstaller بفولدر واحد + Node محمول، مثبّت NSIS بنسختين (أونلاين وكاملة)، تحديث تلقائي موقّع بـEd25519 مع رجوع بزرار واحد، الدكتور بـ«إصلاح» لكل سطر أحمر، ويزارد أول تشغيل، وworkflow إصدار على GitHub Actions. كله مجاني: NSIS 3، GitHub Releases، ومفيش شهادة توقيع مدفوعة.
>
> **EN:** This phase delivers the PyInstaller one-folder build + portable Node, a two-flavour NSIS installer (online / Full), Ed25519-signed auto-update with one-click rollback, the Doctor with «إصلاح» per red line, the first-run wizard backend, and the GitHub Actions release workflow. Free-only: NSIS 3, GitHub Releases, no paid certificate.

## ١ · الملفات · Files

| Path | AR | EN |
|---|---|---|
| `installer/pyinstaller/MagazineStudio.spec` | exe-ين windowed (`ModuleX Magazine Studio.exe` و `mxstudio-cli.exe`) بيشاركوا `_internal` واحد؛ وضع UTF-8؛ مفيش Ghostscript/Poppler | two windowed exes sharing one `_internal`; UTF-8 mode; Ghostscript/Poppler excluded |
| `installer/pyinstaller/build_windows.ps1` (ASCII) | venv بنسخ مثبّتة ← PyInstaller ← Node المحمول (بصمة مثبّتة) ← `npm ci --omit=dev` ← smoke للدكتور | pinned venv → PyInstaller → pinned portable Node → `npm ci --omit=dev` → doctor smoke |
| `installer/pyinstaller/requirements-windows.txt`, `entry_gui.py`, `entry_cli.py` | الاعتماديات المثبّتة ونقاط الدخول | pins and entry points |
| `installer/nsis/MagazineStudio.nsi` | `-DFLAVOUR=online|full`، `/RELAUNCH=1`، استخراج LibreOffice من غير أدمن في الكاملة، حفظ المثبّت للرجوع | flavours, relaunch, no-admin LibreOffice extraction (Full), installer kept for rollback |
| `installer/downloads.json` | كل تنزيل ببصمته؛ اللي لسه مش مثبّت مكتوب عليه **TO-PIN** | every download with its pin; open items marked **TO-PIN** |
| `installer/fetch_offline_payload.py` | بيجمع محتوى النسخة الكاملة؛ صارم افتراضيًا | collects the Full payload; strict by default |
| `installer/windows_sandbox/*` | `.wsb` + سكريبتات الإثبات (نفسها smoke الـCI) | `.wsb` + proof scripts (also the CI smoke) |
| `mxstudio/update/` | الـmanifest، التوقيع، التنزيل المستأنف، آلة الحالات، الرجوع، CLI | manifest, signing, resumable download, state machine, rollback, CLI |
| `mxstudio/doctor/` | ١٣ فحص + ١٠ إصلاحات، كله عن طريق `DoctorContext` قابل للاستبدال | 13 checks + 10 fixers behind an injectable `DoctorContext` |
| `mxstudio/firstrun/` | الويزارد (مساحة العمل ← المزوّدين ← الاكتشاف ← الدكتور) + محرّك أوفيس | wizard + Office engine |
| `.github/workflows/mag-release.yml` | windows-latest يبني ← ubuntu-latest يعمل المثبّتين ← windows-latest يثبّت ويفحص ويشيل ← إصدار | build → installers → smoke → release |
| `tests/mag/release/` | ١٠٦ اختبار، كل ملف فيه negative control | 106 tests, each file with negative controls |

## ٢ · قرارات · Decisions

1. **AR:** المثبّتين بيتبنوا على ubuntu-latest (`apt nsis`) من artifact الـPyInstaller اللي اتبنى على windows-latest، وبعدين بيتثبّتوا `/S` على windows-latest. **EN:** installers are built on ubuntu-latest from the Windows PyInstaller artifact and installed silently on windows-latest.
2. **AR:** `latest.json` موقّع بـEd25519 على البايتات الـcanonical (مفاتيح مترتبة، UTF-8). المفتاح الخاص في السر `MXS_UPDATE_SIGNING_KEY` بس، وبيظهر في job الإصدار بس؛ المفتاح العام بيتحط في `trust.json` وقت البناء من المتغيّر `MXS_UPDATE_PUBLIC_KEY`. لو مفيش سر: مفيش `latest.json` والتحديث التلقائي مقفول — وده مكتوب كتحذير في الـrun. **EN:** canonical-bytes Ed25519 signature; private key only in the release job's secret; the public key is embedded at build time; without the secret no `latest.json` is published (warning, not silence).
3. **AR:** التحديث بيتعرض بس لو النسخة أحدث بجد ومش في `skipped_versions`؛ بيتثبّت في الفتحة الجاية **بموافقة** بس؛ الموافقة بتتمسح بعد كل محاولة (مفيش loop)؛ الملف بيتراجع ببصمته قبل التشغيل؛ الرجوع بيستخدم المثبّت القديم المحفوظ بعد ما يتأكد من بصمته. **EN:** only strictly newer, non-skipped versions; consent-gated apply on next launch; consent cleared per attempt; hash re-checked right before execution; rollback re-verifies the kept installer.
4. **AR:** LibreOffice: PowerPoint الأول؛ وإلا `msiexec /a … /qn TARGETDIR=<فولدر البرنامج>\libreoffice` من غير أدمن؛ وإلا شرح UAC بالعربي وموافقة قبل `msiexec /i … ALLUSERS=1`. **EN:** PowerPoint first; else no-admin administrative extraction; else Arabic UAC explanation and consent before a per-machine install.
5. **AR:** النسخة الكاملة بترفض تتبني لو في TO-PIN (إلا بـdispatch يدوي `allow_unpinned`، وساعتها `offline_manifest.json` بيكتب `pinned: false` أو `missing` — مفيش ادعاء). **EN:** the Full build is strict about TO-PIN; a manual `allow_unpinned` dispatch records `pinned: false` / `missing` honestly.
6. **AR:** الـCLI exe نافذته مخفية (console=False)، فكل أوامر الخلفية بتقبل `--out FILE`. **EN:** the CLI exe is windowed, so background commands accept `--out FILE`.
7. **AR:** tag الإصدار `mxs-v<APP_VERSION>` (مش `v*` علشان ما يتضاربش مع `release.yml` بتاع SlidePoise)، والـworkflow بيرفض لو الرقم مختلف عن `mxstudio.config.APP_VERSION`. **EN:** tags `mxs-v*` avoid the upstream `release.yml` (`v*`); the version must equal `APP_VERSION`.

## ٣ · استثناءات موثّقة · Documented exceptions

- **AR:** `msiexec` مبيقراش متغيّرات بيئة، فمسار الـMSI و TARGETDIR بيتبعتوا في argv — عن طريق `mxstudio.proc` (CreateProcessW، UTF-16، من غير cmd.exe). **EN:** `msiexec` cannot read env vars, so MSI/TARGETDIR are argv items via `mxstudio.proc` (CreateProcessW, never cmd.exe).
- **AR:** طلب الـUAC (`ShellExecuteExW "runas"`) مينفعش يتعمل بـsubprocess، فهو في `firstrun/office.py` وبيشتغل بموافقة بس. يُفضّل ينتقل لـ`mxstudio.proc.run_elevated`. **EN:** the UAC request uses `ShellExecuteExW("runas")` in `firstrun/office.py`, consent-only; better moved into `mxstudio.proc.run_elevated`.
- **AR:** WebView2 bootstrapper بيتغيّر مع كل إصدار من مايكروسوفت، فبيتراجع بتوقيع Authenticode (Microsoft Corporation) بدل بصمة ثابتة. **EN:** the evergreen WebView2 bootstrapper is verified by Authenticode, not a pinned hash.

## ٤ · اللي اتثبت هنا · Proven in this session (Linux container)

| | AR | EN |
|---|---|---|
| NSIS | النسختين اتبنوا بـ`makensis 3.09 -WX` (صفر تحذيرات) بـpayload تجريبي وأسماء عربي | both flavours compile with `-WX` (0 warnings) |
| PyInstaller | بناء تجريبي للـspec على Linux نجح؛ `mxstudio-cli doctor --json --out` من النسخة المجمّدة: python و pypdfium2 و office و workspace و **arabic_path (كتابة + عملية فرعية مجمّدة + Node)** أخضر | trial Linux build of the spec; frozen CLI doctor green on the Arabic-path round-trip incl. a frozen child process |
| Update | توقيع/تحقق، رفض ٥ أنواع تلاعب، رفض توقيع منقول، دورة كاملة لحد applied، فشل التطبيق من غير loop، استئناف بعد قطع بـRange، رجوع وحماية من تلاعب المثبّت القديم | sign/verify, tamper rejection, full cycle, no-loop failure, Range resume, rollback + tamper refusal |
| Node pin | `node-v22.23.3-win-x64.zip` = `2b0ff57b…ed71` من `nodejs.org/dist/v22.23.3/SHASUMS256.txt` | pinned from the official SHASUMS256 |

## ٥ · مستني إثبات على الجهاز / الـCI · Pending on-device / CI proof

**AR:** (أ) تشغيل `mag-release.yml` على GitHub (Actions لسه مقفولة على الـfork)؛ (ب) `msiexec /a` كمستخدم عادي (job `standard-user-proof` + الرنبوك §٥)؛ (ج) الويزارد العربي و SmartScreen؛ (د) تحديث ورجوع بين نسختين حقيقيتين؛ (هـ) بصمات LibreOffice وخزنة الخطوط وحزم الأشكال (TO-PIN — الـLibreOffice download.documentfoundation.org مش متاح من الكلاود هنا). خطوة الـProof Runner: `docs/mag/phase-12/CLEAN_INSTALL_RUNBOOK_AR_EN.md` §٤.

**EN:** (a) a real `mag-release.yml` run (Actions still disabled on the fork); (b) `msiexec /a` as a standard user; (c) Arabic wizard and SmartScreen; (d) update/rollback between two real versions; (e) pins for LibreOffice, font vault, shape packs (TO-PIN — download.documentfoundation.org is blocked from this cloud). Proof Runner step: runbook §4.

## ٦ · المطلوب من باقي الفريق · Needed from other modules

| AR | EN |
|---|---|
| `mxstudio/__main__.py` يعمل `main(argv)` ويوزّع: `doctor` ← `mxstudio.doctor.main`، `update` ← `mxstudio.update.main`، `firstrun` ← `mxstudio.firstrun.main` (كل واحدة بتاخد باقي الـargv). | `mxstudio/__main__.py:main(argv)` dispatches `doctor`/`update`/`firstrun` to each package's `main(argv[1:])`. |
| أمر `open` يبدأ بـ`if mxstudio.update.launch_hook(): return 0`. | `open` first calls `mxstudio.update.launch_hook()` and exits when it returns True. |
| أمر `shutdown` يقفل السيرفر بهدوء ويرجع 0 حتى لو مفيش سيرفر شغّال (المثبّت بيناديه قبل الاستبدال والإزالة). | `shutdown` stops the server gracefully, exits 0 when nothing runs (the installer calls it). |
| السيرفر: `Wizard(secret_store=<DPAPI store with put(name, secret) -> fingerprint>)`؛ endpoints للدكتور (`run_all`, `run_fix(fix_id, consent=…)`) وللتحديث (`UpdateManager().check/download/stage/consent/rollback`) في thread خلفي؛ الـUI يقرا `<app_home>/update/progress.json`. | Server: wire the DPAPI store into `Wizard`; expose Doctor and update endpoints; poll `progress.json`. |
| `pyproject.toml`: إضافة `cryptography` و `pypdfium2` للـextras (`runtime`)، و`pyinstaller`/`pywebview` لو اتعمل extra `windows`. | add `cryptography`, `pypdfium2` to the `runtime` extra. |
| `release.yml` بتاع SlidePoise: `make_latest: false` أو ريبو إصدارات منفصل، علشان رابط `releases/latest/download/…` يفضل للاستوديو. | upstream `release.yml`: `make_latest: false`, or use a releases-only repo, so `releases/latest` stays the Studio's. |
| `renderer`: يدوّر على Node في `<app_dir>/node/node.exe` و `<app_dir>/node/node_modules` (أو `MXS_NODE` / `MXS_NODE_MODULES`)، والـskill في `_internal/skill/slidepoise`. | renderer: Node at `<app_dir>/node/`, skill resources at `_internal/skill/slidepoise`. |
