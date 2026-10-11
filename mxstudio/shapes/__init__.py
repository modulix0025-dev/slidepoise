"""Phase 5 - native, editable, print-sharp shapes for the Magazine Studio.

* ``presets`` / ``warps``: all ECMA-376 preset geometries (187) and text warps (41) with handles.
* ``custgeom``: path model <-> ``a:custGeom`` <-> SVG; ``svg_convert``: SVG -> custGeom.
* ``generators``: deterministic seeded procedural shapes (custGeom, never pictures).
* ``boolean``: union/subtract/intersect/offset (pyclipper).
* ``sanitize``: geometry-only SVG; ``vectorize``: vtracer; ``ai_shapes``: injected providers.
* ``discovery``: licence-gated official APIs; ``library``: SQLite library; ``consistency``,
  ``credits``: book-level facts and the credits page; ``pptx_out``: native PowerPoint objects.
* ``service`` / ``api``: the HTTP + agent surface (see ``service.ENDPOINTS``).

Deterministic code here measures and builds; visual acceptance stays with the operator.
"""
