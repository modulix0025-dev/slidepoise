"""Doctor lines for «Claude Desktop always finds the Studio» and «PowerPoint sees the fonts».

install_location · mcp_config · mcp_handshake · claude_restart_pending · claude_log_state · fonts_registered ·
powerpoint_restart_pending · single_instance — each one measures, never repairs; every red line names a fix_id
that exists in mxstudio.doctor.fixers.FIXERS.
"""
from __future__ import annotations

import json
from pathlib import Path

from mxstudio.doctor.checks import CheckResult, _ok, _red, _skip, _warn
from mxstudio.doctor.context import DoctorContext

APP_EXE = "ModuleX Magazine Studio.exe"


def _system(ctx: DoctorContext):
    from mxstudio.winsys import SYSTEM  # noqa: PLC0415
    return getattr(ctx, "system", None) or SYSTEM


def check_install_location(ctx: DoctorContext) -> CheckResult:
    from mxstudio.winsys import default_install_dir, sync_folder_reason  # noqa: PLC0415
    if not ctx.frozen:
        return _skip("install_location", "مكان التسطيب بيتفحص في النسخة المتسطّبة بس.",
                     "The install location is checked in the installed app only.")
    system = _system(ctx)
    reason = sync_folder_reason(Path(ctx.app_dir), system)
    if reason:
        return _red("install_location",
                    f"البرنامج متسطّب جوه فولدر بيتزامن ({reason['kind']}): {ctx.app_dir} — الملفات ممكن تبقى «أونلاين بس» "
                    "فـClaude Desktop يعمل timeout. سطّبه تاني في المكان الافتراضي.",
                    f"The program sits in a syncing folder ({reason['kind']}); reinstall it in the default folder.",
                    "move_install", path=str(ctx.app_dir), reason=reason, default=str(default_install_dir(system)))
    return _ok("install_location", f"مكان التسطيب سليم: {ctx.app_dir}", f"Install location OK: {ctx.app_dir}",
               path=str(ctx.app_dir))


def check_mcp_config(ctx: DoctorContext) -> CheckResult:
    from mxstudio.mcp import clients  # noqa: PLC0415
    entry = clients.expected_entry(Path(ctx.home), Path(ctx.app_dir), frozen=ctx.frozen, platform=ctx.platform)
    candidates = getattr(ctx, "claude_configs", None)
    configs = [clients._one_status(p, entry) for p in clients.live_configs(candidates)]  # noqa: SLF001
    if not any(c["claude_desktop_found"] for c in configs):
        return _warn("mcp_config", "Claude Desktop مش متسطّب على الجهاز ده (أو عمره ما اتفتح).",
                     "Claude Desktop is not installed here (or was never opened).", "mcp_heal", entry=entry)
    invalid = [c for c in configs if c["problem"]]
    if invalid:
        return _red("mcp_config", "ملف إعدادات Claude Desktop بايظ ومش هنلمسه: " + invalid[0]["problem"]["ar"],
                    "A Claude Desktop config is not valid JSON; it is left untouched.", "mcp_config_help",
                    configs=configs)
    launcher_ok = not Path(entry["command"]).is_absolute() or Path(entry["command"]).is_file()
    wrong = [c for c in configs if not c["connected"]]
    if wrong or not launcher_ok:
        why = "المشغّل الثابت مش موجود" if not launcher_ok else \
            "، ".join(f"{Path(c['path']).parent.parent.name}: {c['reason']}" for c in wrong)
        return _red("mcp_config", f"توصيل Claude Desktop مش سليم ({why}).",
                    "The Claude Desktop entry is missing, broken or not on the fixed launcher.", "mcp_heal",
                    configs=configs, entry=entry, launcher_present=launcher_ok)
    return _ok("mcp_config", f"Claude Desktop متوصّل بالمشغّل الثابت في {len(configs)} ملف إعدادات.",
               f"Claude Desktop entry points at the fixed launcher in {len(configs)} config(s).",
               configs=[c["path"] for c in configs], entry=entry)


