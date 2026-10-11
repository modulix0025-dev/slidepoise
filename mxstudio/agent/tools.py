"""The Studio Agent acts only through typed tools.

* Every tool has a JSON Schema; arguments are validated server-side before the
  handler runs, and each handler re-checks its own preconditions.
* Irreversible tools (publish, delete, send to print, apply a Kit patch, install
  machine-wide fonts, activate a template set) need a human confirmation token.
  Tokens are minted only by the UI for the human operator, bound to the exact
  tool + arguments, expire, and are single-use. The agent has no way to mint one.
* Every call — accepted or refused — is written to the audit log.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jsonschema

TOKEN_TTL_SECONDS = 600
_REDACT_KEYS = {"api_key", "key", "secret", "password", "token", "child_photo", "photo"}


def canonical_args(args: dict[str, Any]) -> str:
    return json.dumps(args, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def args_digest(tool: str, args: dict[str, Any]) -> str:
    return hashlib.sha256(f"{tool}\n{canonical_args(args)}".encode("utf-8")).hexdigest()


class ToolError(RuntimeError):
    def __init__(self, code: str, message_ar: str, message_en: str, details: dict | None = None):
        super().__init__(message_en)
        self.code, self.message_ar, self.message_en, self.details = code, message_ar, message_en, details or {}

    def as_dict(self) -> dict:
        return {"ok": False, "code": self.code, "ar": self.message_ar, "en": self.message_en, "details": self.details}


@dataclass
class Tool:
    name: str
    description_ar: str
    description_en: str
    schema: dict
    handler: Callable[[dict[str, Any]], dict[str, Any]]
    irreversible: bool = False
    tags: list[str] = field(default_factory=list)

    def spec(self) -> dict:
        return {"name": self.name, "description_ar": self.description_ar, "description_en": self.description_en,
                "input_schema": self.schema, "irreversible": self.irreversible, "tags": self.tags}


class _Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self.db() as db:
            db.executescript("""
              CREATE TABLE IF NOT EXISTS tokens (hash TEXT PRIMARY KEY, tool TEXT, digest TEXT, issued_to TEXT,
                                                 expires REAL, used REAL);
              CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, actor TEXT, tool TEXT,
                                                args TEXT, outcome TEXT, code TEXT, token TEXT, summary TEXT);
            """)

    def db(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=30)
        db.execute("PRAGMA journal_mode=WAL")
        return db


class ConfirmationTokens:
    def __init__(self, store: _Store, clock=time.time):
        self.store, self.clock = store, clock

    def mint(self, tool: str, args: dict, human: str) -> str:
        """UI only. `human` is the authenticated UI session (never the agent)."""
        if not human or human.startswith("agent"):
            raise ToolError("TOKEN_FORBIDDEN", "التأكيد لازم يكون من إنسان من الشاشة.",
                            "confirmation tokens are issued to the human UI session only")
        token = secrets.token_urlsafe(24)
        with self.store._lock, self.store.db() as db:
            db.execute("INSERT INTO tokens VALUES (?,?,?,?,?,NULL)",
                       (hashlib.sha256(token.encode()).hexdigest(), tool, args_digest(tool, args), human,
                        self.clock() + TOKEN_TTL_SECONDS))
        return token

    def consume(self, token: str | None, tool: str, args: dict) -> str:
        if not token:
            raise ToolError("CONFIRMATION_REQUIRED", "الخطوة دي مالهاش رجوع ومحتاجة تأكيد منك من الشاشة.",
                            "this action is irreversible and needs a human confirmation token")
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with self.store._lock, self.store.db() as db:
            row = db.execute("SELECT tool, digest, expires, used, issued_to FROM tokens WHERE hash=?",
                             (token_hash,)).fetchone()
            if row is None:
                raise ToolError("TOKEN_INVALID", "التأكيد ده مش معروف.", "unknown confirmation token")
            bound_tool, digest, expires, used, issued_to = row
            if used is not None:
                raise ToolError("TOKEN_USED", "التأكيد ده اتستخدم قبل كده.", "confirmation token already used")
            if self.clock() > expires:
                raise ToolError("TOKEN_EXPIRED", "التأكيد انتهت صلاحيته.", "confirmation token expired")
            if bound_tool != tool or not hmac.compare_digest(digest, args_digest(tool, args)):
                raise ToolError("TOKEN_MISMATCH", "التأكيد ده لعملية تانية أو بيانات مختلفة.",
                                "confirmation token was issued for a different action or arguments")
            db.execute("UPDATE tokens SET used=? WHERE hash=?", (self.clock(), token_hash))
        return token_hash[:12]


class AuditLog:
    def __init__(self, store: _Store, clock=time.time):
        self.store, self.clock = store, clock

    @staticmethod
    def redact(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: ("[redacted]" if k.lower() in _REDACT_KEYS else AuditLog.redact(v)) for k, v in value.items()}
        if isinstance(value, list):
            return [AuditLog.redact(v) for v in value]
        return value

    def write(self, actor: str, tool: str, args: dict, outcome: str, code: str = "", token: str = "",
              summary: str = "") -> None:
        with self.store._lock, self.store.db() as db:
            db.execute("INSERT INTO audit (ts, actor, tool, args, outcome, code, token, summary) VALUES (?,?,?,?,?,?,?,?)",
                       (self.clock(), actor, tool, canonical_args(self.redact(args)), outcome, code, token,
                        summary[:500]))

    def entries(self, limit: int = 200) -> list[dict]:
        with self.store.db() as db:
            rows = db.execute("SELECT id, ts, actor, tool, args, outcome, code, token, summary FROM audit "
                              "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        keys = ("id", "ts", "actor", "tool", "args", "outcome", "code", "token", "summary")
        return [dict(zip(keys, row)) | {"args": json.loads(row[4])} for row in rows]


class ToolRegistry:
    def __init__(self, path: Path, clock=time.time):
        store = _Store(path)
        self.tokens = ConfirmationTokens(store, clock)
        self.audit = AuditLog(store, clock)
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> Tool:
        if tool.name in self._tools:
            raise ValueError(f"tool {tool.name} already registered")
        jsonschema.Draft202012Validator.check_schema(tool.schema)
        self._tools[tool.name] = tool
        return tool

    def specs(self) -> list[dict]:
        return [tool.spec() for tool in self._tools.values()]

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise ToolError("UNKNOWN_TOOL", "الأداة دي مش موجودة.", f"unknown tool {name!r}")
        return self._tools[name]

    def call(self, name: str, args: dict[str, Any], *, actor: str, confirmation_token: str | None = None) -> dict:
        try:
            tool = self.get(name)
            errors = sorted(jsonschema.Draft202012Validator(tool.schema).iter_errors(args), key=lambda e: e.path)
            if errors:
                raise ToolError("INVALID_ARGUMENTS", "البيانات اللي اتبعتت للأداة مش سليمة.",
                                "tool arguments failed schema validation",
                                {"errors": [f"{list(e.path)}: {e.message}" for e in errors[:10]]})
            token_ref = ""
            if tool.irreversible:
                token_ref = self.tokens.consume(confirmation_token, name, args)
            result = tool.handler(args)
        except ToolError as exc:
            self.audit.write(actor, name, args, "refused", exc.code)
            return exc.as_dict()
        except Exception as exc:  # noqa: BLE001 - every failure is reported and audited
            self.audit.write(actor, name, args, "error", type(exc).__name__, summary=str(exc))
            return {"ok": False, "code": "TOOL_FAILED", "ar": "الأداة فشلت.", "en": str(exc)}
        self.audit.write(actor, name, args, "ok", token=token_ref, summary=json.dumps(result, ensure_ascii=False)[:500])
        return {"ok": True, "result": result}
