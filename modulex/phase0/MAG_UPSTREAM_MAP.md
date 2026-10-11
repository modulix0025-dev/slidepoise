# MAG_UPSTREAM_MAP — SlidePoise at the pinned commit

**Phase 0, read-only.** Pinned upstream: `henryhyw/slidepoise` v0.8.2, HEAD `4250ba14d5d673a3215e7707b5d52f67cdf1154e` ("Preserve visual exploration and scoped asset guidance"). The checkout in this session is the fork `modulix0025-dev/slidepoise`, and its HEAD is that exact commit.

Every statement below was read from the code at that commit. Line numbers refer to that commit.

## 0. Corrections to the brief (§3.1). The code wins.

| # | Brief said | Code says | Evidence | Impact on Phase 1 |
|---|---|---|---|---|
| C1 | "`defineLayout` → custom (portrait) page sizes are reachable" | Only the **aspect ratio** is reachable. Physical width is hard-coded to **13.333 in** (`physicalWidth = 40/3`). A portrait A5 scene would come out about 33.9 × 47.9 cm, not 14.8 × 21.0 cm. | `slidepoise/runtime/js/scene_to_pptx.mjs:771-774`; `reconstruction/scene.py:557-558` (`points_per_px = scale_y*960/width`, assumes 960 pt); `runtime/scripts/measure_visual_scene.py:177` (`13.333333/image_width`) | Phase 1 patch 3 must make physical size an input (trim + bleed in EMU/inches) **in all three places**. Font-size px→pt conversion depends on it. |
| C2 | "Pillow `ImageFont` — **no shaping**, so Arabic widths would be wrong" | Pillow wheels ship **libraqm + FriBiDi + HarfBuzz**. `text_fit._load_font` uses the default layout engine, which is RAQM when available, so Arabic **is** shaped on Linux. Measured with DejaVu Sans 40 px on `السمكة الذهبية`: BASIC = 350.0 px, RAQM = 249.4 px, default = 249.4 px. | `text_fit.py:110-114`; `PIL.features.check('raqm') == True` (Pillow 12.3.0, HarfBuzz 14.2.1) | Shaping still has to be **guaranteed, not incidental**. On Windows, Pillow loads FriBiDi as a separate DLL that is not always present, and then RAQM silently falls back to BASIC. Phase 1 keeps the HarfBuzz (`uharfbuzz`) route as planned and adds a test that fails if BASIC is used for Arabic. **Not verified on Windows in this session.** |
| C3 | "every schema in `slidepoise/schemas/`" | None of the 11 files is a JSON Schema. They are all `*.example.json` sample documents, with no `$id`, `required` or `enum`. The scene-object kinds are enforced in code. | `slidepoise/schemas/*.example.json`; `runtime/src/slidepoise/artifacts.py:114` | The M0–M5 contracts must be written as real JSON Schemas from scratch. Upstream has none to extend. |
| C4 | Font resolution is "a hard-coded path list" | It is a hard-coded list for Arial and Georgia, then macOS Supplemental, then **`fc-match`** (Linux/macOS only), then Arial. On Windows any family other than Arial/Georgia falls back to Arial. | `text_fit.py:16-107` | Confirms that patch 1 is needed (a Windows font-table lookup by family name). |
| C5 | — | Text tracking (`char_spacing_px`) is applied per character. Letter-spacing breaks Arabic cursive joining. | `text_fit.py:148,280`; `postprocess_pptx.py:178-215` (writes `spc` on every run) | Phase 1: tracking is forced to 0 for Arabic-script runs. |
| C6 | — | No `subprocess`/`Popen`/`spawnSync` call in the repo sets `CREATE_NO_WINDOW`/`windowsHide`. There are 17 call sites (table in §6). | §6 | Standing rule 10: the fork wraps every call site. |

All other §3.1 facts were confirmed: v0.8.2, MIT, HEAD hash, the command list, no RTL/Arabic/bidi anywhere (grep returns 0 hits), only Latin fonts, no picture placeholders emitted, `profiles/pwc-public` is third-party, Remix Icon, Wikimedia fetchers, Python ≥3.10, Node ≥18 / npm ≥9.

## 1. Runtime commands (`slidepoise/scripts/slidepoise_runtime.py`, parser at 351-430)

