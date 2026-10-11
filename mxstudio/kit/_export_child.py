"""Child process for one PPTX→PDF proof (started hidden by :mod:`mxstudio.kit.proofs`).

Why a child: the vendored converter starts PowerShell/LibreOffice itself; running it inside a
``CREATE_NO_WINDOW`` child means those grandchildren inherit the hidden console (no window on
the operator's desktop), and a hung PowerPoint is killed with the child, not with the Studio.
Inputs arrive in environment variables (Arabic paths): MX_PPTX_SRC, MX_PPTX_DST,
MXS_KIT_ENGINES (comma list, optional), MX_EXPECT_PAGES (optional). Prints one JSON object.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main() -> int:
    from mxstudio.kit import _vendor
    from mxstudio.kit._pdfscan import pdf_font_names

    src = Path(os.environ["MX_PPTX_SRC"])
    dst = Path(os.environ["MX_PPTX_DST"])
    engines = [e.strip() for e in os.environ.get("MXS_KIT_ENGINES", "").split(",") if e.strip()] or None
    p2p = _vendor.pptx_to_pdf()
    try:
        rec = p2p.convert(src, dst, engines=engines, expect_pages=int(os.environ.get("MX_EXPECT_PAGES", "0") or 0))
    except p2p.ConversionError as exc:
        print(json.dumps({"ok": False, "error": str(exc), "attempts": exc.attempts}, ensure_ascii=False))
        return 2
    rec["pdf_fonts"] = pdf_font_names(dst.read_bytes())
    print(json.dumps(rec, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
