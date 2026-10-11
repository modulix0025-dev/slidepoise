"""«إصلاح» actions, one per ``fix_id``.

Rules:
* a fixer runs only when the operator clicks «إصلاح» for that red line;
* it returns ``{ok, ar, en}`` plus, when it cannot act alone, ``needs_consent`` (e.g. UAC)
  or ``instructions`` — it never claims success it did not measure;
* it never touches the operator's systems (OM / Console / Store): for those it only explains;
* downloads go through the pinned, resumable downloader; child processes through ``ctx.run``.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from mxstudio.firstrun import office
from mxstudio.update import payloads
from mxstudio.update.errors import UpdateError

from .context import DoctorContext

Fixer = Callable[..., dict[str, Any]]


def _instructions(ar: str, en: str) -> dict[str, Any]:
    return {"ok": False, "action": "instructions", "ar": ar, "en": en}


def fix_install_libreoffice(ctx: DoctorContext, *, consent: bool = False, progress=None, **_: Any) -> dict[str, Any]:
    return office.install_libreoffice(ctx, consent_elevation=consent, progress=progress)


def fix_create_workspace(ctx: DoctorContext, **_: Any) -> dict[str, Any]:
    ws = Path(ctx.workspace)
    try:
        for sub in ("", "stories", "art", "templates", "packs", "exports"):
            (ws / sub).mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {"ok": False, "ar": f"مش قادرين نعمل فولدر مساحة العمل: {ws}", "en": f"Cannot create {ws} ({exc.strerror})"}
    return {"ok": True, "ar": f"مساحة العمل اتعملت: {ws}", "en": f"Workspace created: {ws}"}


def _build_bundle(ctx: DoctorContext, name: str, progress=None) -> dict[str, Any]:
    """Font vault / shape packs: the Full installer's copy if present, else assembled from the pinned sources."""
    from mxstudio.update import assets  # noqa: PLC0415

    full_copy, home_copy = assets.bundle_dirs(name, app_dir=Path(ctx.app_dir), home=Path(ctx.home))
    if assets.tree_status(full_copy).get("ok"):
        return {"ok": True, "ar": "النسخة اللي جت مع البرنامج (Full) موجودة وسليمة.",
                "en": "The copy shipped with the Full installer is present and intact.", "folder": str(full_copy)}
    try:
        summary = assets.build_tree(name, home_copy, cache_dir=Path(ctx.home) / "downloads" / "assets",
                                    transport=ctx.transport, progress=progress,
                                    digits=ctx.settings.get("digits", "arabic_indic"))
    except UpdateError as err:
        return {"ok": False, "ar": err.ar, "en": err.en, "code": err.code}
    return {"ok": True, "ar": f"اتنزّل {summary['files']} ملف في {home_copy}.",
            "en": f"{summary['files']} files into {home_copy}.", "files": summary["files"], "folder": str(home_copy)}


def fix_fetch_fonts(ctx: DoctorContext, *, progress=None, **_: Any) -> dict[str, Any]:
    result = _build_bundle(ctx, "font_vault", progress)
    if result.get("ok") and ctx.is_windows:
        from mxstudio.update import assets  # noqa: PLC0415
        files = assets.font_files(assets.bundle_dirs("font_vault", app_dir=Path(ctx.app_dir), home=Path(ctx.home)))
        installed = assets.install_vault_fonts(files)
        result["installed"] = installed
        result["ar"] += f" واتسطّب {installed['installed']} خط لحسابك."
        result["en"] += f" {installed['installed']} fonts installed for this user."
    return result


def fix_fetch_shapes(ctx: DoctorContext, *, progress=None, **_: Any) -> dict[str, Any]:
    return _build_bundle(ctx, "shape_packs", progress)


AUTHENTICODE_PS = (
    "$s = Get-AuthenticodeSignature -LiteralPath $env:MXS_FILE; "
    "if ($s.Status -eq 'Valid' -and $s.SignerCertificate.Subject -like '*O=Microsoft Corporation*') { exit 0 } else { exit 3 }"
)


