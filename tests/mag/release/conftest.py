"""Fixtures for the release suites: test keys, a fake HTTP transport, an isolated app home."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from mxstudio.update import signing
from mxstudio.update.download import Response
from mxstudio.update.trust import Trust

ROOT = Path(__file__).resolve().parents[3]


class FakeServer:
    """In-memory HTTPS stand-in with Range support; can cut a transfer after N bytes."""

    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.cut_after: int | None = None
        self.requests: list[tuple[str, int]] = []
        self.ignore_range = False

    def add(self, url: str, data: bytes) -> str:
        self.files[url] = data
        return hashlib.sha256(data).hexdigest()

    def __call__(self, url: str, offset: int) -> Response:
        self.requests.append((url, offset))
        if url not in self.files:
            raise ConnectionRefusedError(url)
        data = self.files[url]
        if self.ignore_range:
            offset = 0
        status = 206 if offset else 200
        body = data[offset:]
        cut = self.cut_after

        def chunks():
            sent = 0
            for i in range(0, len(body), 1000):
                block = body[i:i + 1000]
                if cut is not None and sent + len(block) > cut:
                    yield block[: cut - sent]
                    raise ConnectionResetError("cut")
                sent += len(block)
                yield block

        return Response(status, len(data), chunks())


@pytest.fixture
def server() -> FakeServer:
    return FakeServer()


@pytest.fixture(scope="session")
def keypair() -> tuple[str, str]:
    return signing.generate_keypair()


@pytest.fixture
def trust(keypair) -> Trust:
    _, public = keypair
    return Trust(public_keys={signing.key_id(public): public},
                 manifest_url="https://github.com/o/r/releases/latest/download/latest.json")


@pytest.fixture
def home(tmp_path) -> Path:
    path = tmp_path / "بيانات الاستوديو"
    path.mkdir()
    return path
