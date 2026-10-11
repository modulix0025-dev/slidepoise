"""ModuleX inter-system request signing — THE contract, in one copyable file.

    Copy this file verbatim into any system that talks to the ModuleX
    Orchestrator. Do not edit it. Do not "adapt" it. If you change the
    canonical string here, you have forked the contract and every signed
    call between your system and the hub will 401 — silently, in both
    directions, with your own test suite still green.

Why that warning is not boilerplate: it already happened. Three systems each
implemented a *different* canonical string under the *same* header names. Every
suite signed with its own sign() and verified with its own sign(), so all three
passed while nothing worked. This file exists so that "the shared scheme" is a
file you copy, not a paragraph you re-implement.

THE SCHEME
----------
    canonical = METHOD_UPPER + "\\n" + PATH + "\\n" + TIMESTAMP + "\\n" + sha256_hex(raw_body)

    X-ModuleX-Timestamp : unix seconds, as a string
    X-ModuleX-Signature : lowercase hex of hmac_sha256(secret, canonical)
                          NO "sha256=" prefix. Bare hex.
    X-ModuleX-Key-Id    : optional, defaults to "default"

    PATH is the path only — no scheme, no host, no query string.
    Empty body hashes as sha256(b"").
    Requests outside ±300s of the server clock are refused.

The two rules people get wrong:

  1. **Sign the exact bytes you put on the wire.** Serialize once, hash those
     bytes, send those bytes. `json.dumps` twice with different key ordering
     produces two different hashes of "the same" body. In httpx that means
     `content=raw`, never `json=obj`.
  2. **METHOD and PATH are in the canonical string, and that is the point.**
     A scheme that signs only the timestamp and the body hash cannot tell
     /progress from /drain, so a signature captured off a harmless endpoint
     replays onto a destructive one inside the skew window. That is why this
     scheme won and the shorter ones did not.

SELF-TEST
---------
    python -m contrib.modulex_signing --selftest    # from the repo root
    python modulex_signing.py --selftest            # from anywhere

Exit code 0 means this file computes the five frozen vectors that the whole
ecosystem is pinned to. If it exits 1, the contract is broken and nothing
downstream is worth debugging until it exits 0 again.

DEPENDENCIES
------------
stdlib only, and it stays that way. No imports from `orchestrator.*`, no
settings object, no logger, no framework. The secret is an argument.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import threading
import time

__all__ = [
    "HEADER_TS", "HEADER_SIG", "HEADER_KEY_ID", "DEFAULT_KEY_ID",
    "MAX_SKEW_SECONDS", "canonical_string", "signature", "sign", "verify",
    "resolve_secret_from_env", "TEST_SECRET", "TEST_VECTORS", "selftest",
    # Phase 2 (C10) anti-replay — additive; does not alter the signing bytes.
    "ReplayGuard", "check_replay", "anti_replay_enabled",
    "ANTI_REPLAY_ENV", "REPLAY_TTL_ENV", "REPLAY_MAX_ENV",
]

# --------------------------------------------------------------- constants ---

HEADER_TS = "X-ModuleX-Timestamp"
HEADER_SIG = "X-ModuleX-Signature"
HEADER_KEY_ID = "X-ModuleX-Key-Id"

DEFAULT_KEY_ID = "default"
MAX_SKEW_SECONDS = 300

# The env var names each system historically used for the same shared secret.
# Order is deliberate: the converged name first, the legacy names after it, so a
# system can adopt MODULEX_HMAC_SECRET without a flag day and drop the old name
# whenever it likes. All of them must resolve to the SAME string at runtime —
# a mismatch here looks exactly like a wrong canonical string from the outside,
# which is an afternoon of debugging the wrong thing.
SECRET_ENV_NAMES = ("MODULEX_HMAC_SECRET", "ORCHESTRATOR_HMAC_SECRET", "API_HMAC_SECRET")


# ----------------------------------------------------------------- signing ---

def canonical_string(method: str, path: str, timestamp: str | int, body: bytes | None) -> str:
    """The exact string that gets HMAC'd. This function IS the contract.

    Every argument is load-bearing:
      method    — upper-cased here, so callers cannot get it wrong
      path      — path only. Strip scheme, host and query BEFORE calling.
      timestamp — the same value you put in X-ModuleX-Timestamp, as a string
      body      — the exact bytes on the wire; None and b"" both hash as sha256(b"")
    """
    body_hash = hashlib.sha256(body or b"").hexdigest()
    return "\n".join([method.upper(), path, str(timestamp), body_hash])


def signature(secret: str, method: str, path: str, timestamp: str | int,
              body: bytes | None = b"") -> str:
    """Lowercase hex HMAC-SHA256 of the canonical string. No prefix, ever."""
    canonical = canonical_string(method, path, timestamp, body)
    return hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()


def sign(secret: str, method: str, path: str, body: bytes | None = b"",
         timestamp: str | int | None = None, key_id: str | None = DEFAULT_KEY_ID) -> dict[str, str]:
    """Build the headers for one outbound request.

        raw = json.dumps(payload).encode()          # serialize ONCE
        headers = sign(SECRET, "POST", "/v1/workers/register", raw)
        httpx.post(base + "/v1/workers/register", content=raw, headers=headers)
                                                    # ^ the same bytes you hashed

    `timestamp` is for tests and known-answer vectors; leave it None in
    production so the clock is read at send time and the skew window is spent on
    the network rather than on however long your object sat in a queue.
    """
    ts = str(timestamp) if timestamp is not None else str(int(time.time()))
    headers = {HEADER_TS: ts, HEADER_SIG: signature(secret, method, path, ts, body)}
    if key_id:
        headers[HEADER_KEY_ID] = key_id
    return headers


def verify(
    *,
    secret: str,
    method: str,
    path: str,
    body: bytes | None,
    timestamp: str | None,
    signature: str | None,  # noqa: A002 — the header's name; shadowing is local and intended
    max_skew_seconds: int = MAX_SKEW_SECONDS,
    now: float | None = None,
) -> tuple[bool, str]:
    """Check one inbound request. Returns (ok, reason).

    Order matters and is not negotiable: shape, then clock, then signature.
    Checking the signature first would let an attacker replay a captured
    signature forever, because a stale-but-genuine signature verifies fine — the
    clock is the only thing that makes it stale.

    The compare is constant-time. A byte-by-byte `==` on an HMAC leaks the
    correct prefix through timing, which is enough to forge one given patience.
    """
    if not timestamp or not signature:
        return False, "missing signature headers"
    try:
        ts = int(float(timestamp))
    except ValueError:
        return False, "invalid timestamp"
    current = now if now is not None else time.time()
    if abs(current - ts) > max_skew_seconds:
        return False, "timestamp outside allowed skew"
    # Inlined rather than calling signature() — the parameter above shadows it,
    # and this is also the exact expression the Orchestrator's hmac_signing.py
    # runs, which is the point: two files, one behaviour, no adaptation layer.
    expected = hmac.new(secret.encode(),
                        canonical_string(method, path, str(ts), body).encode(),
                        hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return False, "signature mismatch"
    return True, "ok"


def resolve_secret_from_env(env: dict | None = None) -> tuple[str, str] | tuple[None, None]:
    """Find the shared secret under whichever name this system already uses.

    Returns (value, env_var_name_it_came_from), or (None, None).

    Console reads ORCHESTRATOR_HMAC_SECRET and falls back to API_HMAC_SECRET;
    Video Injection reads ORCHESTRATOR_HMAC_SECRET; the Orchestrator reads
    MODULEX_HMAC_SECRET. Same secret, three names — so back-compat is a lookup
    chain, not a migration. Log the returned name at boot: "which of my three
    env vars actually won" is otherwise unanswerable from the outside, and it is
    the first thing you want to know when one side 401s.
    """
    src = os.environ if env is None else env
    for name in SECRET_ENV_NAMES:
        value = (src.get(name) or "").strip()
        if value:
            return value, name
    return None, None


# ---------------------------------------------------------- known answers ---

# Published on purpose. This secret authenticates nothing anywhere — it exists so
# that two systems can prove they agree without sharing a real secret, without a
# live handshake, and without either one being trusted.
TEST_SECRET = "modulex-contract-test-secret-do-not-use-in-prod"

# The five frozen vectors. These are the ecosystem's tripwire: if a change to
# canonical_string() ever alters one of these hexes, every contract test in every
# system fails at once and loudly, instead of one integration failing quietly at
# 3am six weeks later. Do not "update the expected values to make the test pass".
TEST_VECTORS: tuple[dict, ...] = (
    {
        "name": "register",
        "method": "POST",
        "path": "/v1/workers/register",
        "timestamp": "1700000000",
        "body": b'{"system_type":"execution-console"}',
        "signature": "f427a98f74baf23488c17c5f7ee2f8808f9ce13690251c10009085edd42da6ea",
    },
    {
        "name": "assign",
        "method": "POST",
        "path": "/v1/jobs/7f3a/assign",
        "timestamp": "1700000000",
        "body": b'{"job_id":"7f3a","idempotency_key":"k1"}',
        "signature": "71a838397a78018ef54869a81af1da27aa9f955e8e3ece30422210e5821b77b9",
    },
    {
        "name": "heartbeat",
        "method": "POST",
        "path": "/v1/workers/91cd/heartbeat",
        "timestamp": "1700000000",
        "body": b'{"utilization":0.5}',
        "signature": "becacb49a88fe6596c5e80990dcf6c4844e933275211d7f994436a8fb8087794",
    },
    {
        # Empty body on a POST. The one everybody's implementation gets wrong,
        # because "no body" invites `None` and `None` invites a TypeError that
        # invites a special case that hashes something other than sha256(b"").
        "name": "drain",
        "method": "POST",
        "path": "/v1/workers/91cd/drain",
        "timestamp": "1700000000",
        "body": b"",
        "signature": "ddb8d5a86f6abda80e9cb0e44f251fde1c1bb2ba452c9ed5f6df6593629b67cc",
    },
    {
        # A GET is signed exactly like anything else. There is no "reads don't
        # need signing" case, and the method really is in the string.
        "name": "health",
        "method": "GET",
        "path": "/v1/health",
        "timestamp": "1700000000",
        "body": b"",
        "signature": "d503333f1c41f2380198754d24165c82f1505ae60a10edf8f99e3d3124ed25f5",
    },
)


# ----------------------------------------------------------- anti-replay ---
#
# Phase 2 (C10). ADDITIVE — nothing above this line changed, so the five frozen
# vectors and every signature on the wire are byte-identical. `verify()` is
# stateless: it answers "is this signature valid and inside the skew window?" but
# cannot answer "have I seen THIS exact signature before?", so a signature captured
# off a signed pairing call replays successfully for the whole ±MAX_SKEW_SECONDS
# window. This guard closes that with a bounded, TTL'd cache of signatures already
# seen inside the window — O(1) amortized to detect, memory capped. ONE
# implementation, vendored into all four systems, called from each router's single
# signed-request chokepoint. Default-on; one env flag disables it (rollback).

ANTI_REPLAY_ENV = "MODULEX_ANTI_REPLAY_ENABLED"     # default: on
REPLAY_TTL_ENV = "MODULEX_REPLAY_TTL_SECONDS"       # default: MAX_SKEW_SECONDS
REPLAY_MAX_ENV = "MODULEX_REPLAY_MAX_ENTRIES"       # default: 100_000


def anti_replay_enabled(env: dict | None = None) -> bool:
    raw = (os.environ if env is None else env).get(ANTI_REPLAY_ENV)
    if raw is None:
        return True                                  # default ON
    return str(raw).strip().lower() not in ("0", "false", "no", "off", "")


class ReplayGuard:
    """Bounded, TTL'd seen-signature cache. O(1) amortized; thread-safe.

    A signature is remembered for `ttl` seconds (defaults to the skew window): a
    replay OUTSIDE that window is already refused by verify()'s clock check, so
    nothing older need be remembered. Memory is capped at `max_entries`; when full,
    expired entries are swept, then the oldest is evicted (dicts keep insertion
    order). `scope` (e.g. the peer id) namespaces the key so one peer's signature
    cannot mask another's."""

    __slots__ = ("_ttl", "_max", "_seen", "_lock")

    def __init__(self, ttl_seconds: int | None = None, max_entries: int | None = None,
                 env: dict | None = None) -> None:
        e = os.environ if env is None else env
        self._ttl = int(ttl_seconds if ttl_seconds is not None else (e.get(REPLAY_TTL_ENV) or MAX_SKEW_SECONDS))
        self._max = int(max_entries if max_entries is not None else (e.get(REPLAY_MAX_ENV) or 100_000))
        self._seen: dict[str, float] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(signature: str, scope: str) -> str:
        return f"{scope}\x00{signature}" if scope else signature

    def seen(self, signature: str, *, scope: str = "", now: float | None = None) -> tuple[bool, str]:
        """Record `signature` and report whether it was ALREADY seen (a replay).

        Returns (is_replay, reason). A first sighting is recorded and returns
        (False, "fresh"); a repeat within the TTL returns (True, ...)."""
        if not signature:
            return False, "no signature"
        t = time.time() if now is None else now
        key = self._key(signature, scope)
        with self._lock:
            exp = self._seen.get(key)
            if exp is not None and exp > t:
                return True, "replayed signature within the skew window"
            if len(self._seen) >= self._max:                 # bound memory — O(1)
                # Every entry carries the SAME ttl, so insertion order is expiry
                # order: the oldest key is always the earliest to expire. Evicting
                # it (dicts keep insertion order) is therefore both correct and
                # O(1) — no full scan of the cache on the hot path.
                self._seen.pop(next(iter(self._seen)))
            self._seen[key] = t + self._ttl
            return False, "fresh"

    def size(self) -> int:
        with self._lock:
            return len(self._seen)


