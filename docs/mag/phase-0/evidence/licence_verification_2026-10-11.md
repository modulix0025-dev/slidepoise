# Licence verification — shape/icon/asset sources and bundled tools (2026-10-11)

Method codes: **G** = primary source read from GitHub (git clone / raw.githubusercontent.com) at the listed commit · **P** = PyPI/npm registry metadata · **S** = web-search summary only (secondary — **not** accepted as verification).
Unreachable from the cloud container (proxy 403 for curl; WebFetch ENOTFOUND): iconify.design, api.iconify.design, openclipart.org, commons.wikimedia.org, kenney.nl, undraw.co, svgrepo.com, openpeeps.com, ghostscript.com, libreoffice.org, jrsoftware.org. Every **S**-only row stays **UNVERIFIED** and is disabled until the Studio re-checks it from the operator's Windows machine (the Kit's licence probe) or a human checks it in a browser.

Proposed print allowlist (brief §6.4 E): CC0/PD, MIT, ISC, BSD, Apache-2.0, OFL, CC BY 4.0 (+ credits page). Refused: CC BY-SA, NC/ND, unknown, "personal use".

## A · Asset sources

| # | Source | Licence | Primary evidence | Commercial print | Template/library redistribution | Attribution | Machine-readable per-asset licence | Verdict | Method |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Iconify (240 sets) | per **set** | `iconify/icon-sets` `collections.json` @160026b; docs `iconify/documentation` @3f83c49 | per set | per set | per set | per set only: `license.spdx` (240/240), `license.title`, `license.url` (227/240) | filter on spdx (below) | G |
| 2 | Openclipart | CC0 / PD (per FAQ) | site unreachable | likely | likely | none | no API reached | **UNVERIFIED** | S |
| 3 | Wikimedia Commons | per file | `wikimedia/mediawiki-extensions-CommonsMetadata` @28eaa46 — fields `LicenseShortName`, `License`, `LicenseUrl`, `UsageTerms`, `AttributionRequired`, `Artist`, `Credit`, `Copyrighted`, `Restrictions`, `NonFree` | per file | per file | per file | `extmetadata` (above) | PRINT_OK_WITH_CREDITS **after** allowlist filter + `Restrictions`/`NonFree` empty; API itself not reached | G (extension source) |
| 4 | Kenney | CC0 | `KenneyNL/Starter-Kit-3D-Platformer` README @3fa8a04 ("assets CC0"); per-pack `License.txt` | yes | yes (logo reserved) | optional | `License.txt` inside each pack | PRINT_OK — check each pack's License.txt on import | G + S |
| 5 | Noto Emoji | SVG **Apache-2.0**; font OFL-1.1; flags PD | `googlefonts/noto-emoji` @e20cbc2: `2D/svg/LICENSE` (Apache); root `LICENSE` is OFL since 254596e (2024-07-29) | yes | yes | Apache text/NOTICE | Iconify `noto` = Apache-2.0 (its `license.url` now 404) | PRINT_OK | G |
| 6 | Fluent Emoji | MIT | `microsoft/fluentui-emoji` LICENSE @1ffb34c | yes | yes | MIT notice | Iconify `fluent-emoji*` = MIT | PRINT_OK | G |
| 7 | Twemoji graphics | CC-BY-4.0 (code MIT) | `jdecked/twemoji` LICENSE-GRAPHICS @b6b55fe; `twitter/twemoji` @bad3bce | yes | yes | **required** | Iconify `twemoji` = CC-BY-4.0 (npm `@twemoji/svg` says MIT — code only, misleading) | PRINT_OK_WITH_CREDITS | G |
| 8 | OpenMoji | graphics CC-BY-SA-4.0 | `hfg-gmuend/openmoji` LICENSE.txt @aeb8bb3 | share-alike | share-alike | required | CC-BY-SA-4.0 | **REFUSE for print** (screen only) | G |
| 9 | Tabler Icons | MIT | `tabler/tabler-icons` @a4ce140 | yes | yes | notice | MIT | PRINT_OK | G |
| 10 | Phosphor | MIT | `phosphor-icons/core` @2b75f3a | yes | yes | notice | MIT | PRINT_OK | G |
| 11 | Lucide | ISC + MIT (Feather-derived icons listed in LICENSE) | `lucide-icons/lucide` LICENSE @70562c1 | yes | yes | both notices | ISC | PRINT_OK | G |
| 12 | Remix Icon | ≤ v4.8.0 Apache-2.0; **v4.9.0+ custom "Remix Icon License v1.0"** | `Remix-Design/RemixIcon` `License` @9fb7967; changed in f526a92 (2026-01-25) | yes | 4.9+: forbids icon libraries / competing libraries; templates only where icons are "UI elements" | optional | Iconify `ri` is v4.8.0 = Apache-2.0; npm 4.9.x metadata still says Apache (stale) | **Pin ≤ 4.8.0 (PRINT_OK); 4.9+ REFUSE** | G + P |
| 13 | Open Peeps | CC0 (secondary) | site unreachable | — | — | — | none | **UNVERIFIED** | S |
| 14 | unDraw | custom licence (secondary quotes forbid compiling into packs / competing services) | site unreachable | — | forbidden per quotes | — | none | **REFUSE** (until primary read) | S |
| 15 | SVG Repo | mixed per asset | site unreachable | per asset | unknown | per asset | no official API / field found | **REFUSE** | S |

