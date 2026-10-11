# MAG_PHASE_4_REPORT_AR_EN — المرحلة 4: الخطوط · Phase 4: fonts

> 2026-10-11 · local tag `mag-phase-4` · details: `PHASE_4_NOTES.md`, `evidence/`

**AR:** كتالوج 214 عيلة خطوط من google/fonts متثبّت على commit `bd8f81dd`، سجل تراخيص لكل خط (OFL/Apache/UFL، Reserved Font Names، fsType)، بناءات Office-safe (instances ثابتة بأسماء ستايل صح، وإعادة تسمية لو فيه RFN)، وفحص QA حتمي لكل خط: تغطية العربي والتشكيل والأرقام الهندية، تصادم الحركات، المسافة الآمنة بين السطور، الكشيدة لـ«لـ<اسم>». النتيجة: **206 `certified_print`** و**8 `screen_only`** (خطوط ملوّنة/محدودة) و0 مرفوض. 33 ثيم خطوط (عربي ↔ إنجليزي) كلها عدّت الـvalidator، والمصنع دلوقتي بياخد خطوطه منها (`theme_from_type_theme`). اختيار العميل لخط الاسم/الإهداء (M7) من 12–24 خط بيحددهم المشغّل، والمعاينة بالـfitter الحقيقي. Name Art (حدود/تدرّج/توهّج/ظل) نص حقيقي قابل للتعديل.

**EN:** 214-family catalog pinned to google/fonts `bd8f81dd`, per-font licence ledger, Office-safe builds, deterministic QA → 206 certified_print, 8 screen_only, 0 rejected; 33 validated type themes now feed the factory themes; customer font choice (M7) with a real-fitter preview and a visible fallback note; installation per-user/per-machine with "wait for idle, never kill". New: Studio tools `fonts.list_themes`, `fonts.role_defaults`, `fonts.check_allowed`.

## Measured findings
* LibreOffice turns warped text (`a:prstTxWarp`) into curves ⇒ warp presets are offered only when PowerPoint exports.
* Amiri is not auto-certified for vowelized **body** text (harakat collisions at body size).
* Varela Round reserves «Varela Round» (curly quotes in its OFL header) — recorded in the ledger.

## Evidence
`tests/mag/fonts/` — 123 tests (fixtures: Reem Kufi, Reem Kufi Fun, Blaka, Thabit, Chewy + Amiri/Tajawal, all with licence and provenance; no network). LibreOffice specimen proof: `evidence/specimen_libreoffice_proof.json`.

## Pending on device
Real PowerPoint export per certified font, Windows install (HKCU/HKLM + `AddFontResourceExW`), font visibility to the export account, Name Art warps under PowerPoint, EN A4 derived sizes on printed proofs.
