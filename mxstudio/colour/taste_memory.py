"""Taste memory: the operator's approvals/rejections, few-shot retrieval, reranker, agreement.

Rule: the operator's decision is the ground truth for taste. Every approval or rejection
(with an optional one-line reason) is stored in SQLite with the critic's prediction at
the time, the critic's per-criterion features and the deterministic metrics. From that
record the Studio

* retrieves few-shot examples for the vision judge (recent, same age band/page kind
  first, approvals and rejections balanced);
* fits reranker weights (L2-regularised logistic regression on the stored features,
  deterministic) so the critic's ranking moves toward the operator's taste;
* reports the critic–operator agreement rate over time (per day/week/month).

Nothing here decides or publishes anything; it remembers and measures.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from .critic import CRITERIA, default_weights

SCHEMA_VERSION = 1
MIN_TRAINING = 8
MAX_REASON = 200

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  deck_id TEXT, page_id TEXT, candidate_id TEXT NOT NULL,
  decision TEXT NOT NULL CHECK (decision IN ('approve', 'reject')),
  reason TEXT,
  critic_recommended INTEGER,           -- 1/0: did the critic recommend this candidate? NULL = no critic run
  critic_score REAL,
  features TEXT NOT NULL DEFAULT '{}',  -- per-criterion win rates from the critic
  metrics TEXT NOT NULL DEFAULT '{}',   -- deterministic facts
  context TEXT NOT NULL DEFAULT '{}',   -- age band, page kind, theme…
  image_ref TEXT
);
CREATE INDEX IF NOT EXISTS decisions_ts ON decisions(ts);
CREATE TABLE IF NOT EXISTS reranker_weights (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  trained_at TEXT NOT NULL, n INTEGER NOT NULL, weights TEXT NOT NULL, train_accuracy REAL
);
"""


