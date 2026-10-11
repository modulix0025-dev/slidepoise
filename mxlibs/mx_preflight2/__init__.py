"""mx_preflight2 — print preflight facts and named failures for a magazine PDF.

Public API:
    run(pdf_path, profile) -> {"ok", "failed", "checks": [{"id","ok","ar","en","detail"}], "warnings",
                               "sha256", "bytes", "pages", "page_size_mm", "facts"}
    make_profile(size="A5", **overrides) -> profile dict (trim, tolerance, bleed, safe, dpi, colour, ICC)
    CHECK_IDS -> the named checks, in the order they are reported

Dependencies: pikepdf, pypdfium2, numpy, Pillow. Pure: reads the PDF, never writes files or state.
"""

from .preflight import DEFAULT_PROFILE, MSG, TRIM_SIZES_MM, make_profile, run

CHECK_IDS = (
    "readable",
    "encryption",
    "file_size",
    "page_count",
    "page_size",
    "bleed",
    "safe_zone",
    "fonts_embedded",
    "image_only",
    "image_dpi",
    "colour_space",
)
__version__ = "1.0.0"
__all__ = ["CHECK_IDS", "DEFAULT_PROFILE", "MSG", "TRIM_SIZES_MM", "make_profile", "run"]
