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
