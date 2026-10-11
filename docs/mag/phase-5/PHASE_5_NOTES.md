# المرحلة ٥ — مكتبة الأشكال ولوحة الرسم · Phase 5 — Shape library and drawing canvas

التاريخ: 2026-10-11 · Date: 2026-10-11
الكود: `mxstudio/shapes/` · الواجهة: `mxstudio/ui/canvas/` · الكتالوج: `catalog/shapes/` · الاختبارات: `tests/mag/shapes/`

---

## بالمصري

### اتعمل إيه

**أ. الأشكال الجاهزة (Presets) وانحناءات النص (Warps)**
- كل أشكال `a:prstGeom` في المواصفة ECMA-376 (`ST_ShapeType`): **187 شكل**، متخزنين كبيانات في `presets.py`، ومعاهم أذرع الضبط (adjust handles) بقيمها الافتراضية — **300 ذراع**.
- القائمة اتراجعت على ٣ مصادر: (١) جدول LibreOffice المتسطب `oox-drawingml-cs-presets` (نفس الـ187 بالظبط ونفس أسماء وقيم الأذرع)، (٢) python-pptx (‏177 اسم كلهم جوه قايمتنا)، (٣) قايمة الأمثلة اللي في البريف.
- لقينا **غلطتين في جدول python-pptx**: `upDownArrow` مكرر فيه الأذرع (adj1, adj1, adj2, adj2) و`foldedCorner` مالوش ذراع خالص. صلحناهم في `presets.py` واتأكدنا منهم من جدول LibreOffice.
- كل انحناءات النص `a:prstTxWarp` (`ST_TextShapeType`): **41 انحناء** في `warps.py`. القيم الافتراضية اتراجعت على ملف LibreOffice/core ‏`oox/source/export/presetTextWarpDefinitions.xml` (sha256 ‏`3948968d…c391`، اتقرا من GitHub ومش متشحن معانا). المراجعة دي كشفت **٦ قيم كنت كاتبها غلط** واتصلحت: `textStop`, `textArchDownPour.adj2`, `textCanUp`, `textInflateBottom`, `textInflateTop`, `textSlantUp`.
- الأذرع ظاهرة في الواجهة كـ sliders، والسيرفر بيرجّع XML جاهز (`/api/shapes/presets/xml`, `/api/shapes/warps/xml`). مدى الـslider مجرد إرشاد للواجهة؛ PowerPoint نفسه بيقص القيمة حسب معادلات الشكل.

**ب. المولّدات (Generators)** — 18 مولّد، كلهم بيطلّعوا `a:custGeom` مش صور، وبنفس البذرة (seed) بيطلع نفس الـXML بالبايت:
إطار مموّج بأقواس، إطار طابع بريد، إطار سحابة بعدد نتوءات قابل للضبط، ورق مقطوع، براويز صفحات بثيمات (أمواج البحر، عروق نبات، نجوم، حلويات)، زخرفة الحرف الأول، إطار ماندالا بتماثل دائري، شكل عضوي (superformula + noise)، خط مرسوم باليد (فكرة rough.js — roughness/bowing/أكتر من ضربة)، فقاعة كلام ذيلها بيشاور على الشخصية (من الخريطة الدلالية للصفحة)، فقاعة تفكير، شريط لافتة، وسام، قوس قزح، فاصل أمواج، قصاصات/نجوم متناثرة بـ Poisson-disk وبتبعد عن مربعات الكلام والوشوش، نقشات تعبئة (نقط، خطوط، مربعات، قلوب)، وحدّ قص الملصق (offset بـ pyclipper).

**ج. لوحة الرسم + المحوّل**
- `mxstudio/ui/canvas/`: قلم بيزييه، رسم حر بتنعيم (منقول خوارزمية perfect-freehand من غير ما نضيف أي مكتبة npm)، التقاط (شبكة، نقط موجودة، زوايا ١٥°)، مراية وتماثل دائري ×N، أنواع خطوط (متصل/شرط/نقط…)، دمج/طرح/تقاطع على السيرفر بـ pyclipper.
- محوّل SVG ⇄ custGeom (svgelements): الخطوط → `lnTo`، المنحنيات التكعيبية → `cubicBezTo`، التربيعية → `quadBezTo`، الأقواس المحورية → `arcTo`، الأقواس المايلة → تكعيبي.
- **اختبار الدقة**: مجموعة من **50 شكل SVG** — أقل IoU **‏0.996** (المطلوب ≥ 0.99)، والقياس على الـXML اللي فعلاً بيروح لـ PowerPoint بعد ما نقراه تاني.
- اتأكدنا كمان إن **LibreOffice بيقرا زوايا `arcTo` بنفس طريقتنا** (زوايا "مرئية"): رسم LibreOffice للأشكال اللي فيها أقواس بيطابق resvg بـ IoU ≥ 0.98.

