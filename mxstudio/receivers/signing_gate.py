"""The single signed-request chokepoint for every receiver route.

Order (from the contract): shape → clock → signature (``verify``), then ``check_replay``.
The signing module is the operator system's own ``modulex_signing.py`` — never re-implemented.
Refusals carry a named reason and an HTTP status: 503 no secret configured, 401 bad/missing
signature or stale timestamp, 409 replay.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from types import ModuleType
from typing import Any


@dataclass
class GateResult:
    ok: bool
    status: int
    reason: str
    key_id: str = ""


class SignedRequestGate:
    def __init__(self, signing: ModuleType, secret_resolver: Callable[[], Any] | None = None, *,
                 guard: Any = None, now: Callable[[], float] | None = None):
        self.signing = signing
        self.secret_resolver = secret_resolver or (lambda: signing.resolve_secret_from_env()[0])
        self.guard = guard
        self.now = now

    def check(self, method: str, path: str, body: bytes, headers: Any) -> GateResult:
        s = self.signing
        secret = self.secret_resolver()
        if not secret:
            return GateResult(False, 503, "no shared secret configured on this system")
        ts = headers.get(s.HEADER_TS)
        sig = headers.get(s.HEADER_SIG)
        key_id = headers.get(s.HEADER_KEY_ID) or s.DEFAULT_KEY_ID
        ok, reason = s.verify(secret=secret, method=method, path=path, body=body, timestamp=ts, signature=sig,
                              now=self.now() if self.now else None)
        if not ok:
            return GateResult(False, 401, reason, key_id)
        fresh, why = s.check_replay(sig, scope=f"mag:{key_id}", guard=self.guard,
                                    now=self.now() if self.now else None)
        if not fresh:
            return GateResult(False, 409, why, key_id)
        return GateResult(True, 200, "ok", key_id)
