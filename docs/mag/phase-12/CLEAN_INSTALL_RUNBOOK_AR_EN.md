# رنبوك التثبيت على جهاز نضيف · Clean-install runbook

> **AR:** الرنبوك ده بيثبت إن «مديول إكس · استوديو المجلات» بيتثبّت ويشتغل ويتشال على جهاز ويندوز نضيف، من غير صلاحيات مدير، وإن مساحة العمل بتفضل زي ما هي بعد الإزالة. نفس السكريبت اللي بيشتغل هنا هو اللي بيشغّله الـCI على `windows-latest` (job `smoke-windows`).
>
> **EN:** This runbook proves that ModuleX Magazine Studio installs, runs and uninstalls on a clean Windows machine without admin rights, and that the workspace survives uninstall. The same script is the CI installed-app smoke test on `windows-latest` (job `smoke-windows`).

الملفات · Files: `installer/windows_sandbox/MagazineStudio.wsb`, `sandbox_logon.cmd`, `sandbox_proof.ps1`, `standard_user_proof.ps1` (كلها ASCII · all ASCII-only).

---

## ١ · المتطلبات · Prerequisites

| | AR | EN |
|---|---|---|
| ويندوز | Windows 10/11 **Pro أو Enterprise** مفعّل فيه «Windows Sandbox» (Turn Windows features on or off ← Windows Sandbox). نسخة Home مفيهاش Sandbox — استخدم VM نضيفة أو حساب مستخدم عادي جديد بدالها (القسم ٨). | Windows 10/11 Pro or Enterprise with the *Windows Sandbox* feature enabled. Home has no Sandbox — use a clean VM or a new standard user instead (section 8). |
| الملفات | المثبّتين `ModuleX-MagazineStudio-Setup-<ver>.exe` و `…-Full.exe` و `SHA256SUMS` من صفحة الإصدار. اختياري: ملف MSI بتاع LibreOffice الرسمي. | Both installers and `SHA256SUMS` from the release page; optional: the official LibreOffice MSI. |
| الإنترنت | مطلوب بس للنسخة الأونلاين لما تنزّل LibreOffice/الخطوط. | Only the online flavour needs it, for on-demand downloads. |

روابط مباشرة ثابتة · Stable direct links (always the latest release):

```
https://github.com/<owner>/<repo>/releases/latest/download/ModuleX-MagazineStudio-Setup.exe
https://github.com/<owner>/<repo>/releases/latest/download/ModuleX-MagazineStudio-Setup-Full.exe
https://github.com/<owner>/<repo>/releases/latest/download/SHA256SUMS
```

`<owner>/<repo>` = `modulix0025-dev/slidepoise` أو الريبو المخصّص للإصدارات لو اتضبط `vars.MXS_RELEASE_REPO` · or the releases-only repo when `vars.MXS_RELEASE_REPO` is set.

## ٢ · تأكيد البصمة قبل أي حاجة · Verify the SHA256 first

**AR:** المثبّت **مش موقّع بشهادة مدفوعة** (قرار المشغّل: مفيش أي حاجة ليها ترخيص تجاري). الأمان بييجي من بصمة SHA256 المنشورة ومن ملف `latest.json` الموقّع بـEd25519 اللي البرنامج بيتحقق منه في التحديثات. اعمل كده في PowerShell:

**EN:** The installer carries **no paid code-signing certificate** (operator decision). Integrity comes from the published SHA256 and from the Ed25519-signed `latest.json` the app verifies for updates. In PowerShell:

```powershell
Get-FileHash .\ModuleX-MagazineStudio-Setup.exe -Algorithm SHA256
Select-String -Path .\SHA256SUMS -Pattern "ModuleX-MagazineStudio-Setup.exe"
```

لازم الرقمين يكونوا متطابقين حرف بحرف (Get-FileHash بيكتب بحروف كبيرة — ده عادي) · The two hashes must match (Get-FileHash prints upper case; compare case-insensitively).

### SmartScreen

**AR:** أول مرة ممكن ويندوز يقول «Windows protected your PC». ده متوقّع لأن مفيش شهادة مدفوعة. **بعد** ما البصمة تطابق: اضغط **More info** ← **Run anyway**. لو البصمة مش مطابقة: متشغّلش الملف وامسحه.

