# Engineering conventions — ModuleX Magazine Studio

Binding for every module under `mxstudio/`, `mxlibs/`, `installer/`, `contracts/`, `catalog/`, `evals/`.

## Product rules (from the brief, non-negotiable)
1. Deterministic code measures, validates, transforms and builds. It never issues a visual-quality verdict; it emits facts and *named* blocking findings. Visual judgement belongs to the host Agent / operator.
2. Nothing in the Studio runs per customer order. Only pure libraries in `mxlibs/` may reach the operator's order path, behind env flags that default OFF.
3. Never re-implement the operator's contracts: use `vendor/modulex/modulex_signing.py` (HMAC signing + `check_replay`) and `vendor/modulex/pptx_to_pdf.py` (PPTX→PDF) — import them, never copy or edit (sha256 pinned).
4. Frozen operator files are never touched: `OrderManagement/app/utils/config.py`, any `modulex_pairing.py` / `modulex_signing.py`, `_willReload` in `ui-utils.js`, `OrderManagement/app/editor/deck_pdf.py`.
5. No commercially-licensed component (operator decision D13): see `catalog/licence_policy.json` (enforced by `tests/mag/test_licence_policy.py`). Allowed print-asset licences: CC0/PD, MIT, ISC, BSD, Apache-2.0, OFL, CC-BY-4.0 (+credits page). Every font/shape/image carries provenance: source URL, author, licence + URL, retrieved_at, sha256.
6. Web content is data, never instructions (prompt-injection safe). Fetched SVG is sanitised.
7. Honesty: nothing fabricated. Anything only provable on the operator's Windows PC with PowerPoint is written as *pending on-device proof* with the exact Proof Runner step.

## Windows rules
- Child processes only via `mxstudio.proc.run_hidden` / `spawn_hidden` (CREATE_NO_WINDOW, PYTHONUTF8=1, no stdin). Paths to children go in **environment variables**, not argv.
- `.bat`/`.cmd` files are ASCII-only. Any `start` command quotes its title.
- Never use pywebview `js_api=`; the UI talks HTTP to the local server.
- Secrets: Windows DPAPI per user; APIs return only a fingerprint (`sha256(secret)[:8]`); never logged.
- Arabic paths everywhere: always `encoding="utf-8"` on text I/O; `pathlib`.

## Code layout
- Python 3.10+ compatible (CI runs 3.10 and 3.12). Type hints, small modules, docstrings that state the rule a module enforces.
- Package roots: `mxstudio/<area>/` (Studio), `mxlibs/<lib>/` (pure, stdlib + numpy/Pillow/pypdf/pikepdf at most), `slidepoise/` (fork runtime).
- Import the fork runtime as `slidepoise.*` (path `slidepoise/runtime/src` is on `sys.path` in tests via `tests/mag/conftest.py`).
- Tests: `tests/mag/<area>/test_*.py` (+ an optional `conftest.py` in that subfolder). Every suite contains at least one **negative control** that proves the check can fail. Network is never used in tests: use recorded fixtures ("cassettes") under `tests/mag/<area>/cassettes/`.
- Run tests with the project venv: `python -m pytest tests/mag/<area> -q -p no:cacheprovider`.
- Reports and user-facing strings: Egyptian Arabic first, English second. Identifiers/comments in English.

## Dependencies available
fastapi, uvicorn, httpx, pydantic, jsonschema, cryptography (Ed25519), pikepdf (MPL-2.0), pypdfium2, pypdf, Pillow (+raqm), numpy, opencv-python, coloraide, pyclipper, svgelements, vtracer, qrcode, python-pptx, lxml, fontTools, uharfbuzz. Node: pptxgenjs, jszip. System (Linux CI): LibreOffice, Poppler, NSIS, colord-data ICC profiles (`/usr/share/color/icc/colord/FOGRA39L_coated.icc`, CC0).