def check_mcp_handshake(ctx: DoctorContext) -> CheckResult:
    from mxstudio.mcp import clients  # noqa: PLC0415
    entry = clients.expected_entry(Path(ctx.home), Path(ctx.app_dir), frozen=ctx.frozen, platform=ctx.platform)
    test = (getattr(ctx, "mcp_self_test", None) or clients.self_test)(entry)
    if not test.get("ok"):
        return _red("mcp_handshake", "سيرفر الاستوديو مابيردّش زي ما Claude Desktop مستني: " + str(test.get("ar", "")),
                    "The Studio MCP server does not answer the handshake.", "mcp_heal", test=test)
    if test.get("seconds", 0) > clients.HANDSHAKE_BUDGET_S:
        return _warn("mcp_handshake", f"السيرفر بيرد بس ببطء ({test['seconds']} ث، المطلوب أقل من 2).",
                     f"The handshake works but took {test['seconds']} s (budget 2 s).", "mcp_heal", test=test)
    return _ok("mcp_handshake", f"الـhandshake تمام في {test.get('seconds')} ث ({test.get('tools')} أداة).",
               f"Handshake OK in {test.get('seconds')} s ({test.get('tools')} tools).", test=test)


def check_claude_restart_pending(ctx: DoctorContext) -> CheckResult:
    from mxstudio.mcp import clients  # noqa: PLC0415
    state = clients.restart_pending(Path(ctx.home), _system(ctx))
    ar, en = state.pop("ar"), state.pop("en")
    if state["pending"]:
        return _red("claude_restart_pending", ar, en, "restart_claude", **state)
    if not state["running"]:
        return _ok("claude_restart_pending", "Claude Desktop مقفول — أول ما يتفتح هيقرا الإعدادات الجديدة.",
                   "Claude Desktop is closed; it reads the config when it starts.", **state)
    return _ok("claude_restart_pending", "Claude Desktop شغّال بعد آخر تعديل في الإعدادات.",
               "Claude Desktop started after the last config change.", **state)


def check_claude_log_state(ctx: DoctorContext) -> CheckResult:
    from mxstudio.mcp import clients  # noqa: PLC0415
    paths = getattr(ctx, "claude_logs", None)
    state = clients.claude_log_state(paths)
    if state["state"] == "connected":
        return _ok("claude_log_state", "لوج Claude Desktop: الاستوديو متوصّل ✓", "Claude Desktop log: connected.", **state)
    if state["state"] == "error":
        return _red("claude_log_state", "لوج Claude Desktop فيه خطأ مع الاستوديو: " + state["line"][:200],
                    "Claude Desktop logged an error for the Studio.", "mcp_heal", **state)
    return _warn("claude_log_state", "Claude Desktop لسه ماحاولش يشغّل الاستوديو (أعد تشغيله).",
                 "Claude Desktop has not started the Studio yet (restart it).", "restart_claude", **state)


def _theme_families() -> set[str]:
    from mxstudio.update.assets import _catalog_dir  # noqa: PLC0415
    themes = json.loads((_catalog_dir() / "fonts" / "type_themes.json").read_text(encoding="utf-8"))["themes"]
    return {value for theme in themes for key, value in theme.items()
            if key.startswith(("ar_", "en_")) and isinstance(value, str)}


def _vault_family_files(ctx: DoctorContext) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for folder in (Path(ctx.app_dir) / "offline" / "fonts", Path(ctx.home) / "fonts"):
        manifest = folder / "MANIFEST.json"
        if not manifest.is_file():
            continue
        for item in json.loads(manifest.read_text(encoding="utf-8")).get("files", []):
            if str(item.get("path", "")).lower().endswith((".ttf", ".otf")) and item.get("family"):
                out.setdefault(item["family"], set()).add(Path(item["path"]).name.casefold())
    return out