**EN:** SmartScreen may show “Windows protected your PC”. This is expected without a paid certificate. **Only after** the hash matches: **More info → Run anyway**. If it does not match, do not run the file; delete it.

**AR (لاحقًا):** لو اتضبط توقيع SignPath Foundation المجاني (مشروع مفتوح المصدر بترخيص OSI)، الـworkflow هيوقّع تلقائي والتحذير هيقلّ. لحد دلوقتي مش مضبوط. · **EN (later):** if the free SignPath Foundation integration is configured, the workflow signs automatically; it is not configured yet.

## ٣ · تجهيز الـSandbox · Prepare the Sandbox

```
C:\ModuleX-Sandbox\              <- copy here:
    MagazineStudio.wsb  sandbox_logon.cmd  sandbox_proof.ps1  standard_user_proof.ps1
    ModuleX-MagazineStudio-Setup-<ver>.exe
    ModuleX-MagazineStudio-Setup-<ver>-Full.exe      (optional)
    SHA256SUMS
    LibreOffice_<ver>_Win_x86-64.msi                 (optional: standard-user MSI proof)
C:\ModuleX-Sandbox-Results\      <- empty folder (results are written here)
```

**AR:** المسارات دي مكتوبة جوه ملف `.wsb` بحروف إنجليزي عن قصد (ملفات الـSandbox لازم تبقى ASCII). مساحة العمل العربي `C:\المشروع\ModuleX_MagazineStudio_Data` بتتعمل **جوه** الـSandbox بالسكريبت نفسه علشان نختبر المسار العربي.

**EN:** These host paths are ASCII on purpose (Sandbox files are ASCII-only). The Arabic workspace `C:\المشروع\ModuleX_MagazineStudio_Data` is created **inside** the Sandbox by the proof script to exercise the Arabic path.

## ٤ · التشغيل · Run

