"""«اختبر الموديل» runs by itself as soon as a model key is saved, and the reason for «اقتراح بس» is always shown.

The assistant stays in suggestion-only mode until the configured model passes the safety/task qualification
(mxstudio.agent.evals.cli.qualify). Before, that test only ran when the operator found and pressed a button, so a
saved key silently left the assistant suggesting forever. Now saving the key starts the check in the background and
`explain()` says, in Arabic and English, exactly where things stand.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path

log = logging.getLogger("mxstudio.agent.model_check")
FILE = "model_check.json"
_running: set[str] = set()
_lock = threading.Lock()


def _path(home: Path) -> Path:
    return Path(home) / FILE


def read(home: Path) -> dict:
    try:
        return json.loads(_path(home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write(home: Path, data: dict) -> None:
    path = _path(home)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def run_check(state, qualify=None, build=None) -> dict:
    from mxstudio.providers import ProviderError, build_text_provider  # noqa: PLC0415
    if qualify is None:
        from mxstudio.agent.evals.cli import qualify  # noqa: PLC0415
    build = build or build_text_provider
    started = time.time()
    _write(state.home, {"status": "running", "started": started})
    try:
        provider = build(state.settings.load()["providers"]["text_vision"], state.secrets.get("provider.text_vision"))
    except ProviderError as exc:
        result = {"status": "no_model", "detail": str(exc)[:300]}
    else:
        try:
            outcome = qualify(provider, state.settings)
            result = {"status": "done", "mode": outcome["mode"], "summary": outcome.get("summary", {}),
                      "ar": outcome.get("ar", "")}
        except Exception as exc:  # noqa: BLE001 - e.g. a wrong key: the reason is shown, not hidden
            log.warning("model check failed: %s", exc)
            result = {"status": "error", "detail": f"{type(exc).__name__}: {str(exc)[:300]}"}
    result.update(started=started, finished=time.time())
    _write(state.home, result)
    return result


def start_check(state, **kwargs) -> bool:
    key = str(state.home)
    with _lock:
        if key in _running:
            return False
        _running.add(key)

    def work():
        try:
            run_check(state, **kwargs)
        finally:
            with _lock:
                _running.discard(key)

    threading.Thread(target=work, name="model-check", daemon=True).start()
    return True


def explain(state) -> dict:
    """Why the assistant is (or is not) in full mode, in words."""
    settings = state.settings.load()
    mode = settings.get("agent", {}).get("mode", "suggest_only")
    tv = settings["providers"]["text_vision"]
    check = read(state.home)
    if not tv.get("enabled"):
        return {"mode": mode, "state": "no_model",
                "ar": "مفيش موديل متظبط في الاستوديو — اكتب طلبك هنا وClaude Desktop ينفّذه («نفّذ طلبات الاستوديو»).",
                "en": "No model is configured in the Studio — prepare the request here and run it from Claude Desktop."}
    if mode == "full":
        return {"mode": mode, "state": "qualified", "ar": "الموديل اتقبل — المساعد بينفّذ.", "en": "Model qualified."}
    status = check.get("status")
    if status == "running":
        return {"mode": mode, "state": "checking", "ar": "بنختبر الموديل دلوقتي… (دقيقة أو اتنين)",
                "en": "Checking the model now…"}
    if status == "error":
        return {"mode": mode, "state": "error", "detail": check.get("detail"),
                "ar": "اختبار الموديل ما اشتغلش — غالبًا المفتاح غلط أو مفيش نت. التفاصيل: " + str(check.get("detail", ""))[:160],
                "en": "The model check failed: " + str(check.get("detail", ""))[:160]}
    if status == "no_model":
        return {"mode": mode, "state": "no_key", "ar": "الموديل متظبط بس المفتاح ناقص — حطه في «الإعدادات».",
                "en": "The model is configured but its key is missing."}
    if status == "done":
        s = check.get("summary", {})
        return {"mode": mode, "state": "failed_qualification", "summary": s,
                "ar": f"الموديل ماعدّاش اختبار الأمان (أمان {s.get('safety_rate')}، مهام {s.get('task_rate')}) — "
                      "علشان كده المساعد بيقترح بس.",
                "en": f"The model did not pass (safety {s.get('safety_rate')}, tasks {s.get('task_rate')})."}
    return {"mode": mode, "state": "not_checked", "ar": "الموديل لسه مااتختبرش — دوس «اختبر الموديل».",
            "en": "The model has not been checked yet."}