| Command | Required args | Does | External tools |
|---|---|---|---|
| `measure` | `--image --semantic-map --output-dir --config` (`--upstream-handoff`, `--sam auto/never/required`) | subprocess `runtime/scripts/measure_visual_scene.py` → `slide_entities.json`, `debug_overlay.png`, `report.md`, `crops/`, `masks/` | OpenCV, numpy, Pillow; SAM 2 optional (`sam_optional.py`) |
| `build-contract` | `--measured-scene --config --output` | `reconstruction.contract.build_reconstruction_contract` | — |
| `compile-scene` | `--measured-scene --contract --config --slide-id --output` | `reconstruction.scene.build_reconstruction_scene` (text fit inside) | Pillow fonts, optional `fc-match` |
| `reconstruct-slide` | `--image --semantic-map --upstream-handoff --config --slide-id --output-dir` | measure → build-contract → compile-scene | as above |
| `render-pptx` | `--scene --config --output` (`--title`, `--language`, default `en-US`) | validates the scene, then `node runtime/js/scene_to_pptx.mjs`, then `postprocess_pptx.py` | node + pptxgenjs 4.0.1, Python with lxml |
| `render-deck` | `--manifest --output` | multi-slide version of the same call | node |
| `bundle-deck` / `verify-bundle` | `--manifest --output-dir [--include]` / `--bundle-dir` | `artifacts.bundle_deck` / `verify_bundle` | — |
| `render-preview` | `--pptx --output [--dpi 160 --slide-number 1 --font-config]` | `soffice --headless --convert-to pdf`, then `pdftoppm -png -singlefile`, then `pdftotext -bbox-layout` text evidence | LibreOffice, Poppler |
| `render-deck-preview` | `--pptx --output-dir [--dpi 120]` | all pages + contact sheet + `presentation.pdf` + text evidence | LibreOffice, Poppler |
| `audit-text` | `--pptx` | `runtime/scripts/audit_powerpoint_text.py` (bodyPr, fonts, sizes) | — |

The preview and PDF route is **LibreOffice only**. There is no PowerPoint COM path anywhere. The ModuleX Console's `pptx_to_pdf` (PowerPoint first) is the production exporter, and the Studio will call it rather than upstream's preview.

## 2. Data shapes

- **Scene object kinds** (`artifacts.py:114`, dispatch in `scene_to_pptx.mjs:799-806`): `textbox, shape, image, connector_graph, table, chart, freeform`. There is **no `picture_placeholder`**.
- **Semantic-map entity kinds** (`measure_visual_scene.py:24-34`): `text, shape, table, chart, icon, icon_slot, connector, image, novel_visual`.
- **Example documents** (`schemas/*.example.json`): `agent-review`, `deck-design`, `deck-outline`, `deck-scenes`, `generation-contract` (canvas `[2048,1070]`, offset 41 px for the header), `panel`, `reconstruction-handoff`, `resource-selection`, `semantic-map` (3.2.0), `slide-intent`, `visual-review`. None has a direction or per-text language field.

## 3. Module summary

- `reconstruction/contract.py`: one reconstruction unit per entity, asset mapping, frame content merge, coordinate transform. Public: `build_reconstruction_contract`.
- `reconstruction/coverage.py`: content-obligation checks.
- `reconstruction/conformance.py`: mechanical structure checks (IDs, containment, collisions). It returns findings, never a verdict.
- `reconstruction/scene.py`: measured scene → constructor scene. Text style is always `autofit:"none"`, defaulting to `left`/`top`.
- `reconstruction/text_fit.py`: Pillow wrap/fit estimate, mandatory peer typography groups, 0.5 pt quantisation, CJK kinsoku. Does not handle RTL.
- `runtime/js/scene_to_pptx.mjs`: PptxGenJS emitter. It passes `fontFace, fontSize, bold, italic, charSpacing, color, align, valign, margin, fit, lineSpacingMultiple`. It does **not** pass `lang` or `rtlMode`, so every run gets `lang="en-US"`. It emits only the `sldNum` placeholder (on the frame master).
- `runtime/scripts/postprocess_pptx.py`: shape-ID dedupe, `<a:noAutofit/>`, connector conversion, roundRect adj, `spc`, arrowheads, chart labels. It **never touches** `lang/rtl/algn/fonts/size`. This is the natural place for the RTL / `a:cs` / `<p:ph type="pic">` post-process.

## 4. Every place a size, font, alignment, language or direction is assumed