# Process-wide default guard — reused by every signed-request check in this
# deployable (each of the four systems runs its own process, so this is per-system).
_DEFAULT_REPLAY_GUARD = ReplayGuard()


def check_replay(signature: str, *, scope: str = "", now: float | None = None,
                 guard: "ReplayGuard | None" = None, env: dict | None = None) -> tuple[bool, str]:
    """Router-facing helper, called AFTER verify() succeeds.

    Returns (ok, reason): ok=True means fresh (or the check is disabled by flag)
    and the request may proceed; ok=False means a replay was detected and the
    request MUST be rejected. Default-on; MODULEX_ANTI_REPLAY_ENABLED=0 disables
    it as a one-switch rollback."""
    if not anti_replay_enabled(env):
        return True, "anti-replay disabled by flag"
    g = _DEFAULT_REPLAY_GUARD if guard is None else guard
    is_replay, reason = g.seen(signature, scope=scope, now=now)
    return (not is_replay), reason


def selftest() -> list[dict]:
    """Run the five vectors. Returns one result row per vector; never raises."""
    rows = []
    for v in TEST_VECTORS:
        got = signature(TEST_SECRET, v["method"], v["path"], v["timestamp"], v["body"])
        rows.append({
            "name": v["name"],
            "method": v["method"],
            "path": v["path"],
            "expected": v["signature"],
            "got": got,
            "ok": hmac.compare_digest(got, v["signature"]),
        })
    return rows