def check_fonts_registered(ctx: DoctorContext) -> CheckResult:
    """Every theme font must be REGISTERED (HKCU/HKLM Fonts key), not just copied: copied-only fonts made PowerPoint
    show Microsoft JhengHei for Tajawal and Calibri for Nunito."""
    if not ctx.is_windows:
        return _skip("fonts_registered", "تسجيل الخطوط بيتفحص على ويندوز بس.", "Font registration is checked on Windows.")
    backend = getattr(ctx, "font_backend", None)
    if backend is None:
        from mxstudio.fonts.install import WindowsBackend  # noqa: PLC0415
        backend = WindowsBackend()
    values = {**backend.registry_values("machine"), **backend.registry_values("user")}
    names = {name.casefold() for name in values}
    files = {Path(str(data)).name.casefold(): data for data in values.values()}
    by_family = _vault_family_files(ctx)
    missing = []
    for family in sorted(_theme_families()):
        wanted = by_family.get(family, set())
        by_file = any(f in files and (not Path(str(files[f])).is_absolute() or Path(str(files[f])).is_file())
                      for f in wanted)
        by_name = any(n.startswith(family.casefold()) for n in names)
        if not (by_file or by_name):
            missing.append(family)
    if missing:
        return _red("fonts_registered", f"{len(missing)} خط من خطوط الثيمات مش متسجّل في ويندوز: " + "، ".join(missing[:8]),
                    f"{len(missing)} theme fonts are not registered: " + ", ".join(missing[:8]), "fetch_fonts",
                    missing=missing)
    return _ok("fonts_registered", "كل خطوط الثيمات متسجّلة في ويندوز.", "Every theme font is registered.",
               families=len(_theme_families()))


def _fonts_installed_at(ctx: DoctorContext) -> float | None:
    log = Path(ctx.home) / "logs" / "fonts-install.json"
    try:
        data = json.loads(log.read_text(encoding="utf-8"))
        return float(data.get("installed_at") or log.stat().st_mtime)
    except (OSError, ValueError):
        return None


def check_powerpoint_restart_pending(ctx: DoctorContext) -> CheckResult:
    if not ctx.is_windows:
        return _skip("powerpoint_restart_pending", "على ويندوز بس.", "Windows only.")
    installed = _fonts_installed_at(ctx)
    running = _system(ctx).processes("POWERPNT.EXE")
    stale = [p for p in running if installed and p.started and p.started < installed]
    if stale:
        return _warn("powerpoint_restart_pending", "PowerPoint مفتوح من قبل تسطيب الخطوط — اقفله وافتحه علشان يشوفها.",
                     "PowerPoint was open before the fonts were installed; restart it.", "restart_powerpoint",
                     fonts_installed_at=installed)
    return _ok("powerpoint_restart_pending", "PowerPoint شايف الخطوط (أو مقفول).", "PowerPoint sees the fonts (or is closed).",
               fonts_installed_at=installed, running=len(running))


def check_single_instance(ctx: DoctorContext) -> CheckResult:
    from mxstudio.app.runner import read_lock  # noqa: PLC0415
    from mxstudio.shell.single import pid_alive  # noqa: PLC0415
    lock = read_lock(Path(ctx.home))
    stale = bool(lock) and not pid_alive(int(lock.get("pid") or 0))
    windows = _system(ctx).processes(APP_EXE) if ctx.is_windows else []
    if stale:
        return _red("single_instance", "ملف server.lock قديم وبيشاور على برنامج مقفول.", "server.lock names a dead process.",
                    "single_instance", lock=lock)
    if len(windows) > 1:
        return _red("single_instance", f"فيه {len(windows)} نسخ من الاستوديو مفتوحين.", f"{len(windows)} Studio windows are open.",
                    "single_instance", pids=[p.pid for p in windows])
    return _ok("single_instance", "نسخة واحدة بس من الاستوديو.", "One Studio instance.", windows=len(windows))


CHECKS = [check_install_location, check_mcp_config, check_mcp_handshake, check_claude_restart_pending,
          check_claude_log_state, check_fonts_registered, check_powerpoint_restart_pending, check_single_instance]
IDS = ["install_location", "mcp_config", "mcp_handshake", "claude_restart_pending", "claude_log_state",
       "fonts_registered", "powerpoint_restart_pending", "single_instance"]
