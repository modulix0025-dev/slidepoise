"""mx_qagate — pre-print QA gate for one personalised magazine (pure; vendored verbatim into OM/Console).

Deterministic blockers (each named, Arabic + English) — any one of them means
"hold": empty picture placeholder left, text overflow, child name missing on the
cover, page count different from the approved count, blank page, image-only PDF,
uncertified or missing font.

AI advisory checks (wrong-gender figure, identity drift, scene/page mismatch,
visible artefacts) are reported separately with `advisory: True` and NEVER
change a job's state by themselves.

This library never writes print state. In OM, `printing/preflight.py` appends
these results as checks (flag MODULEX_MAG_QA_GATE, default off), so the
existing `print_service.py` — the only writer of print state — refuses to send
a job whose preflight is not ok.
"""
from mx_qagate.gate import BLOCKERS, advisory_review, qa_sheet, run_gate

__all__ = ["BLOCKERS", "advisory_review", "qa_sheet", "run_gate"]
__version__ = "1.0.0"
