"""MODULEX_MAG P-PROOF payload (OM editor + print portal): customer soft-proof approval record.

Installed by the Magazine Studio Integration Kit. Mounted only when MODULEX_MAG_PROOF_APPROVAL=1.
Never writes print tables: binds through a public print_service function if one exists,
otherwise stores the approval beside the PDF for the print portal to read.
Revert with: python -m mxstudio.kit revert --patch P-PROOF
"""
