"""Arabic / RTL support for the SlidePoise runtime (ModuleX Magazine Studio fork).

Deterministic measurement only: font resolution by family name, HarfBuzz
shaping, harakat-aware line heights and whitespace-only line breaking. Visual
acceptance stays with the host Agent and the operator.
"""
from slidepoise.arabic.fit import FitResult, fit_text, min_safe_line_spacing, wrap
from slidepoise.arabic.fonts import FontFace, FontRegistry, default_registry, normalize_family
from slidepoise.arabic.shaping import (directional_runs, has_harakat, has_rtl, shape, text_width_pt,
                                       to_arabic_indic_digits, to_western_digits)

__all__ = ["FitResult", "FontFace", "FontRegistry", "default_registry", "directional_runs", "fit_text",
           "has_harakat", "has_rtl", "min_safe_line_spacing", "normalize_family", "shape", "text_width_pt",
           "to_arabic_indic_digits", "to_western_digits", "wrap"]
