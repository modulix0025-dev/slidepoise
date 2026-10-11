# MAG_PHASE_7_REPORT_AR_EN — المرحلة 7: ثيمات ومنتجات جديدة · Phase 7: themes & new products

> 2026-10-11 · local tag `mag-phase-7`

**AR:** أنواع صفحات جديدة بتتعمل بنفس المصنع وبتعدّي على نفس الفحوصات: «أنا مين» (إطار صورة العميل بقواعد المحرر الحالية — قص من النص و300/150/72 dpi ومن غير أي AI)، شهادة تقدير، غلاف خلفي بـQR (الكود بيتعمل لكل أوردر في مكان صورة مخصوص)، نسخة تلوين (مشهد line-art ونص حقيقي)، نسخة عربي/إنجليزي (الاتنين في صفحة واحدة بنفس اسم الطفل عشان OM بيبدّل اسم واحد)، وصفحة الفصل لمجلة المدرسة (خطة أوردرات للنظام الحالي للمؤسسات — مش محرّك أوردرات جديد). الثيم = ثيم خطوط + باليتة + إطارات، ولكل منتج مرشّح للمتجر (M3) بسعر **مقترح** بس.

**EN:** New page kinds through the same factory and validators: about_me (customer photo frame, existing editor rules), certificate, QR back cover (per-order QR in a labelled placeholder), coloring edition, bilingual page (both languages, one name per order), class page + a class-magazine plan for the existing institution orders. Theme = type theme + palette + frame set; M3 Store candidates carry only a suggested price.

## Evidence — `tests/mag/factory/test_page_kinds.py` (5 tests)
An 8-page story using every new kind → all 4 variants (A5) pass every validator incl. LibreOffice export + text proof; slot map `{1,2,3,5,6,7,8}` measured with the Console's rule; bilingual page: Arabic RTL box + English LTR box, the variant's own name in both, OM replacement yields «ليلى flew over the Nile.»; the «أنا مين» frame is ≥ 1.5 cm (offered by the editor); certificate without an English title is refused; QR refuses non-http targets; class plan reports bad roster rows; M3 candidates for every kind.

## Text-proof hardening (measured on these decks)
PDF extraction is not logical-order-perfect for Arabic: pdftotext reorders across bidi runs; both pdftotext and pdfium map the lam-alef ligature back reversed («لأنه» → «ألنه»); pdfium reverses a short RTL fragment after mirrored «» at a line start («شكرًا» → «ركشًا»). The proof now uses **pypdfium2 first** (permissive; Poppler only as fallback), canonicalises alef+lam on both sides, and accepts either the exact letter sequence or an equal multiset of per-word letter signatures — still with equal harakat and punctuation multisets. Every negative control still fails as it must (missing word, missing tanween).

## Pending
Themes get their real type themes / palettes / frame sets from the Phase 4/5/6 catalogs during integration; line-art generation for the coloring edition needs the operator's ComfyUI line-art workflow (Art Desk brief + vectorise path from Phase 5).
