"""Background worker process: leases jobs from the queue and runs the handler of each kind.

Feature areas contribute handlers through `mxstudio/<area>/jobs.py` exposing
`HANDLERS: dict[str, callable]` (payload dict -> result dict).
"""
from __future__ import annotations

import importlib
import json
import time

from mxstudio.app.features import AREAS
from mxstudio.config import app_home
from mxstudio.worker import JobQueue, Worker


def collect_handlers() -> dict:
    handlers = {}
    for area in AREAS:
        try:
            module = importlib.import_module(f"mxstudio.{area}.jobs")
        except ModuleNotFoundError:
            continue
        handlers.update(getattr(module, "HANDLERS", {}))
    return handlers


def main(argv: list[str] | None = None) -> int:
    argv = argv or []
    once = "--once" in argv
    worker = Worker(JobQueue(app_home() / "queue.sqlite3"), collect_handlers())
    while True:
        job = worker.run_once()
        if once:
            print(json.dumps({"ran": job["id"] if job else None, "state": job and job["state"]}))
            return 0
        if job is None:
            time.sleep(1.0)