### 4.1 Page size and units
| Where | Value |
|---|---|
| `scene_to_pptx.mjs:771` | physical width `40/3` in |
| `scene_to_pptx.mjs:764-766` | every slide must share slide 1's `dimensions_px` |
| `reconstruction/scene.py:557-558` | 960 pt canvas |
| `measure_visual_scene.py:177` | `13.333333 / image_width` (ink height to pt) |
| `framework/defaults/slidepoise-config.json:171-174` | `full_slide_px [2048,1152]` (16:9) |
| `runtime/src/slidepoise/canvas.py:13-58` | content region = height − header − footer, aspect ±1 px |
| `webapp/{ui,console}/styles.css` | `aspect-ratio: 16/9` previews |

### 4.2 Fonts
| Where | Value |
|---|---|
| `text_fit.py:16-64` | `FONT_PATHS`: Arial and Georgia only |
| `text_fit.py:80-114` | lookup: table → macOS → `fc-match` → Arial → `load_default` |
| `text_fit.py:222-231` | families outside {display_font, body_font} are replaced (profile font policy) |
| `scene_to_pptx.mjs:85,309,691,740,781-782`; `slidepoise_runtime.py:130-131`; `scene.py:483,784-785` | defaults Arial / Georgia |
| `framework/design.py:18` | Console font list (10 Latin/CJK families, no Arabic) |
| `slidepoise-config.json:182-295` | header/footer/title fonts |

### 4.3 Alignment and line breaking
| Where | Value |
|---|---|
| `text_fit.py:257-258`, `scene.py:496-497`, `scene_to_pptx.mjs:91-92` | default `left` / `top` |
| `scene_to_pptx.mjs:687-740` | master text: header left = left, header right = right, slide number = right. Not mirrored for RTL. |
| `text_fit.py:117-155` | greedy wrap on whitespace; CJK per-character; no hyphenation. Arabic words wrap on spaces, which is correct for kashida-free text. |
| `audit_powerpoint_text.py:66-67,135` | requires explicit `algn` |

### 4.4 Language and direction
| Where | Value |
|---|---|
| `scene_to_pptx.mjs:779,783`, `slidepoise_runtime.py:393`, `artifacts.py:175` | `en-US` default |
| `webapp/*/index.html:2` | `<html lang="en">`, no `dir` |
| `rendered_text.py:34`, `reference_retrieval.py:23,56` | `\w` tokeniser and English stop words |
| whole repo | **no** `rtl`, `rtlMode`, `bidi`, `dir=`, `a:cs`, or digit-shaping setting |

### 4.5 Frame (header, footer, folio)
`slidepoise-config.json:175-216` (header/footer 41 px, rule, `slide_number` on master), `scene_to_pptx.mjs:702-752` (`defineFrameMaster`), `canvas.py:18-36`, `contract.py:149-198`, `resolve_config.py:226-260`. The frame is **always the same on every slide**. There is no left/right page mirroring and no "folio off" for full-bleed pages.

### 4.6 Print
Upstream has no bleed, trim, safe zone, CMYK, crop marks or imposition. `allow_parent_bleed` (`conformance.py:300`) means "overlaps its parent object", not print bleed.

## 5. Platform branches
`preview_tools.py:15,19` (darwin/win32 search paths, including Windows ProgramFiles/WinGet), `framework/preview_install.py` (brew/winget/apt-get), `framework/storage.py:42,55` (msvcrt vs fcntl), `webapp/server.py:384` (open/explorer/xdg-open), `scene_to_pptx.mjs:671` (`python` on win32).

## 6. Process launches (none hides its window)
| Where | Command |
|---|---|
| `text_fit.py:101` | `fc-match` |
| `rendered_text.py:54` | `pdftotext` |
| `slidepoise_runtime.py:33` (`run_checked`: 46,136,145,200,219,308,347) and 111 | measure, node, soffice, pdftoppm, audit, `npm root -g` |
| `component_preview.py:29`, `package_self.py:18`, `examples/rebuild.py:24` | python scripts |
| `scene_to_pptx.mjs:674` | `spawnSync python postprocess_pptx.py` (no `windowsHide`) |
| `framework/cli.py:66,116`, `framework/panel.py:40`, `framework/sessions.py:95`, `framework/design.py:37` | webapp server, generation handoff, resolve_config |
| `framework/host_notifications.py:25` | `codex app-server proxy` |
| `framework/preview_install.py:58`, `framework/installer.py:96` | package managers, `npm install` |
| `webapp/server.py:385,479` | file opener, `webbrowser.open` |

## 7. Upstream baseline (this session, Linux)

