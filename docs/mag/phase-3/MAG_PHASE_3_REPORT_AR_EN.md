# MAG_PHASE_3_REPORT_AR_EN — المرحلة 3: مصنع القوالب · Phase 3: Template Factory

> 2026-10-11 · local tag `mag-phase-3`

## 1 · الخلاصة · Summary
**AR:** قصة جديدة خالص («{الاسم} ونجمة القمر») اتكتبت ولد/بنت عربي وإنجليزي، وطلعت منها **8 نسخ** (A4/A5 × ولد/بنت × عربي/إنجليزي) أوتوماتيك، وكل نسخة عدّت على **كل** الفحوصات: عدد الاستبدالات بكود OM نفسه (5 من 5)، أماكن الصور بكود الكونسول نفسه، أطول اسم متوقع (14 حرف) بيكفي، الخطوط متسطّبة، تصدير PDF فيه نص بعدد الصفحات الصح، وكل كلمة وحركة وعلامة ترقيم موجودة في الـPDF. الحزمة الموقّعة للنشر بتتعمل من **نفس البايتات المعتمدة** وبمفتاح ModuleX المشترك، والتلاعب بيتكشف.

**EN:** A brand-new story became all 8 variants automatically; every variant passed every validator (operator rules, longest name, fonts, export, text proof). The signed publish pack is built from the exact approved bytes with the shared ModuleX key; tampering is detected.

## 2 · المكوّنات · Components
| Piece | Module |
|---|---|
| Story Desk (4 hand-written payloads, `{NAME}` token, page kinds, تشكيل proposals accepted word by word — never on the name) | `mxstudio/factory/story.py`, `demo_story.py` |
| Layouts in mm on the print canvas (scene full-bleed, text on a native panel inside the safe box, dedication, back page with 2 placeholders) | `layouts.py` |
| Variant Forge (exact ISO-216 scaling of geometry + type from the trim box, full-bleed preserved, payload swap, HarfBuzz re-fit, one filename scheme) | `forge.py` |
| Art Desk (briefs that forbid letters and keep the text zone empty; glyph check on targets; contact sheets via pypdfium2) | `art.py` |
| Validators (replacement count via verbatim OM code, name-run integrity, slot map via verbatim Console code, fit, longest name 14 letters, installed fonts, vendored `pptx_to_pdf` export, page count, text proof) | `validate.py` |
| Publish (M1 registry-v2 candidate, M2 `story_decks.json` candidate with measured slot maps, signed pack + verify) | `publish.py` |
| Service, API (`factory.build`, irreversible `factory.publish_pack` from approved blobs only), CLI `python -m mxstudio factory demo` | `service.py`, `api.py`, `cli.py` |

## 3 · الأدلة · Evidence
- `tests/mag/factory/test_factory_gate.py` — 8 tests: story-rule negatives (girl text identical to boy, dedication without name, bad key, no scene); تشكيل never touches the name; exact ISO-216 scaling; **all 8 variants green** (replacements 5/5, slots `{1:1,2:1,3:1,4:1,6:2}`, 6 pages with text, text proof ok, PowerPoint proof marked pending); filenames + M1/M2; pack verify + wrong key + tampered file; overflow is a named `fit` finding; API flow: build → publish refused without confirmation → approve with token → publish refused without the shared HMAC secret → publish → pack verifies.
- `evidence/factory_demo_report.json` (CLI output, all variants ok, engine LibreOffice), `evidence/moon_star_contact_sheet.png` (48 pages).
- Measured improvement to the Phase 1 text proof: neutral punctuation next to a direction change is extracted in visual order, so punctuation is now compared as a multiset (letters/digits still compared as an exact sequence; marks as a multiset).

## 4 · لسه · Pending
| Item | How |
|---|---|
| PowerPoint export of the 8 decks | On-Device Proof Runner (Phase 8) |
| Real art generation (Qwen-Image / Qwen-Image-Edit on the operator's GPU) | needs the operator's ComfyUI URL; the Art Desk produces briefs + checks targets; manual exchange works without any API |
| Typography / colour / shapes inside layouts | wired in when the Phase 4/5/6 libraries land (type themes, palettes, frames) |
| Children's-book profiles (moved from Phase 1) | themes = type theme + palette + frame set (Phase 7) |
