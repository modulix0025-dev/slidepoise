"""«ربط أنظمتي» — the Kit inside the Studio: agent tools + a summary route for the UI.

Rules:
* read-only steps (discover, verify, probe, plan, status) are ordinary tools;
* ``kit.apply`` and ``kit.revert`` write into the operator's trees, so they are *irreversible*
  tools: the registry demands a human confirmation token minted by the UI, and ``kit.apply``
  also needs the per-patch confirm code from ``kit.plan`` (bound to the anchors and file bytes);
* long steps (proofs, report) run in the background worker (``mxstudio/kit/jobs.py``).
"""
from __future__ import annotations

from mxstudio.agent.tools import Tool


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or [], "additionalProperties": False}


ROOT = {"root": {"type": "string"}}


def register(app, state) -> None:
    from . import apply as kit_apply
    from .anchors import verify
    from .discover import discover
    from .patches import PATCHES
    from .probe import probe

    patch_ids = sorted(PATCHES)
    tools = [
        Tool("kit.discover", "دوّر على أنظمتي تحت مجلد المشروع.", "Discover the operator's systems.",
             _obj(ROOT), lambda a: discover(a.get("root")), tags=["kit"]),
        Tool("kit.verify", "اتأكد من نقاط الربط (anchors) في الكود.", "Verify anchors.",
             _obj(ROOT), lambda a: verify(discover(a.get("root"))), tags=["kit"]),
        Tool("kit.probe", "افحص القوالب والخطوط والحسابات (قراءة بس).", "Read-only estate probe.",
             _obj({**ROOT, "network": {"type": "boolean"}}),
             lambda a: probe(discover(a.get("root")), network=a.get("network", True)), tags=["kit"]),
        Tool("kit.plan", "اعرض الباتشات الجاهزة والممنوعة مع كود التأكيد.", "Plan patches (with confirm codes).",
             _obj({**ROOT, "patch": {"enum": patch_ids}}),
             lambda a: kit_apply.plan(a.get("root"), patch_ids=[a["patch"]] if a.get("patch") else None),
             tags=["kit"]),
        Tool("kit.status", "حالة الباتشات المتركّبة.", "Applied patch status.",
             _obj(ROOT), lambda a: kit_apply.status(a.get("root")), tags=["kit"]),
        Tool("kit.apply", "ركّب باتش واحد (محتاج موافقتك).", "Apply one patch (needs your confirmation).",
             _obj({**ROOT, "patch": {"enum": patch_ids}, "confirm_code": {"type": "string", "pattern": "^[0-9a-f]{10}$"},
                   "run_tests": {"type": "boolean"}}, ["patch", "confirm_code"]),
             lambda a: kit_apply.apply_patch(a["patch"], root=a.get("root"), confirm=a["confirm_code"],
                                             run_tests=a.get("run_tests", True)),
             irreversible=True, tags=["kit"]),
        Tool("kit.revert", "رجّع باتش زي ما كان بالظبط (محتاج موافقتك).", "Revert one patch byte-identically.",
             _obj({**ROOT, "patch": {"enum": patch_ids}, "cascade": {"type": "boolean"}}, ["patch"]),
             lambda a: kit_apply.revert_patch(a["patch"], root=a.get("root"), cascade=a.get("cascade", False)),
             irreversible=True, tags=["kit"]),
        Tool("kit.proofs", "شغّل إثباتات الجهاز (PowerPoint) في الخلفية.", "Queue the on-device proofs.",
             _obj({**ROOT, "engines": {"type": "string"}, "limit": {"type": "integer", "minimum": 1},
                   "story": {"type": "string"}}),
             lambda a: {"job": state.queue.enqueue("kit.proofs", dict(a))}, tags=["kit"]),
        Tool("kit.report", "اعمل تقرير الجهاز (من غير أسرار ولا بيانات عملاء).", "Queue the device report.",
             _obj(ROOT), lambda a: {"job": state.queue.enqueue("kit.report", dict(a))}, tags=["kit"]),
    ]
    for tool in tools:
        state.tools.register(tool)

    @app.get("/api/kit/summary")
    def summary():
        rows = kit_apply.status(None)["patches"]
        return {"facts": {"patches": rows, "rule": "a patch applies only after its anchors verify and you confirm it; "
                                                   "every flag is OFF until you turn it on"},
                "actions": [{"label_ar": "دوّر على أنظمتي", "label_en": "Discover my systems", "tool": "kit.discover",
                             "args": {}},
                            {"label_ar": "اعرض خطة الربط", "label_en": "Show the patch plan", "tool": "kit.plan",
                             "args": {}}]}
