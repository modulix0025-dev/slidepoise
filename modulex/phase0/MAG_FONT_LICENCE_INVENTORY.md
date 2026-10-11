# MAG_FONT_LICENCE_INVENTORY — جرد الخطوط والتراخيص / Font & licence inventory

**Phase 0, read-only.** Status column: ✅ verified in this session · ⏳ needs the operator's machine · ❓ licence unknown.

## 1. الخطوط المستخدمة في القوالب الحالية / Typefaces used by today's templates

The names come from brief §3.2. They are re-measured by `tools/mag_template_anatomy.py`, which is ⏳ until it runs on the 20 real templates.

| Typeface (exact) | Present on operator PC | Licence | Bundle in installer? | Use in a printed template? | Status |
|---|---|---|---|---|---|
| `Blabeloo  MagdySoliman` (**two spaces**) | ⏳ | ❓ none known; not in the project per brief §3.3 | **No** | Only from the operator's own licensed copy installed by him. The Studio detects it and does not bundle it. | ❓ |
| `Ubuntu Arabic` | ⏳ | Ubuntu Font Licence 1.0 (redistribution and embedding allowed; not OFL) | Possible after the operator confirms the exact files' licence | Yes, once confirmed | ⏳ |
| `Calibri` | ⏳ (ships with Windows/Office) | Microsoft proprietary | **No** | Usable through the installed system copy. PDF embedding follows the font's fsType flags, which Phase 5 preflight records. | ⏳ |

The anatomy tool also records `a:latin` / `a:cs` / `a:ea` typefaces for every run, so any extra typeface hidden in a run is caught.

## 2. بدائل OFL مقترحة لكتب الأطفال / Proposed OFL alternatives (the operator decides)

| Font | Licence | Fits | Note |
|---|---|---|---|
| Baloo Bhaijaan 2 | SIL OFL 1.1 | titles, child name, short lines (closest feel to a rounded "kids" display face) | variable weight |
| Lalezar | SIL OFL 1.1 | big display titles only | single weight |
| Tajawal | SIL OFL 1.1 | body text, ages 6–12 | 7 weights, clean |
| Cairo | SIL OFL 1.1 | body and UI, mixed AR/EN | variable |
| Amiri | SIL OFL 1.1 | long-form reading text, classic naskh | best for long text |

Licences are recalled from upstream projects, not downloaded or checked here. Phase 1 fetches each font from its official repository, records the sha256 and the `OFL.txt` in `licences/fonts.json`, and only then makes it bundleable.

## 3. أصول SlidePoise / SlidePoise assets

| Asset | Licence | Decision |
|---|---|---|
| SlidePoise code | MIT (`LICENSE` sha256 `f64a4266…767f`) | Keep `LICENSE` and add `NOTICE` naming commit `4250ba14…` |
| `profiles/pwc-public/**` (17 MB, 4 PDFs + 36 PNG) | Third-party PwC/Strategy&; `NOTICE.md` asserts no reuse licence | **Exclude from fork** |
| Other profile reference PNGs (consulting, editorial-archive, monochrome-modern) | Marked user-supplied/generated in catalogs; no explicit licence field | Not shipped in printed templates. Replaced by ModuleX profiles in Phase 1 patch 7. |
| Remix Icon v4.9.0 (fetched at run time, off by default) | **Remix Icon License v1.0** (brief said Apache-2.0, which is wrong for v4.x) | Not cleared for print until the operator reviews the licence text |
| Wikimedia Commons fetches | per file, provenance JSON, `run_cache_only` | Allowed only behind the licence gate, and only when the file licence permits commercial print |
| Fonts in repo | none (0 font files) | — |

## 4. أدوات للتوزيع داخل المثبّت / Redistributable tools (Phase 8 decides the exact form)

| Tool | Licence | Bundle form | Status |
|---|---|---|---|
| Python (CPython) | PSF | embedded via PyInstaller | standard |
| Node.js | MIT (plus bundled deps' licences) | portable zip | standard |
| PptxGenJS 4.0.1, JSZip 3.10 | MIT / MIT-or-GPLv3 (dual) | `node_modules` | ✅ in `package.json` |
| Poppler (Windows build) | GPL-2.0/3.0 | separate executables plus source offer | ⏳ Phase 8 legal check (GPL obligations) |
| Ghostscript | **AGPL-3.0** (or commercial from Artifex) | **Not bundled by default.** Downloaded from the official URL with pinned sha256, or the operator buys a commercial licence. | ⏳ operator decision |
| LibreOffice | MPL-2.0 | downloaded on demand (administrative MSI extraction) | ⏳ prove without admin on Windows |
| uharfbuzz / HarfBuzz | Apache-2.0 / MIT ("Old MIT") | wheel | standard |
| OpenCV | Apache-2.0 | wheel | standard |
