"""Kit patch registry. One module per patch: anchors, hook text and additive payload."""
from __future__ import annotations

from . import p_preflight2, p_preview, p_proof, p_receivers, p_safezone, p_textfit
from .base import Patch

PATCHES: dict[str, Patch] = {p.PATCH.id: p.PATCH for p in (p_textfit, p_safezone, p_preview, p_proof,
                                                           p_preflight2, p_receivers)}

#: Flags in the plan table (§3) that have no Kit patch yet — reported honestly by `plan`.
UNWIRED_FLAGS = {
    "MODULEX_MAG_IMPOSE": "imposition/CMYK derivative patch not defined in this phase (mx_impose is vendor-ready)",
    "MODULEX_MAG_FONTCHECK": "Console export font validator hook not defined in this phase (proofs run it on device)",
    "MODULEX_MAG_QA_GATE": "mx_qagate is ready (phase 9); preflight.run() gets only the PDF, so the hook needs the "
                           "probe to learn how OM links an order's deck, approved page count and child name",
}
