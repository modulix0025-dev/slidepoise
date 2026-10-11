# النسخة الكاملة فيها كل حاجة · The Full installer carries everything

> 2026-10-11 · طلب المشغّل: «ضيف في التحميل: البرنامج + LibreOffice + الخطوط + حزم الأشكال»

## ١ · جوه الـFull إيه · What is inside `…-Full.exe`

| الجزء · Part | المصدر · Source | التثبيت · Pin | بيتسطّب فين · Lands in |
|---|---|---|---|
| البرنامج · the app | PyInstaller one-folder | sha256 of the installer (SHA256SUMS) | the folder you choose |
| LibreOffice (محرّك التصدير لو مفيش PowerPoint) | download.documentfoundation.org, series «still» | the sha256 **TDF publishes** next to the MSI (`.sha256` / `.mirrorlist`), never a hash computed from the bytes alone | `<app>\offline\libreoffice\…msi`; unpacked without admin into `<app>\libreoffice` **only when PowerPoint is absent** |
| خزنة الخطوط · font vault | google/fonts at the catalog's commit | every font file and licence file by sha256 (`catalog/fonts/catalog.json`) | `<app>\offline\fonts`, then **installed for your Windows user** (HKCU, no admin) |
| حزم الأشكال · shape packs | official `@iconify-json` packages on npm | each tarball by sha256 + npm sha512 (`catalog/shapes/packs.json`) | `<app>\offline\shapes`, searched in place, no internet needed |

**AR:**
* **الخطوط:** 214 عيلة خطوط مجانية، يعني 311 ملف خط، منهم 104 بيدعموا العربي. كل عيلة جنبها ملف الرخصة بتاعها (OFL أو Apache). الـSetup بيسطّبهم لحسابك على ويندوز من غير صلاحيات مدير، فبيظهروا في PowerPoint وLibreOffice على طول.
* **الأشكال:** 5 مجموعات مسموحة للطباعة: Noto Emoji وFluent Emoji Flat وTwemoji وPhosphor وRemix Icon. Remix مسموح لحد نسخة 4.8.0 بس. Twemoji رخصتها CC-BY، فاسمها بيتكتب في صفحة الاعتمادات. البحث عن شكل شغّال من غير نت. أي شكل لسه لازم توافق عليه قبل ما يدخل المكتبة.
* **Lucide وTabler مش موجودين:** رسوماتهم خطوط رفيعة بس من غير مساحة ملوّنة، والاستوديو بيخزّن الأشكال كمساحات ملوّنة، فماينفعوش. لو اخترت شكل زي ده من النت، هيقولك السبب بدل رسالة خطأ غامضة.
* **LibreOffice:** بيتفك بس لو مفيش PowerPoint على الجهاز، لأن PowerPoint أدق في التصدير.
* **لما تشيل البرنامج:** فولدر البرنامج بيتمسح، لكن الخطوط بتفضل متسطّبة لحسابك علشان ملفاتك القديمة تفضل تفتح صح.

**EN:**
* **Fonts:** 214 free families, 311 font files, 104 of them cover Arabic, each with its licence file. The installer registers them for the current user (no admin), so PowerPoint and LibreOffice see them immediately.
* **Shapes:** five print-safe sets (Noto Emoji, Fluent Emoji Flat, Twemoji, Phosphor, Remix Icon). Remix is accepted only up to 4.8.0. Twemoji is CC-BY, so it goes on the credits page. Shape search works offline, and every icon still needs your approval before it enters the library.
* **Lucide and Tabler are left out:** they are stroke-only, and the library stores filled geometry. Picking such an icon online now gives a named reason (`NO_FILLED_AREA`).
* **LibreOffice** is unpacked only when PowerPoint is absent.
* **Uninstalling** removes the program folder; the per-user fonts stay so existing documents keep rendering.

## ٢ · النسخة الأونلاين · The Online flavour

**AR:** النسخة الصغيرة مش جواها الحاجات دي. أول ما تفتح البرنامج، الدكتور هيقولك إن الخطوط أو الأشكال ناقصة. دوس «إصلاح»، وهو هينزّل نفس الملفات، كل ملف لوحده ومتطابق ببصمته، ويسطّب الخطوط لحسابك. قبل كده الزرار ده ماكانش شغّال، لأن الخطوط والأشكال كانت لسه TO-PIN.

**EN:** The small installer does not contain these parts. The Doctor's «إصلاح» assembles the same bundles from the same pins, file by file, and installs the fonts for the user. Before this change that button refused, because the bundles were still TO-PIN.

## ٣ · إزاي اتأكدنا · How it is proven

* `tests/mag/release/test_asset_bundles.py` covers:
  * every recipe input pinned at one commit;
  * licence policy and version caps;
  * wrong bytes refused and nothing written;
  * no path escapes the bundle;
  * the licence inside each tarball must equal the pinned one;
  * offline search follows the online licence rules;
  * import needs approval;
  * per-user font install, with a broken file named and not blocking the rest;
  * the Doctor prefers the Full copy;
  * NSIS and CI wiring.
* Local real build from the real sources:
  * font vault: 525 files verified (311 fonts + 214 licences, 76 MB);
  * shape packs: 5 sets, 15 files;
  * Doctor: "Font vault: 311 fonts (104 with Arabic)" and "Shape packs: 5 sets".
* Windows proof (`installer/windows_sandbox/sandbox_proof.ps1`, run by the release workflow): the Full install must report
  * Doctor `office`, when LibreOffice is in the build;
  * Doctor `fonts` green;
  * `shapes` ok;
  * `fonts-install.json` with fonts installed.

## ٤ · LibreOffice والتثبيت الدائم · Making the LibreOffice pin permanent

**AR:** مكان الشغل اللي بنبني منه مش قادر يوصل لموقع LibreOffice، فالتثبيت بيتعمل على GitHub. بناء الفرع بيشغّل `installer/pin_libreoffice.py`، ويطبع سطر `LIBREOFFICE_PIN {...}` فيه النسخة والبصمة اللي TDF نشرتها. القيمة دي بتتحفظ في `installer/downloads.json`، وبعد كده أي إصدار بـtag بيستخدمها ومش بيقبل أي ملف غيرها.

**EN:** The cloud workspace cannot reach TDF, so the pin is taken on GitHub's runner. A branch build runs `installer/pin_libreoffice.py`, which prints `LIBREOFFICE_PIN {...}` with the TDF-published sha256. That value is committed to `installer/downloads.json`, so tag builds stay strict.
