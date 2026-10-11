"""MODULEX_MAG P-PREVIEW payload (OM editor): single-slide preview export cached by content hash.

Installed by the Magazine Studio Integration Kit. Mounted only when MODULEX_MAG_PAGE_PREVIEW=1.
Uses OM's own app/editor/deck.py::export_pdf (same engine as the real export).
Revert with: python -m mxstudio.kit revert --patch P-PREVIEW
"""
