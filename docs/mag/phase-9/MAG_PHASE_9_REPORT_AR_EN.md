# MAG_PHASE_9_REPORT_AR_EN — المرحلة 9: فحص ما قبل الطباعة · Phase 9: pre-print QA gate

> 2026-10-11 · local tag `mag-phase-9`

**AR:** مكتبة نقية `mxlibs/mx_qagate` بتطلّع **موانع بالاسم** (عربي + إنجليزي) لكل أوردر: مكان صورة فاضي، نص أكبر من مكانه، اسم الطفل مش على الغلاف، عدد صفحات غير المعتمد، صفحة فاضية، PDF صور بس، خط مش معتمد/مش متسطّب. فحوصات الذكاء الاصطناعي (جنس الرسمة، ثبات الملامح، تطابق المشهد، عيوب ظاهرة) **تنبيه بس** وعمرها ما بتغيّر حالة الطباعة. المكتبة مابتكتبش حالة الطباعة خالص: في OM بتتضاف كـchecks جوه `printing/preflight.py` (فلاج `MODULEX_MAG_QA_GATE` مقفول افتراضيًا)، و`print_service.py` يفضل هو الكاتب الوحيد. سجل QA لكل أوردر بيتكتب جنب الـPDF (`…_final.pdf.qa.json`).

**EN:** Pure `mxlibs/mx_qagate` returns named blockers per order; AI checks are advisory only and never change state; the library never writes print state (it feeds OM's preflight behind `MODULEX_MAG_QA_GATE`, default off; `print_service.py` stays the only writer). A per-order QA record is written beside the PDF.

## Evidence — `tests/mag/qa/test_qa_gate.py` (7 tests)
A real order is built end to end in the test (factory template → OM's verbatim replacement → python-pptx injection into the placeholders → LibreOffice export): it passes with no finding. Each blocker is then triggered by a real defect: uninjected deck → `empty_placeholder` (+ `blank_page` for the photo-only back page); approved 16 / wrong child → `page_count`, `child_name_missing`; Pillow picture PDF → `image_only_pdf`; certified set without Tajawal → `font_not_certified` only; an 80× sentence → `text_overflow` (the good deck passes the same fitter). A worried advisory judge leaves `hold` false; the QA record says `advisory_changes_state: false`.
A measured correction: "blank" means featureless **and** paper-white (a full-bleed solid-colour scene is content, not a blank page).

## Pending
Integration with the Console's own `qc_agent.py` / `qc_store.py` / `qa_refs/` is verified by the Kit probe on device (exists? format?) before any hook; the OM preflight hook is Kit patch P-QA (Phase 8).
