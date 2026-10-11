"""Fixtures for the Phase 5 shape suites: cassette-backed HTTP (no network), temp library."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import httpx
import pytest

HERE = Path(__file__).resolve().parent
CASSETTES = HERE / "cassettes"
CORPUS = HERE / "corpus"
FIXTURES = HERE / "fixtures"


def _norm(url: str) -> tuple:
    parts = urlsplit(url)
    return (parts.scheme, parts.netloc, parts.path, tuple(sorted(parse_qsl(parts.query, keep_blank_values=True))))


class Cassette:
    """Replays recorded interactions; any request not in the cassette is a test failure."""

    def __init__(self, *names: str) -> None:
        self.interactions = []
        self.meta = []
        for name in names:
            data = json.loads((CASSETTES / name).read_text(encoding="utf-8"))
            self.meta.append(data.get("_meta", {}))
            self.interactions.extend(data["interactions"])
        self.calls: list[str] = []
        self.queues: dict[tuple, list] = {}
        for it in self.interactions:
            self.queues.setdefault(_norm(it["request"]["url"]), []).append(it["response"])

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.calls.append(url)
        key = _norm(url)
        queue = self.queues.get(key)
        if not queue:
            raise AssertionError(f"request not in cassette (tests never use the network): {url}")
        resp = queue.pop(0) if len(queue) > 1 else queue[0]
        body = resp.get("body_text")
        if body is None:
            body = json.dumps(resp.get("json"), ensure_ascii=False)
        headers = dict(resp.get("headers") or {})
        headers.setdefault("Content-Type", "application/json")
        return httpx.Response(resp.get("status", 200), headers=headers, content=body.encode("utf-8"))


@pytest.fixture
def cassette_client():
    """``make(*cassettes) -> (PoliteClient, Cassette)`` with zero-delay sleep recorded."""
    from mxstudio.shapes.discovery.base import PoliteClient

    def make(*names: str, cache_dir: Path | None = None):
        cas = Cassette(*names)
        sleeps: list[float] = []
        client = PoliteClient(httpx.Client(transport=httpx.MockTransport(cas)), cache_dir=cache_dir,
                              sleep=sleeps.append, min_interval=0.0)
        client.sleeps = sleeps
        return client, cas

    return make


@pytest.fixture
def library(tmp_path):
    from mxstudio.shapes.library import ShapeLibrary

    lib = ShapeLibrary(tmp_path / "library.sqlite3")
    yield lib
    lib.close()
