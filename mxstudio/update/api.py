"""Update routes: check/download/stage run in a background thread; installing needs the human's consent."""
from __future__ import annotations

import json
import threading

from fastapi import HTTPException, Request


def register(app, state) -> None:
    from mxstudio.update.errors import UpdateError  # noqa: PLC0415
    from mxstudio.update.state import UpdateManager  # noqa: PLC0415

    def manager() -> UpdateManager:
        return UpdateManager(state.home)

    def background(work):
        def run():
            try:
                work()
            except UpdateError:
                pass  # the state machine records the failure in its state file
        threading.Thread(target=run, daemon=True).start()

    @app.get("/api/update/state")
    def update_state():
        progress = state.home / "update" / "progress.json"
        return {"state": manager().state(), "progress": json.loads(progress.read_text("utf-8"))
                if progress.is_file() else None}

    @app.post("/api/update/{action}")
    async def update_action(action: str, request: Request):
        body = await request.json() if (await request.body()) else {}
        m = manager()
        if action == "check":
            background(lambda: (m.check(), m.download(), m.verify() and m.stage()))
            return {"started": True}
        if action == "consent":
            return m.consent(bool(body.get("yes", True)))
        if action == "rollback":
            target = m.rollback_target()
            if not target:
                raise HTTPException(409, "no previous version to roll back to")
            if not body.get("confirm"):
                return {"rollback_target": target, "needs_confirm": True,
                        "ar": "أكّد الرجوع للنسخة اللي قبل كده."}
            return {"rollback_target": target, "started": m.rollback()}
        raise HTTPException(404, f"unknown action {action}")
