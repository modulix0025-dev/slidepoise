"""AI spend guard: estimate before calling, refuse past per-job / per-day ceilings, record actuals.

Self-hosted open-weight models (the D13 defaults) cost 0 per call here; the
operator can set a GPU-hour price so rented-GPU time is still counted.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

DAY = 86400


class BudgetExceeded(RuntimeError):
    def __init__(self, message_ar: str, message_en: str, facts: dict):
        super().__init__(message_en)
        self.message_ar, self.facts = message_ar, facts


@dataclass
class Prices:
    """USD prices. Unknown providers default to 0 (self-hosted) — set them in Settings."""
    per_1k_input_tokens: float = 0.0
    per_1k_output_tokens: float = 0.0
    per_image: float = 0.0
    per_gpu_second: float = 0.0


class BudgetGuard:
    def __init__(self, path: Path, per_job_usd: float, per_day_usd: float, clock=time.time):
        self.path, self.per_job, self.per_day, self.clock = Path(path), per_job_usd, per_day_usd, clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS spend (ts REAL, job TEXT, provider TEXT, usd REAL, kind TEXT)")

    def _db(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.execute("PRAGMA journal_mode=WAL")
        return db

    @staticmethod
    def estimate(prices: Prices, input_tokens: int = 0, output_tokens: int = 0, images: int = 0,
                 gpu_seconds: float = 0.0) -> float:
        return round(input_tokens / 1000 * prices.per_1k_input_tokens + output_tokens / 1000 * prices.per_1k_output_tokens
                     + images * prices.per_image + gpu_seconds * prices.per_gpu_second, 6)

    def spent(self, job: str | None = None, since: float | None = None) -> float:
        query, args = "SELECT COALESCE(SUM(usd),0) FROM spend WHERE 1=1", []
        if job:
            query += " AND job=?"
            args.append(job)
        if since is not None:
            query += " AND ts>=?"
            args.append(since)
        with self._db() as db:
            return float(db.execute(query, args).fetchone()[0])

    def check(self, job: str, estimate_usd: float) -> dict:
        day_spent = self.spent(since=self.clock() - DAY)
        job_spent = self.spent(job=job)
        facts = {"estimate_usd": estimate_usd, "job_spent_usd": job_spent, "day_spent_usd": day_spent,
                 "per_job_usd": self.per_job, "per_day_usd": self.per_day}
        if job_spent + estimate_usd > self.per_job + 1e-9:
            raise BudgetExceeded("العملية دي هتعدّي الحد المسموح للمهمة الواحدة.", "per-job AI budget would be exceeded",
                                 facts)
        if day_spent + estimate_usd > self.per_day + 1e-9:
            raise BudgetExceeded("وصلنا للحد اليومي لمصاريف الذكاء الاصطناعي.", "daily AI budget would be exceeded", facts)
        return facts

    def record(self, job: str, provider: str, usd: float, kind: str = "call") -> None:
        with self._lock, self._db() as db:
            db.execute("INSERT INTO spend VALUES (?,?,?,?,?)", (self.clock(), job, provider, float(usd), kind))

    def dashboard(self) -> dict:
        now = self.clock()
        with self._db() as db:
            rows = db.execute("SELECT provider, SUM(usd) FROM spend WHERE ts>=? GROUP BY provider", (now - DAY,)).fetchall()
        return {"day_usd": self.spent(since=now - DAY), "per_day_usd": self.per_day, "per_job_usd": self.per_job,
                "by_provider": {provider: round(total, 6) for provider, total in rows}}