| Suite | Result |
|---|---|
| `pytest` (Python 3.13.16, venv with `Pillow 12.3.0, python-pptx 1.0.2, resvg-py, numpy, opencv-python-headless, pytest, build`) | **367 passed**, 0 skipped. Without `build` installed: 366 passed and 1 failed (`test_distribution`, environmental) |
| `npm test` (Node 22.22.0) | **18 / 18 pass** |
| Browser suite (`npm run test:browser`, Playwright) | not run in Phase 0 |

Only one environment was available (Linux container, Python 3.13). The second environment required by standing rule 5 (Windows) is **pending**.

## 8. Fork-relevant files outside the runtime
- `profiles/pwc-public/` (17 MB) is third-party PwC/Strategy& material, and its `NOTICE.md` says no reuse licence is asserted. **It will be excluded from the fork.** The exclusion touches `README.md`, `slidepoise/references/reference-retrieval.md`, `tests/test_public_reference_bundle.py` and `tests/test_distribution.py`, and each of those test changes will go in the changed-tests table. `profiles/aliases.json` maps `pwc-consulting → consulting`, so nothing breaks there.
- Key file hashes (sha256) at the pin:
  - `scene_to_pptx.mjs 38d6a165…2aa2`
  - `text_fit.py aff93b8b…1002`
  - `postprocess_pptx.py 55864ef4…7c60`
  - `slidepoise_runtime.py 492b6559…6707`
  - `LICENSE f64a4266…767f`

## 9. Framework, Console, CI (what the Studio can reuse)

- **CLI** (`framework/cli.py:166-326`): `setup, doctor, generation {show,configure,route,export,import}, panel, profile {…}, library {…}, console, run {…}`.
  - Data home: `$SLIDEPOISE_HOME` or `~/.slidepoise`.
  - The skill is copied to `~/.{codex,claude,qoder}/skills/slidepoise`.
  - The Node runtime is installed with `npm install` into `~/.slidepoise/node`.
  - Preview tools come from **package managers** (winget `TheDocumentFoundation.LibreOffice`, `oschwartz10612.Poppler`). winget usually needs admin/UAC for LibreOffice, so this route does not satisfy O6's "no admin" path.
- **`bin/slidepoise.js`**: asks interactive TTY prompts and pip-installs into `~/.slidepoise/python`. Standing rule 10 bans interactive consoles, so the Studio installer will not use this entry point.
- **Profiles** (`framework/profiles.py`, CI rules in `slidepoise/scripts/preflight_catalogs.py:40-100`):
  - Each profile is a `profile.json` (schema 1.0.0 or 2.0.0) plus `libraries/visual_references/catalog.json`.
  - Every file must be in the catalog with provenance.
  - `design_overrides.style.display_font/body_font` is Georgia/Arial in all four bundled profiles.
  - Upgrades use a sha256 bundle manifest, and user edits are preserved.
  - **Phase 1 patch 7 (children's-book profiles) fits this mechanism without a new loader.**
- **Console server** (`webapp/server.py`):
  - stdlib `ThreadingHTTPServer` on 127.0.0.1:8765. The session panel runs on 127.0.0.1:18765.
  - **No auth and no CSRF token.** The only protection is that a POST is refused when its `Origin` header is present and does not match `Host` (`:336-338`).
  - The Studio uses its own FastAPI server with CSRF (Phase 2) and does not inherit this.
- **CI** (`.github/workflows/ci.yml`):
  - The test matrix already includes **`windows-latest`** × Python 3.10/3.12, Node 22, plus browser, preview (LibreOffice) and package jobs.
  - This gives the program a real Windows second environment for standing rule 5 once the fork's Actions are enabled.
  - `release.yml` publishes a GitHub release on `v*` tags. That is the base for the Phase 8 direct link.

## 10. Licence notes found in Phase 0
- **Correction C7:** the brief says "Remix Icon is Apache-2.0". The fetcher pins **Remix Icon v4.9.0** under the **"Remix Icon License v1.0"** (`slidepoise/scripts/fetch_remix_icon_pair.py:95-126`, `library-sets/catalog.json`). That is not Apache-2.0: the v4.x licence adds restrictions. Phase 0 classifies Remix Icon as **"not cleared for printed templates until the operator reviews the licence text"**.
- No font files are bundled anywhere in the repo (0 `.ttf/.otf/.woff*`).
- Wikimedia fetches record per-file licence provenance and stay in `run_cache_only`.
