"""P-PROOF — customer soft-proof approval bound to the PDF sha256 (flag MODULEX_MAG_PROOF_APPROVAL)."""
from __future__ import annotations

from ._editor_ext import ANCHORS, hook, payload
from .base import Patch

PATCH = Patch(
    id="P-PROOF",
    flag="MODULEX_MAG_PROOF_APPROVAL",
    title_ar="موافقة العميل على البروفة",
    title_en="Customer proof approval",
    summary_en="Records {version, timestamp, sha256}; binds via a public print_service function when one exists, "
               "else a sidecar beside the PDF. Never writes print tables.",
    anchors=ANCHORS + ("OM.editor.printing.freeze_rebind", "OM.printing.print_service.public"),
    hooks=(hook("MODULEX_MAG_PROOF_APPROVAL", "mag_proof"),),
    payloads=(payload("proof"),),
    notes=(("print_service today exposes freeze_sent_artifacts/rebind_ready_artifacts only, so the sidecar path "
            "is used; the print portal reading the sidecar needs a follow-up anchor located by the probe."),),
)