### Iconify `collections.json` by `license.spdx` (240 sets @160026b)

MIT 110 · CC-BY-4.0 52 · Apache-2.0 31 · OFL-1.1 13 · CC0-1.0 10 · ISC 3 · CC-BY-SA-4.0 7 · CC-BY-SA-3.0 2 · GPL-2.0-or-later 2 · GPL-3.0-or-later 2 · GPL-3.0 1 · GPL-2.0-only 1 · MPL-2.0 1 (`circum`) · BSD-3-Clause 1 · Unlicense 1 · CC-BY-3.0 1 (`game-icons`) · CC-BY-NC-4.0 1 (`ps`) · CC-BY-NC-SA-4.0 1 (`cbi`).

⇒ 168 sets PRINT_OK (MIT/Apache/ISC/OFL/CC0/BSD) · 52 PRINT_OK_WITH_CREDITS (CC-BY-4.0) · **operator decision** for Unlicense (1), CC-BY-3.0 (1), MPL-2.0 (1) — default: refused until decided · refused: 9 BY-SA, 6 GPL, 2 NC.
Extra rule: CC0 does not clear **trademarks** — `simple-icons` and `logos` (brand marks) are excluded from children's products.
Iconify API terms: docs say the public API is "free to use", recommend self-hosting; no published rate limit found; the site itself unreachable from the cloud → the Studio will use a polite client (cache, backoff) and allow a self-hosted endpoint setting.

## B · Bundled libraries and tools

| Component | Licence | Evidence | Bundling consequence |
|---|---|---|---|
| rough.js, perfect-freehand, paper.js, svgelements, svgpathtools, pyclipper, coloraide, fontTools, PptxGenJS | MIT | GitHub @56a2762, @176e00f, @92775f5, @9794fc9, @15b500e, @f998920, @d95a26f, @ae5237e, @3c9ec1b | ship licence texts |
| vtracer | MIT | `visioncortex/vtracer` @928ed0a; PyPI 0.6.15 | ship licence |
| uharfbuzz | Apache-2.0 | `harfbuzz/uharfbuzz` @bfddbe1; PyPI 0.56.3 | ship licence/NOTICE |
| JSZip | MIT OR GPL-3.0+ | `Stuk/jszip` @609d95f | use under MIT |
| python-bidi 0.6.11 | **LGPL-3.0** | `MeirKriheli/python-bidi` @3ed1dc9 (COPYING + COPYING.LESSER) | PyInstaller **one-folder** with the module replaceable; ship LGPL/GPL texts + source offer (or replace with an ICU-based bidi) |
| Ghostscript | **AGPL-3.0+** or Artifex commercial | `ArtifexSoftware/ghostpdl` @3346f19 | **do not bundle**; optional component downloaded from the official URL at install/first use with pinned sha256, run as a separate process; AGPL text shown — operator decision D8 |
| Poppler | GPL-2.0+ (primary not reached) | distro metadata only | prefer **pypdfium2** (PDFium, BSD/Apache — to verify in Phase 2) for rasterising; Poppler only as an optional separate executable |
| potrace | GPL | known; not re-read | not used (vtracer instead) |
| LibreOffice | MPL-2.0 + third-party | `LibreOffice/core` COPYING.MPL @63a2e19 | unmodified official MSI may be redistributed (Full flavour) with notices + source pointer; online flavour downloads it |
| Inno Setup | custom permissive | `jrsoftware/issrc` license.txt @b9a17b6 | installers OK; keep notices; vendor *requests* a commercial licence for commercial use (request, not condition — jrsoftware.org unreachable to re-read) |
