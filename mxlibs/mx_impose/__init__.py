"""mx_impose — print-shop derivatives of an approved magazine PDF. Pure functions; the source is never modified.

Public API:
    crop_marks(pdf_in, pdf_out, *, bleed_mm=None, mark_len_mm=5, offset_mm=None) -> record
    saddle_stitch_order(n_pages, binding="ltr"|"rtl") -> printer spreads (sheet, side, left, right)
    creep_offsets(n_sheets, creep_mm) -> per-sheet shift toward the spine, outermost first
    impose_saddle(pdf_in, pdf_out, *, binding, sheet="auto", creep_mm=0, duplex="short_edge") -> record
    cmyk_derivative(pdf_in, pdf_out, icc_profile, tac_limit=300, *, raster_dpi=600) -> record

Every record carries source_sha256 and output_sha256 so the derivative stays linked to the record.
Dependencies: pikepdf, Pillow (ImageCms / LittleCMS), numpy, pypdfium2. Not PDF/X certification.
"""

from .cmyk import ColourConverter, cmyk_derivative
from .marks import crop_marks
from .saddle import creep_offsets, impose_saddle, padded_count, saddle_stitch_order

__version__ = "1.0.0"
__all__ = [
    "ColourConverter",
    "cmyk_derivative",
    "creep_offsets",
    "crop_marks",
    "impose_saddle",
    "padded_count",
    "saddle_stitch_order",
]
