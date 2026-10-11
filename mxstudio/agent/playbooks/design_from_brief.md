# من طلب أو صورة لقالب جاهز · From a brief or a reference image to a template

**AR:** المشغّل بيكتب اللي عايزه و/أو بيرفع صورة تصميم. انت:
1. اعرض خطة قصيرة (`plan`): القصة، عدد الصفحات وأنواعها، الخطوط، الألوان.
2. لو فيه صورة: `colour.from_art` بـ`reference=<sha>` تطلّع الباليتة؛ اختار ألوان النص والإطار والخلفية منها، واتأكد بـ`colour.print_check` إنها هتتطبع صح.
3. اختار ثيم خطوط من `fonts.list_themes` يناسب الإحساس (مرح، هادي، كلاسيكي…). لو `factory.build` رجّع `FONTS_NOT_INSTALLED` اختار ثيم تاني أو قول للمشغّل يسطّب الخطوط من «الخطوط».
4. اكتب القصة: نص الولد ونص البنت **كل واحد لوحده** (الأفعال والضمائر)، والإنجليزي ترجمة، واسم الطفل دايمًا `{NAME}`، وصفحة الإهداء فيها `{NAME}`.
5. `factory.build` بـ`story` و`theme`. هتوصلك صورة المعاينة لكل الصفحات: **بصّ عليها** قبل ما تقول خلصت (نص مقطوع؟ ألوان مش مقروءة؟ إحساس مختلف عن الصورة؟).
6. لو فيه فحوصات حمرا صلّحها وابني تاني. في الآخر قول بالظبط إيه اتبنى وإيه لسه.
7. تعديلات المشغّل ("كبّر الاسم"، "خلّي الألوان أهدى"، "غيّر الصفحة التالتة"): هات آخر نسخة بـ`factory.preview`، عدّل اللي اتطلب بس، وابني نسخة جديدة. النسخ القديمة بتفضل محفوظة.
8. الاعتماد والنشر مش شغلك: لما القالب يبقى جاهز قول للمشغّل يعتمده من الشاشة.

**EN:** Plan → (reference image) `colour.from_art reference=<sha>` → `colour.print_check` → pick a type theme (`fonts.list_themes`) → write boy/girl texts separately with `{NAME}` → `factory.build` with `story` + `theme` → look at the attached preview before reporting → fix red findings and rebuild → for revisions start from `factory.preview`, change only what was asked, rebuild (old versions stay). Approval and publishing are the human's, from the Studio screen.

Story JSON shape (`factory.build.story`):
```json
{"key": "sea_trip", "title": {"ar": "{NAME} في رحلة البحر", "en": "{NAME}'s Sea Trip"},
 "figure_prompt_male": "a cheerful Egyptian boy, about six", "figure_prompt_female": "a cheerful Egyptian girl, about six",
 "pages": [
  {"kind": "cover", "texts": {"ar_boy": "…", "ar_girl": "…", "en_boy": "…", "en_girl": "…"}, "scene": "…"},
  {"kind": "scene", "texts": {"ar_boy": "…", "ar_girl": "…", "en_boy": "…", "en_girl": "…"}, "scene": "…"},
  {"kind": "dedication", "texts": {"ar_boy": "بكل الحب تهدى لـ{NAME}", "ar_girl": "بكل الحب تهدى لـ{NAME}",
                                   "en_boy": "With love, for {NAME}", "en_girl": "With love, for {NAME}"}, "figure": false},
  {"kind": "back", "figure": false}]}
```
Page kinds: cover, scene, dedication, back, certificate (needs `title` per language), about_me, qr_back, coloring, bilingual, class_page. Theme (`factory.build.theme`): `{"type_theme": "<id>", "colours": {"text": "#RRGGBB", "panel": "#RRGGBB", "outline": "#RRGGBB", "background": "#RRGGBB"}}`.

## صفحة بالعرض 16:9 وصورة مالية الصفحة · Landscape 16:9, full-page scene

**AR:** لو المشغّل عايز الشكل بالعرض (الصورة مالية الصفحة): في القصة حط `"page": "landscape_169"` و`"layout"`:
`"overlay"` (تدرّج غامق ناحية النص — الافتراضي يمين — والكلام فوقه) أو `"storybook"` (كلام في نص السطر ومايل سنة في الحتة الفاضية، واسم الطفل كبير «name art» جوه المشهد). المشهد دايمًا Picture Placeholder 100 فاضي في القالب.
لكل صفحة تقدر تحدد (كنِسَب من الصفحة 0..1): `text_box: [x, y, w, h]`، `name_box`، `rotate` و`name_rotate` (درجات)، `name_style`: `gold` | `ice` | `pink`، `text_side`: `right` | `left` (overlay)، `ink: true` لكلام غامق على حتة فاتحة، `name_art: false` لصفحة من غير اسم كبير، و`art`: بصمة صورة المشهد (من `studio_inbox_use`) علشان فحص التباين يتحسب على الصورة الحقيقية. لو طلع `low_contrast` اتبع الاقتراح (تغميق التدرّج أو تحريك الكلام). لو `text_outside_safe` صغّر أو حرّك المربع.

**EN:** `"page": "landscape_169"` + `"layout": "overlay" | "storybook"`; per page: `text_box`, `name_box` (fractions), `rotate`, `name_rotate`, `name_style` (gold|ice|pink), `text_side`, `ink`, `name_art`, `art` (sha of the scene art from `studio_inbox_use`, used for the contrast check on the real pixels).
```json
{"key": "pyramid_secret", "page": "landscape_169", "layout": "storybook",
 "title": {"ar": "{NAME} وسرّ الهرم الكبير", "en": "{NAME} and the Pyramid's Secret"},
 "pages": [
  {"kind": "cover", "texts": {"ar_boy": "{NAME} وسرّ الهرم الكبير", "…": "…"}, "name_style": "gold", "art": "<sha>"},
  {"kind": "scene", "texts": {"…": "…"}, "text_box": [0.55, 0.06, 0.40, 0.30], "rotate": -2,
   "name_box": [0.04, 0.05, 0.36, 0.22], "name_rotate": 3, "name_style": "ice", "art": "<sha>"}]}
```
