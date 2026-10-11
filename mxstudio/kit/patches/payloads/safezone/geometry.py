"""Safe-zone geometry read straight from the deck zip (no python-pptx needed).

Facts only: trim = the slide canvas; safe = trim inset by ``safe_mm``; every picture frame and
text box whose rectangle leaves the safe rectangle is listed with a named finding. Face
detection is NOT done here (no vision model in the order path) — a frame crossing the safe
band is the measurable proxy and is reported as such.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

EMU_PER_MM = 36000
_SLIDE_RE = re.compile(r"^ppt/slides/slide(\d+)\.xml$")
_SHAPE_RE = re.compile(rb"<p:(pic|sp)\b.*?</p:\1>", re.DOTALL)
_OFF_RE = re.compile(rb'<a:off x="(-?\d+)" y="(-?\d+)"\s*/>')
_EXT_RE = re.compile(rb'<a:ext cx="(\d+)" cy="(\d+)"\s*/>')
_NAME_RE = re.compile(rb'<p:cNvPr id="(\d+)" name="([^"]*)"')


def geometry(pptx_path: Path, *, safe_mm: float = 5.0) -> dict:
    with zipfile.ZipFile(str(pptx_path)) as z:
        pres = z.read("ppt/presentation.xml")
        m = re.search(rb'<p:sldSz[^>]*cx="(\d+)"[^>]*cy="(\d+)"', pres)
        cx, cy = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
        inset = int(safe_mm * EMU_PER_MM)
        safe = [inset, inset, cx - inset, cy - inset]
        slides = []
        for name in sorted(z.namelist(), key=lambda n: int(_SLIDE_RE.match(n).group(1)) if _SLIDE_RE.match(n) else 0):
            sm = _SLIDE_RE.match(name)
            if not sm:
                continue
            xml = z.read(name)
            findings = []
            for shape in _SHAPE_RE.finditer(xml):
                block = shape.group(0)
                off, ext, nm = _OFF_RE.search(block), _EXT_RE.search(block), _NAME_RE.search(block)
                if not (off and ext):
                    continue
                x, y = int(off.group(1)), int(off.group(2))
                w, h = int(ext.group(1)), int(ext.group(2))
                is_pic = shape.group(1) == b"pic" or b'type="pic"' in block
                is_text = b"<a:t>" in block or b"<a:t " in block
                if not (is_pic or is_text):
                    continue
                full_bleed = x <= 0 and y <= 0 and x + w >= cx and y + h >= cy
                outside = x < safe[0] or y < safe[1] or x + w > safe[2] or y + h > safe[3]
                if outside and not (is_pic and full_bleed):
                    findings.append({
                        "shape_id": int(nm.group(1)) if nm else None,
                        "name": nm.group(2).decode("utf-8", "replace") if nm else "",
                        "kind": "picture" if is_pic else "text",
                        "finding": "picture_frame_crosses_safe_band" if is_pic else "text_outside_safe_zone",
                        "rect_emu": [x, y, x + w, y + h]})
            slides.append({"slide": int(sm.group(1)), "findings": findings})
    return {"trim_emu": [0, 0, cx, cy], "safe_emu": safe, "safe_mm": safe_mm,
            "trim_mm": [round(cx / EMU_PER_MM, 2), round(cy / EMU_PER_MM, 2)], "slides": slides}
