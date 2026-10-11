"""Taste memory: SQLite decisions, few-shot retrieval, reranker convergence, agreement over time."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from mxstudio.colour.critic import CRITERIA, Candidate, review
from mxstudio.colour.taste_memory import TasteMemory, agreement_report, import_decisions

START = datetime(2026, 9, 7, 9, 0, tzinfo=timezone.utc)  # a Monday


def ts(day: int) -> str:
    return (START + timedelta(days=day)).isoformat()


def honest_judge(req):
    out = {}
    for c in req.criteria:
        d = req.first.meta["truth"][c] - req.second.meta["truth"][c]
        out[c] = {"winner": "tie" if abs(d) < 0.03 else ("first" if d > 0 else "second"), "confidence": 0.9,
                  "reason": c}
    return {"criteria": out}


OPERATOR = {c: 0.0 for c in CRITERIA} | {"cultural_fit": 1.0, "age_readability": 0.6}


def operator_choice(cands):
    return max(cands, key=lambda c: sum(OPERATOR[k] * v for k, v in c.meta["truth"].items())).id


def test_record_persist_and_validate(tmp_path):
    db = tmp_path / "ذوق" / "taste.sqlite"            # Arabic path
    with TasteMemory(db) as mem:
        mem.record("p1", "approve", "الألوان دافية  وحلوة\n", context={"age": "3-5"}, ts=ts(0))
        mem.record("p2", "reject", None, ts=ts(1))
        with pytest.raises(ValueError):
            mem.record("p3", "maybe")
    with TasteMemory(db) as mem:
        rows = mem.decisions()
        assert [r["candidate_id"] for r in rows] == ["p1", "p2"]
        assert rows[0]["reason"] == "الألوان دافية وحلوة" and rows[0]["context"] == {"age": "3-5"}


def test_few_shot_is_balanced_and_context_first():
    mem = TasteMemory(":memory:")
    for i in range(6):
        mem.record(f"a{i}", "approve", f"ok {i}", context={"age": "6-8" if i < 3 else "3-5"}, ts=ts(i))
        mem.record(f"r{i}", "reject", f"no {i}", context={"age": "6-8" if i < 3 else "3-5"}, ts=ts(i))
    shots = mem.few_shot(k=4, context={"age": "6-8"})
    assert [s["decision"] for s in shots] == ["approve", "reject", "approve", "reject"]
    assert all(s["context"]["age"] == "6-8" for s in shots)
    assert shots[0]["candidate_id"] == "a2"                          # most recent first within the context


def test_reranker_needs_data_then_learns_the_operators_weights():
    mem = TasteMemory(":memory:")
    assert mem.fit_reranker()["source"] == "default_equal"
    rng = np.random.default_rng(4)
    for i in range(60):
        feats = {c: float(rng.uniform(0, 1)) for c in CRITERIA}
        approve = feats["cultural_fit"] + 0.6 * feats["age_readability"] > 0.8
        mem.record(f"x{i}", "approve" if approve else "reject", features=feats, ts=ts(i % 20))
    w = mem.fit_reranker()
    assert w["source"] == "taste_memory" and w["n"] == 60 and w["train_accuracy"] >= 0.85
    top = sorted(w["criteria"], key=lambda c: -w["criteria"][c])[:2]
    assert set(top) == {"cultural_fit", "age_readability"}
    assert mem.latest_weights() == w


def test_critic_converges_to_operator_taste_and_agreement_rises():
    rng = np.random.default_rng(9)
    mem = TasteMemory(":memory:")
    weights = None
    for rnd in range(48):
        day = rnd // 2                                   # 2 reviews per day, 24 days → 4 ISO weeks
        cands = [Candidate(f"r{rnd}c{i}", meta={"truth": {c: float(rng.uniform(0, 1)) for c in CRITERIA}})
                 for i in range(4)]
        rep = review(cands, [honest_judge], judgements=2, weights=weights, few_shot=mem.few_shot(4))
        mem.record_review(rep, operator_choice(cands), ts=ts(day), context={"age": "6-8"})
        if rnd == 15:                                    # retrain once enough decisions exist
            weights = mem.fit_reranker()
            assert weights["source"] == "taste_memory"
    series = mem.agreement("week")["points"]
    assert len(series) >= 3
    early, late = series[0]["rate"], np.mean([p["rate"] for p in series[-2:]])
    assert late > early
    report = agreement_report(mem, "week")
    assert report["enough_data"] and report["title"]["ar"] and report["summary"]["en"]
    assert report["overall_rate"] == mem.agreement("week")["overall_rate"]
    assert [c["key"] for c in report["columns"]] == ["period", "n", "rate"]


def test_agreement_definition_and_negative_controls():
    mem = TasteMemory(":memory:")
    assert agreement_report(mem)["enough_data"] is False and "قليلة" in agreement_report(mem)["summary"]["ar"]
    mem.record("a", "approve", critic_recommended=True, ts=ts(0))     # agree
    mem.record("b", "reject", critic_recommended=False, ts=ts(0))     # agree
    mem.record("c", "approve", critic_recommended=False, ts=ts(8))    # disagree
    mem.record("d", "reject", critic_recommended=True, ts=ts(8))      # disagree
    mem.record("e", "approve", ts=ts(9))                              # no critic run → excluded
    a = mem.agreement("week")
    assert a["n"] == 4 and a["overall_rate"] == 0.5
    assert [p["rate"] for p in a["points"]] == [1.0, 0.0] and a["trend"] == -1.0
    assert [p["period"] for p in mem.agreement("day")["points"]] == ["2026-09-07", "2026-09-15"]
    with pytest.raises(ValueError):
        mem.agreement("year")
    n = import_decisions(mem, [{"candidate_id": "z", "decision": "reject", "ts": ts(30)}])
    assert n == 1 and len(mem.decisions()) == 6