**د. أشكال بمساعدة الذكاء الاصطناعي (للتأليف بس)**
- (أ) وصف → موديل نصوص يكتب SVG → منظّف صارم → رسم → ناقد بصري → تعديل (عدد لفّات محدود). (ب) موديل صور → vtracer (MIT، مش potrace) → تبسيط → custGeom.
- الموديلات بتتحقن كدوال (callables)، والاختبارات بتستخدم موديلات وهمية. **مفيش حاجة بتدخل المكتبة من غير موافقة المشغّل باسمه**. لو الشكل طلع شبه صورة الإلهام قوي بيتعلّم عليه `too_similar_to_inspiration`.

**هـ. البحث على النت بترخيص مضبوط**
- بنسأل الـAPIs الرسمية بس: Iconify وOpenverse وWikimedia Commons، وحزم Kenney (CC0) من مجلد/zip. نتايج النت العامة **إلهام بس** وعمرها ما تتستورد.
- قائمة الطباعة المسموحة من `catalog/licence_policy.json`. المرفوض: CC BY-SA، أي NC/ND، المجهول، "للاستخدام الشخصي"، GPL/MPL. Unlicense وCC-BY-3.0 مستنيين قرار المشغّل (مرفوضين لحد ما يقرر). CC-BY-4.0 مسموح بشرط صفحة اعتمادات بتتعمل أوتوماتيك.
- Iconify: الرخصة لكل مجموعة؛ مستبعد `simple-icons` و`logos` (علامات تجارية) و`openmoji`؛ Remix مسموح لحد 4.8.0 بس. Wikimedia: أي ملف عليه `Restrictions` أو `NonFree` مرفوض.
- كل أصل بيتخزن معاه: رابط المصدر، المؤلف، الرخصة ورابطها، وقت الجلب، sha256، واسم اللي وافق. الـSVG اللي جاي من برّه بيتنضف، والنصوص (عناوين/مؤلفين) بيانات مش أوامر.

**و. إدارة المكتبة**: SQLite فيه تاجات (ثيم، سن، مود، ستايل flat/hand-drawn/outline/3D)، مفضلة، عدّاد استخدام لكل كتاب، بحث نصي بيفهم الكتابة العربية بأشكالها (أ/ا، ة/ه، ى/ي، التشكيل)، بحث بالرسمة/التشابه (Hu + طيف الحدود)، وفحص تناسق الكتاب (سُمك الخط، استدارة الأركان، الباليتة، خلط الستايلات) — كله **حقائق ونتايج بأسامي**، مفيش حكم بصري.

### النتايج
- `tests/mag/shapes`: **256 اختبار ناجح** (كل ملف فيه negative control بيثبت إن الفحص يقدر يفشل). السويت كلها `tests/mag`: ‏908 ناجح.
- PPTX فيه الـ187 شكل + الـ41 انحناء + كل المولّدات + SVGs متحوّلة: الـXML سليم، صفر صور، كله `p:sp`، وLibreOffice حوّله PDF بنفس عدد الصفحات.

### لسه مستني إثبات على جهاز المشغّل (Proof Runner)
1. `shapes.proof_deck`: افتح الـPPTX اللي بيطلّعه `pptx_out.build_proof_deck()` في PowerPoint: الـ187 شكل بيترسموا، والأذرع الصفرا بتتسحب، والـ41 انحناء ظاهرين صح.
2. `shapes.arcto_powerpoint`: نفس فحص الأقواس اللي عدّى في LibreOffice، بس في PowerPoint.
3. `shapes.multi_path_fill`: الشريط (أجزاء `darken`/`darkenLess` جوه نفس الشكل) وأكتر من `a:path` في نفس الشكل بيترسموا صح في PowerPoint.
4. `shapes.discovery.record`: إعادة تسجيل الكاسيتات من جهاز المشغّل — الـAPIs مش متاحة من السحابة (proxy 403)، فالكاسيتات الحالية **مش تسجيل حي**؛ مبنية على شكل الرد الموثّق ومكتوب ده جواها (`_meta.recorded_live = false`).
5. العربي جوه انحناءات زي الحلقة (`textRingInside/Outside`) بيتقطّع في LibreOffice؛ لازم نشوفه في PowerPoint.
6. لون القص (spot colour زي CutContour) لملصقات القص: الهندسة جاهزة، تسمية اللون للمطبعة لسه.
7. الواجهة اتجرّبت هندستها في Node بس؛ لسه تجربة حقيقية في نافذة الاستوديو (pywebview) على ويندوز، ومعاينة شكل الـpreset بصريًا (دلوقتي بنعرض الأذرع والـXML).
8. الموديلات الحقيقية (نصوص/رؤية/صور) لسه مش متوصلة: الـAPI بيقرا `state.shape_providers` لو موجود، وإلا بيرد `NO_PROVIDER`.