1. دبل-كليك على `C:\ModuleX-Sandbox\MagazineStudio.wsb` · double-click the `.wsb`.
2. **AR:** السكريبت بيشتغل مخفي (من غير شبّاك كونسول). استنى لحد ما Notepad يفتح بـ`summary.txt` (من ٥ لـ٢٠ دقيقة حسب النسخة الكاملة و LibreOffice). · **EN:** the proof runs hidden; wait until Notepad opens `summary.txt` (5–20 min).
3. النتايج كمان في · results also in `C:\ModuleX-Sandbox-Results\` (`results.json`, `doctor-online.json`, `doctor-full.json`, `standard-user\standard_user_proof.json`, `msi.log`).

### معنى كل سطر · What each line proves

| سطر · line | AR | EN |
|---|---|---|
| `sha256 <file>` | البصمة مطابقة لـSHA256SUMS | hash matches SHA256SUMS |
| `online install` | `Setup.exe /S` اتثبّت لحساب المستخدم في `%LOCALAPPDATA%\Programs\ModuleX Magazine Studio` ومعاه `mxstudio-cli.exe` | per-user silent install, both exes present |
| `online doctor` | الدكتور اشتغل من البرنامج المتثبّت: python و node و pypdfium2 و webview2 و workspace و **arabic_path** (كتابة/قراءة + عملية فرعية + Node على مسار عربي) كلهم أخضر | Doctor from the installed app: python, node, pypdfium2, webview2, workspace and the Arabic-path round-trip are green |
| `online uninstall` | `uninstall.exe /S` شال فولدر البرنامج، و**ساب** مساحة العمل وبيانات الاستوديو (السؤال افتراضيه «لأ») | program folder removed; workspace and app data kept (default No) |
| `full install/doctor/uninstall` | نفس الكلام للنسخة الكاملة، وكمان سطر **office** لازم يبقى أخضر (LibreOffice اتفك من غير صلاحيات مدير) | same for Full, plus **office** must be green (LibreOffice unpacked without admin) |
| `standard user` | شوف القسم ٥ | see section 5 |

**AR:** الـSandbox بيكون فيه أوفيس؟ لأ — فده بالظبط سيناريو «مفيش PowerPoint». أنظمة OM/الكونسول/المتجر (8000/6060/8200) هتطلع أحمر في الدكتور جوه الـSandbox وده طبيعي، والسكريبت مش بيحسبها.

**EN:** The Sandbox has no Office — exactly the “no PowerPoint” case. OM/Console/Store (8000/6060/8200) are red inside the Sandbox by design and are not counted.

## ٥ · إثبات المستخدم العادي · Standard-user proof

**AR:** حساب الـSandbox (`WDAGUtilityAccount`) أدمن، فـ`standard_user_proof.ps1` بيعمل مستخدم مؤقت **عادي** (`mxsstd`، عضو في Users بس)، ويشغّل كمستخدم ده — عن طريق Scheduled Task بـ`RunLevel Limited` (عمره ما يتعمله elevation):

1. `msiexec /a LibreOffice.msi /qn TARGETDIR=C:\mxs-proof\lo` — **استخراج إداري** للـMSI الرسمي (بيكتب ملفات بس، مش بيسجّل حاجة في النظام).
2. `Setup.exe /S` — تثبيت الاستوديو لحسابه، وبعدين `mxstudio-cli.exe doctor`.

وبيكتب `standard_user_proof.json` فيه: `is_admin` (لازم `false`)، `msi_exit` (لازم `0`)، مسار `soffice.exe` ونسخته، `setup_exit`، ووجود تقرير الدكتور. وفي الآخر بيمسح المستخدم والـtask.

**EN:** The Sandbox account is an administrator, so `standard_user_proof.ps1` creates a throw-away **standard** user (`mxsstd`, member of Users only) and runs, as that user, through a Scheduled Task with `RunLevel Limited` (never elevated): (1) the **administrative extraction** of the official MSI, (2) the per-user Studio install + Doctor. It records `is_admin` (must be `false`), `msi_exit` (`0`), the `soffice.exe` path/version, `setup_exit` and the Doctor report, then removes the user and the task. The same script runs in CI job `standard-user-proof` (it does not block a release; its JSON is attached to the run).

**AR:** لو الاستخراج ما نجحش على جهاز معيّن، البرنامج بيعرض شرح UAC بالعربي ويطلب موافقتك قبل ما يعمل تثبيت لكل الأجهزة (`msiexec /i … ALLUSERS=1`)، أو استخدم النسخة الكاملة. · **EN:** if extraction fails on a given PC, the app shows an Arabic UAC explanation and asks before a per-machine install, or use the Full installer.

## ٦ · تجربة يدوية جوه الـSandbox · Manual checks inside the Sandbox

1. ثبّت الأونلاين (دبل-كليك، من غير `/S`): الويزارد عربي، مفيش صفحة اختيار فولدر، ومفيش طلب صلاحيات مدير. · Install interactively: Arabic wizard, no directory page, no UAC.
2. افتح البرنامج: أول تشغيل ← مساحة العمل (الافتراضي `C:\المشروع\ModuleX_MagazineStudio_Data`، وتقدر تغيّره — بس مش جوه فولدر البرنامج) ← المزوّدين (اختياري) ← الاكتشاف عن طريق الـKit (اختياري) ← الدكتور. · First run: workspace → providers → discovery → Doctor.
3. في الدكتور، كل سطر أحمر جنبه «إصلاح». جرّب «إصلاح» على سطر المكتب (office): الأونلاين هينزّل LibreOffice بنسبة مئوية بالأرقام العربي ويكمّل من مكان ما وقف لو النت قطع. · Each red line has «إصلاح»; the office fix downloads LibreOffice with Arabic progress and resumes after a cut.
4. شيل البرنامج من Settings ← Apps: السؤال «تمسح بيانات استوديو المجلات؟» الافتراضي **لأ**. · Uninstall: the data question defaults to **No**.

## ٧ · التحديث والرجوع · Update and rollback

**AR:**
1. ثبّت نسخة N (الأونلاين). المثبّت بيحتفظ بنسخة منه في `%LOCALAPPDATA%\ModuleX\MagazineStudio\update\installers\`.
2. لما تنزل N+1، البرنامج بيقرا `latest.json`، يتحقق من توقيع Ed25519 بالمفتاح العام اللي جوه البرنامج، وينزّل في الخلفية (بيكمّل بعد أي قطع) ويتحقق من SHA256، ويجهّزه.
3. بيسألك: «ثبّت عند الفتح الجاي؟». لو وافقت، أول ما تفتح البرنامج تاني بيقفل ويشغّل المثبّت `/S /RELAUNCH=1` ويرجع يفتح على N+1.
4. «رجوع للنسخة السابقة» (زرار واحد): بيشغّل مثبّت N المحفوظ بعد ما يتأكد من بصمته، ومش هيعرض N+1 تاني (لكن هيعرض N+2 لو نزلت).

**EN:** install N (it keeps a copy of itself); N+1 is found through the signed `latest.json`, downloaded in the background (resumable), sha256-verified and staged; it installs on the next launch **only with consent** (`/S /RELAUNCH=1`); one-click rollback re-runs the kept N installer after re-verifying its hash and skips N+1 (a later N+2 is offered again). CLI equivalent: `mxstudio-cli.exe update check|download|stage|consent|status|rollback --out FILE`.

## ٨ · من غير Sandbox · Without Windows Sandbox (Home edition)

**AR:** اعمل حساب مستخدم **عادي** جديد (Settings ← Accounts ← Other users)، ادخل بيه، وشغّل المثبّت بالإيد، وبعدين من PowerShell عادي (مش Run as administrator):
**EN:** create a new **standard** user, sign in with it, run the installer, then in a normal (non-elevated) PowerShell:

```powershell
& "$env:LOCALAPPDATA\Programs\ModuleX Magazine Studio\mxstudio-cli.exe" doctor --json --out "$env:TEMP\doctor.json"
Start-Sleep 5; Get-Content "$env:TEMP\doctor.json"
```

(`mxstudio-cli.exe` نافذته مخفية دايمًا، علشان كده النتيجة بتتكتب في ملف · the CLI is windowed/hidden by design, so results go to a file.)

## ٩ · قبل أول إصدار · Before the first release (operator actions)

| # | AR | EN |
|---|---|---|
| 1 | فعّل GitHub Actions على الـfork (تبويب Actions). | Enable Actions on the fork. |
| 2 | `python -m mxstudio.update keygen --out-private key.txt` على جهازك؛ حط محتوى `key.txt` في السر `MXS_UPDATE_SIGNING_KEY`، والمفتاح العام في المتغيّر `MXS_UPDATE_PUBLIC_KEY`، وامسح `key.txt`. | Generate the Ed25519 pair; private → secret `MXS_UPDATE_SIGNING_KEY`, public → variable `MXS_UPDATE_PUBLIC_KEY`; delete the file. |
| 3 | ثبّت قيم `TO-PIN` في `installer/downloads.json` (نسخة LibreOffice ورابطها وبصمتها وحجمها؛ خزنة الخطوط؛ حزم الأشكال). لحد ما تتثبّت: الـtag build بيرفض يبني النسخة الكاملة، والبرنامج بيرفض ينزّلها. | Pin the `TO-PIN` values; until then the tag build refuses the Full flavour and the app refuses those downloads. |
| 4 | (اختياري) لو الريبو هيبقى private: ريبو إصدارات عام + `vars.MXS_RELEASE_REPO` + `secrets.MXS_RELEASE_TOKEN`. | Optional releases-only public repo. |
| 5 | `git tag mxs-v<APP_VERSION>` و push — رقم النسخة لازم يساوي `mxstudio.config.APP_VERSION`. | Tag `mxs-v<APP_VERSION>` and push. |

## ١٠ · اللي لسه محتاج إثبات على الجهاز · Pending on-device proof

**AR (بصراحة):** لحد ما الـCI على ويندوز يشتغل أو الرنبوك ده يتعمل، الحاجات دي **مستنية إثبات على الجهاز**: (أ) إن `msiexec /a` بيشتغل كمستخدم عادي مع نسخة LibreOffice اللي هتتثبّت؛ (ب) شكل الويزارد العربي و SmartScreen على ويندوز حقيقي؛ (ج) التحديث والرجوع من نسخة لنسخة على جهاز المشغّل؛ (د) الدكتور جنب OM/الكونسول/المتجر الحقيقيين. خطوة الـProof Runner: شغّل القسم ٤ وابعت `C:\ModuleX-Sandbox-Results\`.

**EN (honest):** until Windows CI runs or this runbook is executed, these are **pending on-device proof**: (a) `msiexec /a` as a standard user with the pinned LibreOffice version; (b) the Arabic wizard and SmartScreen on real Windows; (c) update/rollback between two real versions; (d) the Doctor next to the real OM/Console/Store. Proof Runner step: run section 4 and send back `C:\ModuleX-Sandbox-Results\`.
