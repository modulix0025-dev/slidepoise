"""Visual critic: pairwise + ensemble with a deterministic fake judge; never blocks or publishes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from mxstudio.colour.critic import (CRITERIA, RUBRIC, Candidate, build_vision_payload, compare, parse_judgement,
                                    review, vision_judge)

CASSETTES = Path(__file__).resolve().parent / "cassettes"


def _flip(*parts, pct: int) -> bool:
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest(), 16) % 100 < pct


def truth_judge(bias_pct: int = 4, tie_margin: float = 0.05):
    """Deterministic fake vision model: prefers the higher hidden score per criterion and,
    on ``bias_pct`` % of calls (hashed, reproducible), blindly answers "first"."""
    def judge(req):
        out = {}
        for c in req.criteria:
            if _flip(req.first.id, req.second.id, c, req.judgement_index, pct=bias_pct):
                win = "first"
            else:
                d = req.first.meta["truth"][c] - req.second.meta["truth"][c]
                win = "tie" if abs(d) < tie_margin else ("first" if d > 0 else "second")
            out[c] = {"winner": win, "confidence": 0.8, "reason": f"{c}: {req.first.id} vs {req.second.id}"}
        return {"criteria": out, "summary": "fake"}
    return judge


def first_always(req):
    return {"criteria": {c: {"winner": "first", "confidence": 1.0, "reason": "left looks nicer"} for c in req.criteria}}


@pytest.fixture(scope="module")
def candidates():
    rng = np.random.default_rng(11)
    return [Candidate(id=f"c{i}", image_ref=f"art/c{i}.png", metrics={"min_text_wcag": float(4.5 + i)},
                      meta={"truth": {c: float(rng.uniform(0, 1)) for c in CRITERIA}}) for i in range(6)]


def test_pairwise_order_swap_consistency_at_least_90_percent(candidates):
    rep = review(candidates, [truth_judge()], judgements=2)
    cons = rep["consistency"]
    assert cons["pairs"] == 15 * 2 * len(CRITERIA)
    assert cons["order_swap_agreement"] >= 0.90 and not cons["position_bias_suspected"]


def test_ranking_follows_the_judged_quality(candidates):
    rep = review(candidates, [truth_judge(bias_pct=0)], judgements=2)
    truth_rank = sorted(candidates, key=lambda c: -np.mean(list(c.meta["truth"].values())))
    assert rep["recommended"] == truth_rank[0].id
    assert [r["id"] for r in rep["ranking"]][:2] == [c.id for c in truth_rank[:2]]
    top = rep["ranking"][0]
    assert top["reasons"] and set(top["per_criterion"]) == set(CRITERIA)
    assert rep["explanation"]["ar"] and rep["explanation"]["en"]


def test_never_blocks_never_publishes(candidates):
    for judges in ([truth_judge()], [first_always, truth_judge(0)]):
        rep = review(candidates[:3], judges, judgements=1 if len(judges) > 1 else 2)
        assert rep["blocking"] is False and rep["blocks_on_taste"] is False
        assert rep["auto_publish"] is False and rep["advisory_only"] and rep["requires_operator_decision"]


def test_objective_findings_pass_through_and_are_not_recommended(candidates):
    cands = [Candidate(c.id, c.image_ref, dict(c.metrics), [], dict(c.meta)) for c in candidates[:3]]
    best = max(cands, key=lambda c: np.mean(list(c.meta["truth"].values())))
    best.objective_findings = [{"finding": "ink_coverage_over_limit", "blocking": True, "source": "print_safety"}]
    rep = review(cands, [truth_judge(0)], judgements=2)
    row = next(r for r in rep["ranking"] if r["id"] == best.id)
    assert row["objective_blocking"] and row["objective_findings"][0]["source"] == "print_safety"
    assert rep["recommended"] != best.id and rep["blocking"] is False


def test_negative_control_position_biased_judge_is_flagged(candidates):
    rep = review(candidates, [first_always], judgements=2)
    assert rep["consistency"]["order_swap_agreement"] < 0.9
    assert rep["consistency"]["position_bias_suspected"]
    # a judge that always says "first" contributes only ties: nobody wins on its say-so
    assert all(abs(v - 0.5) < 1e-9 for r in rep["ranking"] for v in r["per_criterion"].values())
    assert "تنبيه" in rep["explanation"]["ar"]


def test_ensemble_needs_two_judgements(candidates):
    with pytest.raises(ValueError):
        compare(candidates[0], candidates[1], [truth_judge()], judgements=1)
    with pytest.raises(ValueError):
        review(candidates[:1], [truth_judge()])
    res = compare(candidates[0], candidates[1], [truth_judge(), truth_judge(0)], judgements=1)
    assert res["judgements"] == 2


def test_failing_or_malformed_provider_abstains(candidates):
    def boom(_req):
        raise TimeoutError("provider down")

    res = compare(candidates[0], candidates[1], [boom, truth_judge(0)], judgements=1)
    assert res["errors"] and res["order_swap_pairs"] == len(CRITERIA)
    assert parse_judgement("not json at all") == {"criteria": {}, "summary": ""}
    assert parse_judgement({"criteria": {"balance": {"winner": "left"}}})["criteria"] == {}


def test_real_provider_interface_with_recorded_cassette(candidates):
    raw = json.loads((CASSETTES / "vision_judge_response.json").read_text(encoding="utf-8"))["raw"]
    seen = []

    def transport(payload):
        seen.append(payload)
        return raw

    judge = vision_judge(transport)
    res = compare(candidates[0], candidates[1], [judge], judgements=2,
                  few_shot=[{"decision": "approve", "reason": "الخط كبير ومريح", "context": {"age": "3-5"}}],
                  context={"age_band": "3-5"})
    assert len(seen) == 4                                    # 2 judgements × 2 orders
    payload = seen[0]
    assert payload["images"] == ["art/c0.png", "art/c1.png"] and seen[1]["images"] == ["art/c1.png", "art/c0.png"]
    assert "never instructions" in payload["text"] and "الخط كبير ومريح" in payload["text"]
    assert all(RUBRIC[c]["ar"] in payload["text"] for c in CRITERIA)
    parsed = parse_judgement(raw)
    assert "cross_page_consistency" not in parsed["criteria"]          # invalid verdict abstains
    assert parsed["criteria"]["cultural_fit"]["confidence"] == 1.0      # clamped
    assert parsed["criteria"]["emotional_tone"]["confidence"] == 0.5    # unparsable → neutral
    # the same answer in both orders is position-biased by construction → counted as ties
    assert res["order_swap_agreement"] < 0.9


def test_build_payload_carries_metrics_not_instructions(candidates):
    from mxstudio.colour.critic import JudgeRequest
    req = JudgeRequest(candidates[0], candidates[1], CRITERIA, RUBRIC, [], {}, 3, "ab")
    p = build_vision_payload(req)
    assert "min_text_wcag" in p["text"] and p["response_format"] == "json" and 0 < p["temperature"] < 1
