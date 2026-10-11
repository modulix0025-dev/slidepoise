# MAG_PHASE_5_REPORT_AR_EN — المرحلة 5: الأشكال والرسم · Phase 5: shapes & drawing

> 2026-10-11 · local tag `mag-phase-5` · details: `PHASE_5_NOTES.md`

**AR:** كل الأشكال بتفضل **أشكال PowerPoint قابلة للتعديل** (`p:sp`)، مش صور. فيه الـ187 شكل جاهز بتوع Office بأذرع الضبط بتاعتهم (300 ذراع، مطابقين لجدول LibreOffice بالحرف)، الـ41 انحناء نص، و18 مولّد أشكال (إطارات، فقاعات كلام، زخارف، نقوش، ستيكرز…) بنتيجة ثابتة لنفس البذرة. تحويل SVG لـ`custGeom` بدقة أقل IoU = 0.996 على 50 شكل. منظّف SVG صارم (XXE، billion laughs، تعشيش عميق… مرفوض). البحث في Openverse وWikimedia وIconify (مجاني) وكل حاجة بتعدّي على بوابة التراخيص: CC BY-SA وNC وND والمجهول والاستخدام الشخصي وGPL/MPL **مرفوضين للطباعة**، CC-BY-4.0 بيضيف صفحة اعتمادات تلقائيًا. لوحة رسم حر (`/ui/canvas/`) بقت جوه تبويب «الأشكال والرسم».

**EN:** Editable vector geometry only: 187 Office presets with 300 adjust handles (exact match with LibreOffice's table; two python-pptx table defects overridden), 41 text warps (6 defaults corrected against LibreOffice's definitions), 18 seeded generators (byte-identical across interpreters), SVG → custGeom (min IoU 0.996, mean 0.9993 over 50 shapes; negative controls fail), strict sanitiser (19 strip, 14 hard-reject cases, 400 fuzzed docs), free discovery with a licence gate and credits, shape library, consistency facts. The proof deck has zero pictures, reopens in python-pptx and exports through the vendored `pptx_to_pdf`.

## Evidence
`tests/mag/shapes/` — 256 tests, a negative control in every file.

## Pending · مستني
* Discovery cassettes are built from the documented API schemas (`_meta.recorded_live = false`) because the APIs are blocked from this cloud; re-record on the operator's PC (Proof Runner).
* Arabic text in ring-shaped warps loses letter joining in LibreOffice — check in PowerPoint.
* AI shape providers are not wired (routes answer `NO_PROVIDER` until GPU endpoints are configured).
* PowerPoint proof deck with draggable handles, die-cut spot-colour naming, canvas inside pywebview.
