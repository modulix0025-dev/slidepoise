"""`python -m mxstudio evals generate|run|qualify` — JSON output, non-interactive.

qualify: runs the safety families + a task subset through the configured model; if the model
misses the thresholds the agent is restricted to suggestion-only mode (settings agent.mode).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from mxstudio.agent.evals.runner import run_scenario, summarise
from mxstudio.agent.evals.scenarios import all_scenarios, write

REPO = Path(__file__).resolve().parents[3]
QUALIFY_FAMILIES = {"prompt_injection", "customer_photo_ai_edit", "publish_without_approval", "licence_gate",
                    "palette_for_theme", "harmonies", "class_plan"}


def qualify(provider, settings, per_family: int = 2) -> dict:
    chosen, seen = [], {}
    for scenario in all_scenarios():
        if scenario["family"] in QUALIFY_FAMILIES and seen.get(scenario["family"], 0) < per_family:
            seen[scenario["family"]] = seen.get(scenario["family"], 0) + 1
            chosen.append(scenario)
    results = [run_scenario(s, "model", provider) for s in chosen]
    summary = summarise(results)
    mode = "full" if summary["safety_ok"] and summary["task_ok"] else "suggest_only"
    settings.update({"agent": {"mode": mode, "qualification": {"safety_rate": summary["safety_rate"],
                                                               "task_rate": summary["task_rate"]}}})
    return {"mode": mode, "summary": summary,
            "ar": "الموديل اتقبل للتشغيل الكامل." if mode == "full" else
            "الموديل ده ماعدّاش الاختبارات — المساعد هيقترح بس ومش هينفّذ."}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mxstudio evals")
    parser.add_argument("command", choices=["generate", "run", "qualify"])
    parser.add_argument("--out", type=Path, default=REPO / "evals" / "scenarios.json")
    parser.add_argument("--family", action="append")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    if args.command == "generate":
        print(json.dumps(write(args.out)))
        return 0
    if args.command == "run":
        scenarios = [s for s in all_scenarios() if not args.family or s["family"] in args.family]
        results = [run_scenario(s) for s in scenarios]
        summary = summarise(results)
        if args.report:
            args.report.write_text(json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=1))
        return 0 if summary["safety_ok"] and summary["task_ok"] else 1
    from mxstudio.config import Settings  # noqa: PLC0415
    from mxstudio.providers import build_text_provider  # noqa: PLC0415
    from mxstudio.secrets import SecretStore  # noqa: PLC0415
    settings = Settings()
    provider = build_text_provider(settings.load()["providers"]["text_vision"],
                                   SecretStore().get("provider.text_vision"))
    print(json.dumps(qualify(provider, settings), ensure_ascii=False, indent=1))
    return 0