def default_db_path() -> Path:
    from mxstudio.config import app_home

    return app_home() / "taste_memory.sqlite"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class TasteMemory:
    """SQLite-backed store. ``path=":memory:"`` is accepted for tests."""

    def __init__(self, path: str | Path | None = None):
        self.path = str(path or default_db_path())
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        with self._conn:
            self._conn.executescript(_SCHEMA)
            self._conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)",
                               (str(SCHEMA_VERSION),))

    def close(self) -> None:
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ------------------------------------------------------------ decisions
    def record(self, candidate_id: str, decision: str, reason: str | None = None, *,
               deck_id: str | None = None, page_id: str | None = None,
               critic_recommended: bool | None = None, critic_score: float | None = None,
               features: Mapping[str, float] | None = None, metrics: Mapping[str, Any] | None = None,
               context: Mapping[str, Any] | None = None, image_ref: str | None = None,
               ts: str | None = None) -> int:
        if decision not in ("approve", "reject"):
            raise ValueError("decision must be 'approve' or 'reject'")
        reason = (" ".join(str(reason).split())[:MAX_REASON]) if reason else None
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO decisions(ts, deck_id, page_id, candidate_id, decision, reason, critic_recommended,"
                " critic_score, features, metrics, context, image_ref) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (ts or _now(), deck_id, page_id, candidate_id, decision, reason,
                 None if critic_recommended is None else int(bool(critic_recommended)), critic_score,
                 json.dumps(dict(features or {}), ensure_ascii=False),
                 json.dumps(dict(metrics or {}), ensure_ascii=False, default=str),
                 json.dumps(dict(context or {}), ensure_ascii=False), image_ref))
        return int(cur.lastrowid)

    def record_review(self, review: Mapping, chosen_id: str, reasons: Mapping[str, str] | None = None, *,
                      deck_id: str | None = None, page_id: str | None = None,
                      context: Mapping[str, Any] | None = None, ts: str | None = None) -> list[int]:
        """Operator picked ``chosen_id`` out of a critic review: one approve + rejects for the rest."""
        ids = []
        for row in review["ranking"]:
            ids.append(self.record(
                row["id"], "approve" if row["id"] == chosen_id else "reject", (reasons or {}).get(row["id"]),
                deck_id=deck_id, page_id=page_id, critic_recommended=row["id"] == review.get("recommended"),
                critic_score=row["score"], features=row["per_criterion"],
                metrics={k: v for k, v in row["metrics"].items() if isinstance(v, (int, float))},
                context=context, ts=ts))
        return ids

    def decisions(self) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM decisions ORDER BY ts, id").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            for key in ("features", "metrics", "context"):
                d[key] = json.loads(d[key] or "{}")
            out.append(d)
        return out

    # ------------------------------------------------------------ few-shot
    def few_shot(self, k: int = 6, context: Mapping[str, Any] | None = None) -> list[dict]:
        """Recent decisions, those sharing context values first, approvals/rejections interleaved."""
        context = dict(context or {})
        rows = self.decisions()[::-1]  # newest first

        def overlap(d):
            return sum(1 for key, v in context.items() if d["context"].get(key) == v)

        rows.sort(key=lambda d: -overlap(d))  # stable: keeps recency inside equal overlap
        app = [d for d in rows if d["decision"] == "approve"]
        rej = [d for d in rows if d["decision"] == "reject"]
        mixed = []
        while (app or rej) and len(mixed) < k:
            if app:
                mixed.append(app.pop(0))
            if rej and len(mixed) < k:
                mixed.append(rej.pop(0))
        return [{"decision": d["decision"], "reason": d["reason"], "context": d["context"],
                 "features": d["features"], "candidate_id": d["candidate_id"], "image_ref": d["image_ref"]}
                for d in mixed]

    # ------------------------------------------------------------ reranker
    def fit_reranker(self, criteria: Sequence[str] = CRITERIA, metric_names: Sequence[str] = (),
                     l2: float = 0.05, iterations: int = 2000, lr: float = 0.5) -> dict:
        """Logistic regression approve ~ criteria win rates (+ named metrics). Deterministic."""
        data = [d for d in self.decisions() if d["features"]]
        labels = np.array([1.0 if d["decision"] == "approve" else 0.0 for d in data])
        if len(data) < MIN_TRAINING or labels.min(initial=1) == labels.max(initial=0):
            w = default_weights(criteria)
            w["note"] = f"insufficient data ({len(data)} decisions; need ≥ {MIN_TRAINING} with both outcomes)"
            return w
        names = list(criteria) + list(metric_names)
        X = np.array([[float(d["features"].get(c, 0.5)) for c in criteria]
                      + [float(d["metrics"].get(m, 0.0)) for m in metric_names] for d in data])
        mu = X.mean(axis=0)
        sd = X.std(axis=0)
        sd[sd == 0] = 1.0
        Z = (X - mu) / sd
        w = np.zeros(Z.shape[1])
        b = 0.0
        for _ in range(iterations):
            p = 1.0 / (1.0 + np.exp(-(Z @ w + b)))
            g = Z.T @ (p - labels) / len(labels) + l2 * w
            w -= lr * g
            b -= lr * float(np.mean(p - labels))
        acc = float(np.mean(((1.0 / (1.0 + np.exp(-(Z @ w + b)))) >= 0.5) == (labels == 1.0)))
        # fold standardisation back into raw-feature weights
        raw = w / sd
        bias = b - float(np.sum(w * mu / sd))
        weights = {"criteria": {c: round(float(raw[i]), 6) for i, c in enumerate(criteria)},
                   "metrics": {m: round(float(raw[len(criteria) + i]), 6) for i, m in enumerate(metric_names)},
                   "bias": round(bias, 6), "source": "taste_memory", "n": len(data),
                   "train_accuracy": round(acc, 4), "names": names}
        with self._conn:
            self._conn.execute("INSERT INTO reranker_weights(trained_at, n, weights, train_accuracy) VALUES (?,?,?,?)",
                               (_now(), len(data), json.dumps(weights), acc))
        return weights

    def latest_weights(self, criteria: Sequence[str] = CRITERIA) -> dict:
        row = self._conn.execute("SELECT weights FROM reranker_weights ORDER BY id DESC LIMIT 1").fetchone()
        return json.loads(row["weights"]) if row else default_weights(criteria)

    # ------------------------------------------------------------ agreement
    def agreement(self, bucket: str = "week") -> dict:
        """Critic–operator agreement over time.

        A decision agrees when (operator approved) == (critic recommended it). Decisions
        recorded without a critic run are excluded.
        """
        rows = [d for d in self.decisions() if d["critic_recommended"] is not None]
        series: dict[str, list[int]] = {}
        for d in rows:
            key = _bucket(d["ts"], bucket)
            agree = int((d["decision"] == "approve") == bool(d["critic_recommended"]))
            series.setdefault(key, []).append(agree)
        points = [{"period": k, "n": len(v), "agree": sum(v), "rate": round(sum(v) / len(v), 4)}
                  for k, v in sorted(series.items())]
        total = sum(p["n"] for p in points)
        agree = sum(p["agree"] for p in points)
        return {"bucket": bucket, "points": points, "n": total,
                "overall_rate": round(agree / total, 4) if total else None,
                "trend": round(points[-1]["rate"] - points[0]["rate"], 4) if len(points) >= 2 else None}


