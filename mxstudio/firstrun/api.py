"""First-run wizard routes (workspace → providers → discovery → doctor); keys go to the DPAPI store only."""
from __future__ import annotations

from fastapi import Request


class _SecretAdapter:
    def __init__(self, store):
        self.store = store

    def put(self, name: str, secret: str) -> str:
        return self.store.set(name, secret)["fingerprint"]


def register(app, state) -> None:
    from mxstudio.firstrun.wizard import Wizard, WizardError  # noqa: PLC0415

    def wizard() -> Wizard:
        return Wizard(state.settings, secret_store=_SecretAdapter(state.secrets))

    @app.get("/api/firstrun/state")
    def firstrun_state():
        return wizard().state()

    @app.post("/api/firstrun/{action}")
    async def firstrun_action(action: str, request: Request):
        body = await request.json() if (await request.body()) else {}
        w = wizard()
        try:
            if action == "submit":
                return w.submit(str(body.get("step")), body.get("payload") or {})
            if action == "skip":
                return w.skip(str(body.get("step")))
            if action == "back":
                return w.back()
            if action == "reset":
                return w.reset()
        except WizardError as exc:
            return {"ok": False, **exc.to_dict()}
        return {"ok": False, "error": f"unknown action {action}"}
