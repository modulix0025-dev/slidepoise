"""Every result the local server would return is plain JSON (no numpy scalars, no private keys)."""
from __future__ import annotations

import json

import numpy as np

from mxstudio.colour import cvd, extract, harmony, print_safety, readability, roles
from mxstudio.colour.critic import CRITERIA, Candidate, review


def _judge(req):
    return {"criteria": {c: {"winner": "tie", "confidence": 0.5, "reason": "same"} for c in req.criteria}}


def test_results_are_json_serialisable(scene_art, neon_art):
    img, mask = scene_art
    pal = extract.extract_palette(img, skin_mask=mask)
    deck = roles.derive_roles(pal)
    results = [
        harmony.all_harmonies("#2a9d8f", lightness=0.7, chroma=0.1),
        pal, deck.as_dict(), roles.check_roles(deck),
        roles.consistency_report(deck, [{"page_id": "p1", "colours": {"primary": "#123456"}}]),
        readability.check_page(img, [{"id": "t", "box_px": (10, 10, 120, 60), "text_colour": "#222222",
                                      "font_size_pt": 16}], deck.roles()),
        print_safety.check_colour("#39ff14"), print_safety.check_image(neon_art), print_safety.check_cmyk([0, 0, 0, 100]),
        print_safety.rich_black_guidance("background"), print_safety.profile_info(),
        cvd.check_colour_meanings({"a": "#2ca02c", "b": "#d62728"}),
        review([Candidate("x", meta={}), Candidate("y", meta={})], [_judge], judgements=2),
    ]
    for res in results:
        text = json.dumps(res, ensure_ascii=False, allow_nan=False)
        assert "_region" not in text
    assert not any(isinstance(v, np.generic) for v in json.loads(json.dumps(results[6])).values())
    assert len(CRITERIA) == 8
