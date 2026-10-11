# MAG_PHASE_11_REPORT_AR_EN — المرحلة 11: التسويق والمبيعات · Phase 11: marketing & sales outputs

> 2026-10-11 · local tag `mag-phase-11` · code `mxstudio/marketing/` · tests `tests/mag/marketing/` (14)

**AR:** تلات حاجات، كلها وقت التصميم ومن المعتمد بس (مش في مسار الأوردرات):
1. **كتاب معاينة (flipbook)** من الـPDF المعتمد: صور صفحات صغيرة (أطول ضلع ≤ 1100 بكسل ≈ 95 dpi على A4 — حلوة على الموبايل ومش صالحة للطباعة) عليها **علامة مائية مايلة على الصفحة كلها** «معاينة فقط · PREVIEW · ModuleX»، وصفحة HTML بتقلب من اليمين للشمال من غير أي سكريبت خارجي. **ملف الطباعة نفسه عمره ما بيتنسخ** (التست بيتأكد إن مفيش PDF ولا بايتاته في الفولدر).
2. **كاروسيل سوشيال 4:5 (1080×1350) و1:1 (1080×1080)**. عينات القالب (أسماء تجريبية) عادي. أي ملف برّه القالب المعتمد (زي رندر أوردر) بيتعامل إنه فيه **بيانات طفل حقيقي** ومحتاج موافقة صريحة كاملة: `granted=true` + مين وافق + مرجع الموافقة + `social` في النطاق — وإلا بيترفض **قبل** ما أي صورة تترسم. المانيفست بيسجّل مرجع الموافقة بس.
3. **عرض مبيعات للمدارس** 16:9 PowerPoint **قابل للتعديل** بالـrenderer بتاع SlidePoise زي ما هو متصمم، عربي من اليمين للشمال (المرحلة 1): كل كلمة text box حقيقي متظبط بالـfitter، صفحات العينة صور المعاينة بعلامة مائية، والأسعار «مقترحة» (المتجر هو اللي بيقرر).

**EN:** Preview flipbook (watermarked, ≤ 1100 px, self-contained RTL viewer, never the print file); social carousels 4:5 and 1:1 with a consent gate that refuses before rendering; institution sales decks as editable 16:9 Arabic RTL PPTX through the forked renderer. Agent tools: `marketing.flipbook`, `marketing.carousel`, `marketing.sales_deck` (sources: the exact approved PDF blobs of a template set — the factory now stores exported PDFs with the record). UI tab «التسويق والمبيعات».

## Evidence
* `tests/mag/marketing/test_marketing.py` — 14 tests: no PDF/print bytes in the flipbook, size cap enforced, watermark in all four quadrants, exact carousel sizes, 4 incomplete-consent cases refused with nothing written, consent reference recorded, deck spec 16:9 + RTL + aspect-kept pictures, **rendered PPTX: 16:9, every paragraph `rtl="1"`, 3 pictures = 3 samples, LibreOffice export text proof OK**, tools refuse unapproved material, and a negative control (removing the consent check turns the eval red).
* Agent evals: +10 safety scenarios (`child_data_without_consent`, `marketing_unapproved`).
* `evidence/sales_deck_contact_sheet.png` + `sales_deck_proof.json`. Visual review found a bullet «•» rendered at the line end in RTL (`…_before_bullet_fix.png`); bullets are now shapes on the right.

## Pending on device
PowerPoint rendering of the sales deck (fonts installed per Phase 4), the flipbook on the operator's phone/browser, real consent records from the Store/OM (field names agreed through the Kit).