---

## English

### What was built

**A. Presets and text warps**
- All ECMA-376 `a:prstGeom` presets (`ST_ShapeType`): **187**, embedded as data in `presets.py`, with adjust handles and defaults — **300 handles**.
- Cross-checked against three sources: LibreOffice's installed `oox-drawingml-cs-presets` table (identical 187 names, handle names and defaults), python-pptx (its 177 names are a subset) and the brief's examples.
- Found **two defects in python-pptx's table**: `upDownArrow` lists handles twice and `foldedCorner` lists none. Overridden in `presets.py`, confirmed against LibreOffice.
- All `a:prstTxWarp` warps (`ST_TextShapeType`): **41** in `warps.py`. Defaults checked against LibreOffice/core `oox/source/export/presetTextWarpDefinitions.xml` (sha256 `3948968d…c391`, read from GitHub, not shipped). That check found **six defaults I had written wrong**, now corrected: `textStop`, `textArchDownPour.adj2`, `textCanUp`, `textInflateBottom`, `textInflateTop`, `textSlantUp`.
- Handles are exposed as UI sliders. The server returns ready XML (`/api/shapes/presets/xml`, `/api/shapes/warps/xml`). Slider ranges are UI hints only; Office pins values through each preset's guide formulas.

**B. Generators**: 18 seeded generators. All emit `a:custGeom` (never pictures). The same seed gives byte-identical XML, including in a fresh interpreter with a different `PYTHONHASHSEED`. They cover: scalloped and stamp frames, cloud frames with tunable bumps, torn paper, themed page borders (sea waves, vines, stars, candy), drop-cap ornaments, mandala frames, superformula+noise blobs, rough.js-style hand-drawn outlines, speech bubbles whose tail aims at a semantic-map anchor, thought bubbles, ribbon banners, rosettes, rainbows, wave dividers, Poisson-disk confetti that avoids text boxes and faces, pattern fills (dots, stripes, checks, hearts) and die-cut sticker outlines (pyclipper offset).

**C. Canvas and converter**
- `mxstudio/ui/canvas/` is vanilla JS with no dependencies. It has:
  - a pen/Bezier tool;
  - freehand smoothing (the perfect-freehand algorithm, ported without adding any npm package);
  - snapping to grid, anchors and 15° angles;
  - mirror and radial ×N symmetry;
  - dash/cap/width stroke styles;
  - server-side union/subtract/intersect.
- SVG ⇄ custGeom via svgelements: lines become `lnTo`, cubics `cubicBezTo`, quadratics `quadBezTo`, axis-aligned arcs `arcTo` (visual angles) and rotated arcs cubics. A non-zero element that overlaps itself is unioned with pyclipper (finding `nonzero_flattened`).
- **Fidelity gate**: 50-shape corpus, minimum IoU **0.996** (gate ≥ 0.99). The measurement uses the emitted XML parsed back, rendered by this package's exact even-odd scanline rasteriser, against resvg.
- LibreOffice's PDF render of the arc-heavy shapes matches resvg at IoU ≥ 0.98. So LibreOffice reads `arcTo` angles the way we write them.

**D. AI-assisted shapes (authoring only)**
- Route (a) is describe → LLM SVG → strict sanitiser → resvg render → vision critic → bounded revision loop.
- Route (b) is image model → vtracer → simplify → custGeom.
- Providers are injected callables, and the tests use fakes. Nothing enters the library without a named operator. Copies of inspiration are flagged `too_similar_to_inspiration`.

**E. Licence-gated discovery**
- Sources are Iconify, Openverse, Wikimedia Commons and local CC0 packs (Kenney) only. General-web results are inspiration-only (`InspirationOnly`).
- The gate reads `catalog/licence_policy.json`:
  - Print-allowed: CC0/PD, MIT, ISC, BSD-2/3, Apache-2.0, OFL-1.1, and CC-BY-4.0 (which adds an auto credits page).
  - Refused: CC BY-SA, NC/ND, unknown, personal-use, GPL/MPL.
  - Pending the operator, refused until he decides: Unlicense and CC-BY-3.0.
