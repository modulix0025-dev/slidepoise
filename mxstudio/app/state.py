"""Everything the server needs, built once from the app home and settings."""
from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from pathlib import Path

from mxstudio.agent.tools import ToolRegistry
from mxstudio.budget import BudgetGuard
from mxstudio.config import Settings, app_home
from mxstudio.secrets import SecretStore
from mxstudio.worker import JobQueue
from mxstudio.workspace import Workspace


@dataclass
class AppState:
    home: Path
    settings: Settings
    secrets: SecretStore
    workspace: Workspace
    queue: JobQueue
    budget: BudgetGuard
    tools: ToolRegistry
    shutdown_token: str = field(default_factory=lambda: secrets.token_urlsafe(24))
    sessions: dict[str, str] = field(default_factory=dict)  # session id -> csrf token
    closers: list = field(default_factory=list)  # long-lived handles (e.g. the shape library) closed by close()

    def close(self) -> None:
        """Release open files: on Windows an open SQLite handle blocks deleting or moving the workspace."""
        while self.closers:
            try:
                self.closers.pop()()
            except Exception:  # noqa: BLE001 - closing is best effort
                pass

    @classmethod
    def create(cls, home: Path | None = None) -> "AppState":
        home = Path(home or app_home())
        home.mkdir(parents=True, exist_ok=True)
        settings = Settings(home / "settings.json")
        loaded = settings.load()
        budget_cfg = loaded["budget"]
        state = cls(home=home, settings=settings, secrets=SecretStore(home / "secrets.json"),
                    workspace=Workspace(settings.workspace()), queue=JobQueue(home / "queue.sqlite3"),
                    budget=BudgetGuard(home / "budget.sqlite3", budget_cfg["per_job_usd"], budget_cfg["per_day_usd"]),
                    tools=ToolRegistry(home / "agent.sqlite3"))
        from mxstudio.agent.catalog import register_core_tools, register_guarded_tools  # noqa: PLC0415
        register_core_tools(state)
        register_guarded_tools(state)
        return state
