"""ModuleX Magazine Studio (authoring-time application on the SlidePoise fork)."""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

# A source checkout runs without installing the fork runtime or the order-path libraries:
# put `slidepoise/runtime/src` (package `slidepoise`) and `mxlibs/` on the path when present.
# The frozen app has both through PyInstaller (pathex + bundled data) and skips what is missing.
_ROOT = _Path(__file__).resolve().parents[1]
for _extra in (_ROOT / "slidepoise" / "runtime" / "src", _ROOT / "mxlibs"):
    if _extra.is_dir() and str(_extra) not in _sys.path:
        _sys.path.append(str(_extra))