- Iconify licences are checked per set. `simple-icons`, `logos` and `openmoji` are excluded, and Remix is accepted only up to 4.8.0.
- Wikimedia files with `Restrictions`/`NonFree` are refused.
- Imports are resolved from the server-side copy of the search result, so a client cannot rewrite a licence. They need an operator name and record source URL, author, licence + URL, retrieved_at, sha256 and approved_by.
- Fetched SVG is sanitised. Fetched text is inert data: HTML stripped, control and bidi-override characters removed, length-capped. In prompts it travels as an escaped JSON `<data>` block.

**F. Library**
- SQLite store with:
  - tags (theme, age, mood, style flat/hand-drawn/outline/3D);
  - favourites;
  - per-book usage tracking;
  - Arabic-aware text search (FTS5 + letter folding);
  - sketch and similarity search (first Hu invariant + rotation-invariant contour spectrum).
- A book consistency check reports stroke width, corner radius, palette ΔE2000 and mixed styles as named findings, never a score.
- `credits.py` builds the licence report (JSON + Markdown) and appends a bilingual credits slide.

### Results
- `tests/mag/shapes`: **256 passed**. Every file has a negative control that proves its check can fail. Whole `tests/mag`: 908 passed.
- Proof deck (187 presets + 41 warps + all generators + converted SVGs):
  - the XML is valid;
  - it has zero pictures, and every shape is a `p:sp`;
  - python-pptx reopens it and recolours every freeform;
  - LibreOffice exports it to PDF with the expected page count (vendored `pptx_to_pdf`).

### Endpoints (auto-mounted: `mxstudio/shapes/api.py` → `register(app, state)`)
`GET /api/shapes/presets` · `GET /api/shapes/warps` · `GET /api/shapes/generators` · `GET /api/shapes/sources` ·
`POST /api/shapes/presets/xml` · `POST /api/shapes/warps/xml` · `POST /api/shapes/generate` · `POST /api/shapes/sanitize` ·
`POST /api/shapes/svg-to-custgeom` · `POST /api/shapes/boolean` · `POST /api/shapes/canvas/commit` · `POST /api/shapes/vectorize` ·
`POST /api/shapes/ai/describe` · `POST /api/shapes/ai/image` · `POST /api/shapes/candidates/approve` · `POST /api/shapes/discover` ·
`POST /api/shapes/inspiration` · `POST /api/shapes/import` · `POST /api/shapes/library/search` · `POST /api/shapes/library/similar` ·
`POST /api/shapes/library/get` · `POST /api/shapes/library/favourite` · `POST /api/shapes/library/use` ·
`POST /api/shapes/consistency` · `POST /api/shapes/licence-report`.
Agent tools: `shapes.presets`, `shapes.warps`, `shapes.generators`, `shapes.generate`, `shapes.library_search`, `shapes.consistency`, `shapes.licence_report` (read-only or reversible).
The canvas page is `/ui/canvas/index.html` and uses the CSRF token from `/api/session`.

### Pending on-device proof (Proof Runner steps)
1. `shapes.proof_deck`: open the deck from `pptx_out.build_proof_deck()` in PowerPoint. All 187 presets should render, the yellow handles should drag, and all 41 warps should show.
2. `shapes.arcto_powerpoint`: repeat the arcTo IoU check (passed in LibreOffice) in PowerPoint.
3. `shapes.multi_path_fill`: check that multi-`a:path` shapes with `darken`/`darkenLess` parts (ribbon banner) render in PowerPoint.
4. `shapes.discovery.record`: re-record the cassettes from the operator's PC. The APIs are unreachable from the cloud (proxy 403), so the cassettes are schema-shaped fixtures, **not live recordings**; each says so in `_meta.recorded_live = false`.
5. Arabic text in ring warps loses letter joining in LibreOffice. Check it in PowerPoint.
6. Spot-colour naming for die-cut lines (for example CutContour) is a print-shop step. The geometry is done; the naming is not.
7. The canvas geometry was tested in Node only. Still needed: a real run inside the Studio window (pywebview, Windows) and a visual preset preview (the UI shows handles + XML today).
8. Real text/vision/image providers are not wired. The API reads `state.shape_providers` when present and otherwise answers `NO_PROVIDER`.
