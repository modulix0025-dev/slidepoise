"""Watermarked preview flipbook from an APPROVED PDF (never the print file).

Output folder:
  index.html     self-contained viewer (no external scripts), right-to-left spreads for Arabic books
  pages/NNN.jpg  watermarked page images, long edge ≤ PREVIEW_MAX_PX
  manifest.json  facts: source sha256, page count, size cap, watermark text
The PDF is read, never copied: nothing in the folder is a PDF or a full-resolution page.
"""
from __future__ import annotations

import html
import json
from pathlib import Path

from mxstudio.marketing.preview import (PREVIEW_MAX_PX, WATERMARK_AR, WATERMARK_EN, render_pdf_pages, sha256_file,
                                        watermark)

VIEWER = """<!doctype html>
<html lang="{lang}" dir="{dir}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{ --bg:#f4f1ea; --ink:#1f1f1f; --muted:#6b6b6b; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#1b1b1b; --ink:#f1f1f1; --muted:#a9a9a9; }} }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink); font-family:system-ui,"Segoe UI",Tahoma,sans-serif; }}
header {{ padding:12px 16px; display:flex; justify-content:space-between; align-items:center; gap:8px; }}
h1 {{ font-size:18px; margin:0; }}
.badge {{ font-size:12px; color:var(--muted); }}
main {{ display:flex; justify-content:center; align-items:center; padding:8px 16px 24px; }}
.spread {{ display:flex; gap:4px; max-width:100%; }}
.spread img {{ max-height:78vh; max-width:calc(50vw - 24px); box-shadow:0 2px 10px rgba(0,0,0,.25);
  user-select:none; -webkit-user-drag:none; }}
@media (max-width:700px) {{ .spread img {{ max-width:calc(100vw - 32px); }} .spread img + img {{ display:none; }} }}
nav {{ display:flex; justify-content:center; gap:12px; padding-bottom:20px; }}
button {{ font:inherit; padding:8px 18px; border-radius:20px; border:1px solid var(--muted); background:transparent;
  color:var(--ink); cursor:pointer; }}
</style></head>
<body oncontextmenu="return false">
<header><h1>{title}</h1><span class="badge">{badge}</span></header>
<main><div class="spread" id="spread"></div></main>
<nav><button id="prev">{prev}</button><span id="where" class="badge"></span><button id="next">{next}</button></nav>
<script>
const pages = {pages};
const single = () => window.matchMedia("(max-width:700px)").matches;
let at = 0;
function show() {{
  const step = single() ? 1 : 2;
  const spread = document.getElementById("spread");
  spread.replaceChildren();
  // the cover stands alone; after it, pages come in spreads
  const items = at === 0 ? [0] : pages.slice(at, at + step).map((_, i) => at + i);
  for (const i of items) {{ const img = new Image(); img.src = pages[i]; img.alt = String(i + 1); spread.append(img); }}
  document.getElementById("where").textContent = (items.map(i => i + 1).join("–")) + " / " + pages.length;
}}
function move(d) {{
  const step = single() ? 1 : 2;
  if (d > 0) at = at === 0 ? 1 : Math.min(at + step, pages.length - 1);
  else at = at <= 1 ? 0 : Math.max(1, at - step);
  show();
}}
document.getElementById("next").onclick = () => move(1);
document.getElementById("prev").onclick = () => move(-1);
const forward = "{dir}" === "rtl" ? "ArrowLeft" : "ArrowRight";
const back = "{dir}" === "rtl" ? "ArrowRight" : "ArrowLeft";
document.addEventListener("keydown", e => {{ if (e.key === forward) move(1); if (e.key === back) move(-1); }});
let x0 = null;
document.addEventListener("touchstart", e => {{ x0 = e.touches[0].clientX; }});
document.addEventListener("touchend", e => {{ if (x0 === null) return; const dx = e.changedTouches[0].clientX - x0;
  if (Math.abs(dx) > 40) move(("{dir}" === "rtl") === (dx > 0) ? 1 : -1); x0 = null; }});
window.addEventListener("resize", show);
show();
</script></body></html>
"""


def build_flipbook(pdf: Path, out_dir: Path, title: str, *, language: str = "ar", max_px: int = PREVIEW_MAX_PX,
                   quality: int = 78) -> dict:
    pdf, out_dir = Path(pdf), Path(out_dir)
    if max_px > PREVIEW_MAX_PX:
        raise ValueError(f"preview pages are capped at {PREVIEW_MAX_PX}px on the long edge")
    pages_dir = out_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    names = []
    for number, image in enumerate(render_pdf_pages(pdf, max_px), 1):
        name = f"pages/{number:03d}.jpg"
        watermark(image).save(out_dir / name, "JPEG", quality=quality, optimize=True)
        names.append(name)
    rtl = language == "ar"
    (out_dir / "index.html").write_text(VIEWER.format(
        lang="ar" if rtl else "en", dir="rtl" if rtl else "ltr", title=html.escape(title),
        badge="معاينة — مش نسخة الطباعة" if rtl else "Preview — not the print file",
        prev="السابق" if rtl else "Previous", next="التالي" if rtl else "Next",
        pages=json.dumps(names)), encoding="utf-8")
    manifest = {"kind": "preview_flipbook", "title": title, "language": language, "pages": len(names),
                "max_px": max_px, "watermark": [WATERMARK_AR, WATERMARK_EN], "source_pdf_sha256": sha256_file(pdf),
                "contains_print_file": False}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return dict(manifest, folder=str(out_dir), index=str(out_dir / "index.html"))
