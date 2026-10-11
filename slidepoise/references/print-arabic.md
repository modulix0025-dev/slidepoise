# Print pages and Arabic text (ModuleX fork)

Read this when a page is a printed magazine page, carries Arabic or other right-to-left text, or will be personalised by name replacement.

## Page geometry

Declare the physical canvas on the spec: `page.canvas_mm = [trim_w + 2·bleed, trim_h + 2·bleed]` (A5 with 3 mm bleed = `[154, 216]`). `dimensions_px` must have the same aspect. Use `slidepoise.print_geometry.PageSpec` for the trim box, the safe box and pixel boxes; full-bleed art covers the whole canvas, while text, faces and QR codes stay inside the safe box. A4↔A5 is an exact ISO-216 scale of 1/√2 for geometry **and** type sizes; every scaled page is re-fitted afterwards.

## Right-to-left text

Set `style.direction = "rtl"` (and `style.lang`, default `ar-EG`) on a textbox. The post-processor writes `rtl="1"`, right alignment unless authored, the language on every run and a complex-script typeface. Fitting measures RTL copy with HarfBuzz on the exact family name (`slidepoise.arabic`); line breaks happen only at spaces, and a word wider than its box is an overflow fact. Vowelised lines get a taller line box automatically. Family names keep their internal spaces exactly.

Generated art must leave text zones empty: image models draw Arabic letters badly and pixels cannot be personalised or edited. Every word is native text.

## Names that will be replaced

Write the hero's sample name as its own run: `runs: [{"text": "…"}, {"text": "إياد", "role": "child_name"}, {"text": "…"}]`. Attach prepositions with a tatweel (`لـإياد`) so a plain replacement yields a correct `لـمحمد`. Validate with the operator's own rules in `mxstudio/validators/operator_ports.py`: the replacement count must equal the expected paragraphs and every name must lie whole inside one run.

## Picture placeholders

Use `{"kind": "picture_placeholder", "bbox_px": …, "order": n}` for every place a per-order scene or customer photo will go. They become `<p:ph type="pic">` on the slide (plus a matching layout placeholder), counted by the Console's slot rule. LibreOffice may export such a deck to PDF, but it must never re-save a template: re-saving replaces empty picture placeholders with plain pictures.
