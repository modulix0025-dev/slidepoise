"""P-TEXTFIT — OM editor: measure customer text with the vendored mx_textfit before export.

Anchors: OM app/editor/deck.py constants, id regexes, function signatures and the P149 kill switch.
Hook:    top of ``apply(deck_in, deck_out, texts, images, inv)`` (after its docstring).
Payload: ``app/mag_textfit/`` (gate + vendored ``mx_textfit``).
Flag:    MODULEX_MAG_TEXTFIT (default OFF; off ⇒ the hook only reads the environment).
"""
from __future__ import annotations

from .base import PAYLOADS, Hook, Patch, Payload

HOOK_BODY = '''\
if __import__("os").environ.get("MODULEX_MAG_TEXTFIT", "0").strip() == "1":
    from app.mag_textfit.gate import check_texts as _mx_check_texts
    _mx_check_texts(deck_in, texts, inv)
'''

PATCH = Patch(
    id="P-TEXTFIT",
    flag="MODULEX_MAG_TEXTFIT",
    title_ar="قياس نص العميل قبل التصدير",
    title_en="Fit customer text before export",
    summary_en="Refuses (Arabic message) any edited text frame that mx_textfit measures as overflowing.",
    anchors=("OM.editor.deck.signatures", "OM.editor.deck.constants", "OM.editor.deck.regexes",
             "OM.editor.deck.killswitch", "OM.app_package"),
    hooks=(Hook("OM", "app/editor/deck.py", "func_start:apply", HOOK_BODY),),
    payloads=(Payload("OM", "app/mag_textfit", (PAYLOADS / "textfit",), libs=("mx_textfit",)),),
    notes=("TextDoesNotFit subclasses ValueError; how the editor turns it into a response is verified on device.",),
)