def _bucket(ts: str, bucket: str) -> str:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if bucket == "day":
        return dt.strftime("%Y-%m-%d")
    if bucket == "month":
        return dt.strftime("%Y-%m")
    if bucket == "week":
        y, w, _ = dt.isocalendar()
        return f"{y}-W{w:02d}"
    raise ValueError("bucket must be day, week or month")


def agreement_report(memory: TasteMemory, bucket: str = "week", min_n: int = 10) -> dict:
    """Bilingual scaffold for the Console's "is the critic learning my taste?" panel."""
    a = memory.agreement(bucket)
    enough = a["n"] >= min_n
    rate = a["overall_rate"]
    if not enough:
        ar = f"لسه البيانات قليلة ({a['n']} قرار) — محتاجين {min_n} على الأقل عشان نحكم على نسبة الاتفاق."
        en = f"Not enough decisions yet ({a['n']}); at least {min_n} are needed to read the agreement rate."
    else:
        pct = round(100 * rate)
        ar = f"الناقد اتفق معاك في {pct}% من القرارات ({a['n']} قرار)."
        en = f"The critic agreed with you on {pct}% of decisions ({a['n']} decisions)."
        if a["trend"] is not None:
            ar += " الاتجاه: " + ("بيتحسّن" if a["trend"] > 0 else "ثابت" if a["trend"] == 0 else "بيقلّ") + "."
            en += " Trend: " + ("improving" if a["trend"] > 0 else "flat" if a["trend"] == 0 else "declining") + "."
    return {"title": {"ar": "اتفاق الناقد مع ذوقك", "en": "Critic agreement with your taste"},
            "summary": {"ar": ar, "en": en}, "enough_data": enough, "series": a["points"],
            "overall_rate": rate, "n": a["n"], "bucket": bucket,
            "columns": [{"key": "period", "ar": "الفترة", "en": "Period"},
                        {"key": "n", "ar": "عدد القرارات", "en": "Decisions"},
                        {"key": "rate", "ar": "نسبة الاتفاق", "en": "Agreement"}]}


def import_decisions(memory: TasteMemory, rows: Iterable[Mapping]) -> int:
    """Bulk import (e.g. from a previous machine's export)."""
    n = 0
    for r in rows:
        memory.record(r["candidate_id"], r["decision"], r.get("reason"), deck_id=r.get("deck_id"),
                      page_id=r.get("page_id"), critic_recommended=r.get("critic_recommended"),
                      critic_score=r.get("critic_score"), features=r.get("features"), metrics=r.get("metrics"),
                      context=r.get("context"), image_ref=r.get("image_ref"), ts=r.get("ts"))
        n += 1
    return n