def _main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        prog="modulex_signing",
        description="ModuleX signing contract — reference implementation and self-test.")
    ap.add_argument("--selftest", action="store_true",
                    help="check this file against the five frozen vectors")
    ap.add_argument("--show", action="store_true",
                    help="print the canonical string of each vector, \\n shown as \\\\n")
    args = ap.parse_args(argv)

    if not (args.selftest or args.show):
        ap.print_help()
        return 0

    if args.show:
        for v in TEST_VECTORS:
            c = canonical_string(v["method"], v["path"], v["timestamp"], v["body"])
            print(f'{v["name"]:>10} : {c!r}')
        print()

    if args.selftest:
        rows = selftest()
        width = max(len(r["name"]) for r in rows)
        for r in rows:
            print(f'{"PASS" if r["ok"] else "FAIL"}  {r["name"]:<{width}}  '
                  f'{r["method"]} {r["path"]}')
            if not r["ok"]:
                print(f'      expected {r["expected"]}')
                print(f'      got      {r["got"]}')
        bad = [r for r in rows if not r["ok"]]
        if bad:
            print(f"\n{len(bad)}/{len(rows)} vectors FAILED — this file does not implement "
                  f"the ModuleX contract. Do not ship it.")
            return 1
        print(f"\n{len(rows)}/{len(rows)} vectors pass — this file implements the ModuleX contract.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