def fix_install_webview2(ctx: DoctorContext, *, progress=None, **_: Any) -> dict[str, Any]:
    if not ctx.is_windows:
        return _instructions("WebView2 للويندوز بس.", "WebView2 applies to Windows only.")
    manifest = payloads.load()
    item = payloads.entry(manifest, "webview2_bootstrapper")
    dest = Path(ctx.home) / "downloads" / item["file_name"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Evergreen bootstrapper: not sha-pinnable, so it is verified by Authenticode before it runs.
    from mxstudio.update.download import urllib_transport
    transport = ctx.transport or urllib_transport
    try:
        response = transport(item["url"], 0)
        with open(dest, "wb") as handle:
            for block in response.chunks:
                handle.write(block)
    except OSError as exc:
        return {"ok": False, "ar": "مش قادرين ننزّل WebView2 دلوقتي.", "en": f"Could not download WebView2 ({type(exc).__name__})."}
    check = ctx.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", AUTHENTICODE_PS],
                    env={"MXS_FILE": str(dest)}, timeout=60)
    if check.returncode != 0:
        dest.unlink(missing_ok=True)
        return {"ok": False, "ar": "ملف WebView2 اللي نزل مش موقّع من مايكروسوفت — اتمسح ومش هنشغّله.",
                "en": "The downloaded WebView2 bootstrapper is not Microsoft-signed; deleted, not run."}
    result = ctx.run([str(dest), "/silent", "/install"], timeout=900)
    return {"ok": result.returncode == 0,
            "ar": "WebView2 اتثبّت." if result.returncode == 0 else "تثبيت WebView2 ما نجحش.",
            "en": "WebView2 installed." if result.returncode == 0 else f"WebView2 install failed ({result.returncode})."}


def fix_open_providers(ctx: DoctorContext, **_: Any) -> dict[str, Any]:
    return {"ok": False, "action": "navigate", "target": "settings/providers",
            "ar": "افتح الإعدادات ← المزوّدين وراجع الرابط والمفتاح.", "en": "Open Settings → Providers and check URL and key."}


def fix_show_system_help(ctx: DoctorContext, **_: Any) -> dict[str, Any]:
    return _instructions(
        "الاستوديو مش بيشغّل أنظمتك بنفسه. شغّل النظام من الاختصار بتاعه المعتاد (OM على 8000، الكونسول على 6060، "
        "المتجر على 8200) وبعدين اضغط «افحص تاني».",
        "The Studio never starts your systems. Start the system from its usual launcher (OM 8000, Console 6060, "
        "Store 8200), then press “Check again”.")


def fix_arabic_path_help(ctx: DoctorContext, **_: Any) -> dict[str, Any]:
    return _instructions(
        "المسارات العربي بتبوظ مع عملية فرعية. اتأكد إن البرنامج متثبّت من المثبّت الرسمي (بيشغّل بايثون بـUTF-8)، "
        "وإن مفيش برنامج حماية بيمنع الكتابة في مساحة العمل. ابعت تقرير الدكتور لو المشكلة فضلت.",
        "Arabic paths break across a child process. Make sure the app came from the official installer (UTF-8 mode) "
        "and that no security tool blocks writes to the workspace. Send the Doctor report if it persists.")


def fix_reinstall_app(ctx: DoctorContext, **_: Any) -> dict[str, Any]:
    return _instructions("جزء من البرنامج ناقص أو بايظ. نزّل المثبّت تاني من الرابط الرسمي وشغّله (بياناتك مش هتتلمس).",
                         "Part of the program is missing or broken. Re-run the official installer (your data is kept).")


def fix_free_disk(ctx: DoctorContext, **_: Any) -> dict[str, Any]:
    return _instructions("فضّي مساحة على القرص (مثلًا امسح ملفات التصدير القديمة من مساحة العمل) وبعدين افحص تاني.",
                         "Free disk space (e.g. old exports in the workspace), then check again.")


FIXERS: dict[str, Fixer] = {
    "install_libreoffice": fix_install_libreoffice,
    "create_workspace": fix_create_workspace,
    "fetch_fonts": fix_fetch_fonts,
    "fetch_shapes": fix_fetch_shapes,
    "install_webview2": fix_install_webview2,
    "open_providers": fix_open_providers,
    "show_system_help": fix_show_system_help,
    "arabic_path_help": fix_arabic_path_help,
    "reinstall_app": fix_reinstall_app,
    "free_disk": fix_free_disk,
}


def run_fix(fix_id: str, ctx: DoctorContext | None = None, **kwargs: Any) -> dict[str, Any]:
    if fix_id not in FIXERS:
        return {"ok": False, "ar": f"مفيش إصلاح اسمه {fix_id}.", "en": f"No fixer named {fix_id}."}
    return FIXERS[fix_id](ctx or DoctorContext.default(), **kwargs)
