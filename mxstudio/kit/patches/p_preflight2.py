"""P-PREFLIGHT2 — OM printing: append mx_preflight2 findings to ``preflight.run()``.

Anchor:  OM app/printing/preflight.py ``def run(path, *, magazine_size="A4", …, max_bytes=…)``.
Hook:    module end of preflight.py (flag read at import; off ⇒ ``run`` is the original object).
Payload: ``app/mag_preflight2/`` (wrapper + vendored ``mx_preflight2``).
Never writes print state — print_service.py stays the only writer.
"""
from __future__ import annotations

from .base import PAYLOADS, Hook, Patch, Payload

HOOK_BODY = '''\
if __import__("os").environ.get("MODULEX_MAG_PREFLIGHT2", "0").strip() == "1":
    from app.mag_preflight2.hook import wrap_run as _mx_wrap_run
    run = _mx_wrap_run(run)
'''

PATCH = Patch(
    id="P-PREFLIGHT2",
    flag="MODULEX_MAG_PREFLIGHT2",
    title_ar="فحص الطباعة المتقدم (preflight v2)",
    title_en="Preflight v2 checks",
    summary_en="When on, preflight.run() results also carry mx_preflight2 checks (bleed, fonts, DPI, safe band).",
    anchors=("OM.printing.preflight.run", "OM.printing.print_service.public", "OM.app_package"),
    hooks=(Hook("OM", "app/printing/preflight.py", "module_end", HOOK_BODY),),
    payloads=(Payload("OM", "app/mag_preflight2", (PAYLOADS / "preflight2",), libs=("mx_preflight2",)),),
    notes=("The flag is read when preflight.py is imported: restart OM after changing it.",),
)
