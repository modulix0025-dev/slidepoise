"""Doctor checks: each returns facts as ``{id, ok, level, ar, en, fix_id, details}``.

Rules:
* a check measures and reports; it never repairs (repairs are fixers, run only on «إصلاح»);
* every red line names a ``fix_id`` that exists in :data:`mxstudio.doctor.fixers.FIXERS`;
* ``level`` is ``ok`` | ``warn`` | ``red`` | ``skip`` (not applicable here); ``ok`` is False
  only for ``red``;
* child processes go through ``ctx.run`` (``mxstudio.proc.run_hidden``) with paths in env.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from mxstudio.firstrun import office

from .context import DoctorContext, program_dir

OPERATOR_SYSTEMS = (
    ("system_om", 8000, "OrderManagement (OM)", "نظام الطلبات OM"),
    ("system_console", 6060, "Execution Console", "الكونسول"),
    ("system_store", 8200, "ModuleX Store", "المتجر"),
)
DISK_RED_BYTES = 1 * 1024**3
DISK_WARN_BYTES = 5 * 1024**3
ARABIC_PROBE_TEXT = "تجربة مسار عربي — إياد ومحمد ٠١٢٣"


@dataclass
class CheckResult:
    id: str
    ok: bool
    ar: str
    en: str
    fix_id: str | None = None
    level: str = "ok"
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _ok(cid: str, ar: str, en: str, **details: Any) -> CheckResult:
    return CheckResult(cid, True, ar, en, None, "ok", details)


def _warn(cid: str, ar: str, en: str, fix_id: str | None = None, **details: Any) -> CheckResult:
    return CheckResult(cid, True, ar, en, fix_id, "warn", details)


def _red(cid: str, ar: str, en: str, fix_id: str, **details: Any) -> CheckResult:
    return CheckResult(cid, False, ar, en, fix_id, "red", details)


def _skip(cid: str, ar: str, en: str, **details: Any) -> CheckResult:
    return CheckResult(cid, True, ar, en, None, "skip", details)


# ---------------------------------------------------------------- checks
def check_python(ctx: DoctorContext) -> CheckResult:
    version = ".".join(map(str, sys.version_info[:3]))
    utf8 = bool(sys.flags.utf8_mode) or sys.getfilesystemencoding().lower() in ("utf-8", "utf8")
    if sys.version_info < (3, 10):
        return _red("python", f"بايثون {version} قديم — محتاجين 3.10 أو أحدث.", f"Python {version} is too old (need 3.10+).",
                    "reinstall_app", version=version)
    if not utf8:
        return _red("python", "بايثون مش شغّال بـUTF-8 — المسارات العربي ممكن تبوظ.",
                    "Python is not in UTF-8 mode; Arabic paths may break.", "reinstall_app", version=version)
    return _ok("python", f"بايثون {version} شغّال بـUTF-8.", f"Python {version} in UTF-8 mode.", version=version,
               frozen=ctx.frozen)


def node_paths(ctx: DoctorContext) -> tuple[str | None, Path | None]:
    env_node = os.environ.get("MXS_NODE")
    bundled = Path(ctx.app_dir) / "node" / ("node.exe" if ctx.is_windows else "node")
    node = env_node if env_node and Path(env_node).is_file() else (str(bundled) if bundled.is_file() else ctx.which("node"))
    modules = None
    for candidate in (os.environ.get("MXS_NODE_MODULES"), Path(ctx.app_dir) / "node" / "node_modules",
                      Path(ctx.app_dir) / "node_modules"):
        if candidate and (Path(candidate) / "pptxgenjs").is_dir():
            modules = Path(candidate)
            break
    return node, modules


NODE_PROBE = ("const p=require('path');const m=process.env.MXS_NODE_MODULES;"
              "const a=require(p.join(m,'pptxgenjs'));require(p.join(m,'jszip'));"
              "process.stdout.write(process.version+' '+(typeof a))")


def check_node(ctx: DoctorContext) -> CheckResult:
    node, modules = node_paths(ctx)
    if not node:
        return _red("node", "Node.js مش موجود — من غيره مش هنقدر نبني ملفات PowerPoint.",
                    "Node.js was not found; PowerPoint decks cannot be built.", "reinstall_app")
    if not modules:
        return _red("node", "مكتبات PptxGenJS/JSZip مش موجودة جنب Node.", "PptxGenJS/JSZip modules are missing.",
                    "reinstall_app", node=node)
    try:
        result = ctx.run([node, "-e", NODE_PROBE], env={"MXS_NODE_MODULES": str(modules)}, timeout=30)
    except (OSError, ValueError) as exc:
        return _red("node", "Node.js مش بيشتغل.", f"Node.js does not start ({type(exc).__name__}).", "reinstall_app")
    out = (result.stdout or b"").decode("utf-8", "replace").strip()
    if result.returncode != 0:
        return _red("node", "Node.js مش قادر يحمّل PptxGenJS/JSZip.", "Node.js cannot load PptxGenJS/JSZip.",
                    "reinstall_app", stderr=(result.stderr or b"").decode("utf-8", "replace")[-400:])
    return _ok("node", f"Node.js {out.split(' ')[0]} و PptxGenJS و JSZip شغّالين.",
               f"Node.js {out.split(' ')[0]} with PptxGenJS and JSZip works.", node=node, modules=str(modules))


def check_office(ctx: DoctorContext) -> CheckResult:
    engine = office.detect_engine(ctx)
    if engine and engine["engine"] == "powerpoint":
        return _ok("office", "PowerPoint موجود — هنستخدمه للتصدير.", "PowerPoint found; it is used for export.", **engine)
    if engine:
        return _ok("office", "LibreOffice موجود — محرّك التصدير المجاني جاهز.", "LibreOffice found; the free export engine is ready.",
                   **engine)
    return _red("office", "مفيش PowerPoint ولا LibreOffice — محتاجين محرّك تصدير.",
                "Neither PowerPoint nor LibreOffice is installed; an export engine is needed.", "install_libreoffice")


def check_pypdfium2(ctx: DoctorContext) -> CheckResult:
    try:
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument.new()
        page = doc.new_page(100, 100)
        image = page.render(scale=1).to_pil()
        size = image.size
        page.close()
        doc.close()
    except Exception as exc:
        return _red("pypdfium2", "pypdfium2 (عرض صفحات الـPDF) مش شغّال.", f"pypdfium2 does not work ({type(exc).__name__}).",
                    "reinstall_app")
    return _ok("pypdfium2", "pypdfium2 بيرسم صفحات PDF تمام.", "pypdfium2 renders PDF pages.",
               version=getattr(pdfium, "V_PYPDFIUM2", ""), rendered=list(size))


def font_dirs(ctx: DoctorContext) -> list[Path]:
    return [Path(ctx.app_dir) / "fonts", Path(ctx.app_dir) / "offline" / "fonts", Path(ctx.home) / "fonts",
            Path(ctx.workspace) / "fonts"]


def check_fonts(ctx: DoctorContext) -> CheckResult:
    files: list[Path] = []
    for folder in font_dirs(ctx):
        if folder.is_dir():
            files += [p for p in folder.rglob("*") if p.suffix.lower() in (".ttf", ".otf")]
    if not files:
        return _red("fonts", "خزنة الخطوط مش موجودة.", "The font vault is missing.", "fetch_fonts",
                    searched=[str(p) for p in font_dirs(ctx)])
    arabic = 0
    try:
        from fontTools.ttLib import TTFont
        for path in files[:400]:
            try:
                with TTFont(path, lazy=True, fontNumber=0) as font:
                    cmap = font.getBestCmap() or {}
                if 0x0627 in cmap and 0x0644 in cmap:
                    arabic += 1
            except Exception:
                continue
    except ImportError:
        arabic = -1
    if arabic == 0:
        return _red("fonts", f"لقينا {len(files)} خط بس ولا واحد فيهم بيدعم العربي.",
                    f"{len(files)} fonts found but none covers Arabic.", "fetch_fonts", count=len(files))
    return _ok("fonts", f"خزنة الخطوط فيها {len(files)} خط ({arabic} بيدعم العربي).",
               f"Font vault: {len(files)} fonts ({arabic} with Arabic).", count=len(files), arabic=arabic)


def check_shapes(ctx: DoctorContext) -> CheckResult:
    sets = []
    for folder in (Path(ctx.app_dir) / "offline" / "shapes", Path(ctx.home) / "shapes"):
        sets += [p.parent.name for p in folder.glob("iconify/*/icons.json")]
    if not sets:
        return _warn("shapes", "حزم الأشكال مش موجودة — البحث عن أشكال هيحتاج نت.",
                     "Shape packs are missing; shape search needs the internet.", "fetch_shapes")
    names = sorted(set(sets))
    return _ok("shapes", f"حزم الأشكال موجودة ({len(names)} مجموعة).", f"Shape packs: {len(names)} sets.", sets=names)


WEBVIEW2_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"


def check_webview2(ctx: DoctorContext) -> CheckResult:
    if not ctx.is_windows:
        return _skip("webview2", "WebView2 بيتفحص على ويندوز بس.", "WebView2 is checked on Windows only.")
    for hive, key in (("HKLM", rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_GUID}"),
                      ("HKLM", rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_GUID}"),
                      ("HKCU", rf"Software\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_GUID}")):
        version = ctx.reg_read(hive, key, "pv")
        if version and version != "0.0.0.0":
            return _ok("webview2", f"WebView2 موجود (نسخة {version}).", f"WebView2 Runtime {version} is installed.",
                       version=version)
    return _red("webview2", "Microsoft Edge WebView2 مش موجود — نافذة الاستوديو محتاجاه.",
                "Microsoft Edge WebView2 Runtime is missing; the Studio window needs it.", "install_webview2")


def check_providers(ctx: DoctorContext) -> CheckResult:
    providers = ctx.settings.get("providers") or {}
    enabled = {name: cfg for name, cfg in providers.items() if isinstance(cfg, dict) and cfg.get("enabled")}
    if not enabled:
        return _warn("providers", "مفيش مزوّد ذكاء اصطناعي مفعّل — الاستوديو شغّال من غيره، والتوليد هيبقى متاح لما تضيف واحد.",
                     "No AI provider is enabled; the Studio works without one.", "open_providers")
    failing = {}
    for name, cfg in enabled.items():
        base = str(cfg.get("base_url") or "").rstrip("/")
        if not base:
            failing[name] = "no base_url"
            continue
        probe = f"{base}/system_stats" if cfg.get("kind") == "comfyui" else f"{base}/models"
        status = ctx.http_get(probe, ctx.timeout)
        if status == 0 or status >= 500:
            failing[name] = f"HTTP {status or 'unreachable'}"
    if failing:
        return _red("providers", "في مزوّد مفعّل ومش بيرد: " + "، ".join(failing),
                    "Enabled provider(s) not answering: " + ", ".join(f"{k} ({v})" for k, v in failing.items()),
                    "open_providers", failing=failing)
    return _ok("providers", "المزوّدين المفعّلين بيردّوا.", "Enabled providers answer.", providers=sorted(enabled))


def _system_check(cid: str, port: int, en_name: str, ar_name: str) -> Callable[[DoctorContext], CheckResult]:
    def check(ctx: DoctorContext) -> CheckResult:
        if ctx.connect("127.0.0.1", port, ctx.timeout):
            return _ok(cid, f"{ar_name} شغّال على البورت {port}.", f"{en_name} answers on port {port}.", port=port)
        return _red(cid, f"{ar_name} مش بيرد على البورت {port} — الاستوديو مش بيشغّله بنفسه.",
                    f"{en_name} does not answer on port {port}; the Studio never starts it itself.",
                    "show_system_help", port=port)
    check.__name__ = f"check_{cid}"
    return check


def check_disk(ctx: DoctorContext) -> CheckResult:
    free = ctx.disk_free(Path(ctx.workspace))
    gb = round(free / 1024**3, 1)
    if free < DISK_RED_BYTES:
        return _red("disk", f"المساحة الفاضية {gb} جيجا بس — قليلة جدًا.", f"Only {gb} GB free.", "free_disk", free_bytes=free)
    if free < DISK_WARN_BYTES:
        return _warn("disk", f"المساحة الفاضية {gb} جيجا — يُفضّل 5 أو أكتر.", f"{gb} GB free; 5 GB+ recommended.",
                     "free_disk", free_bytes=free)
    return _ok("disk", f"المساحة الفاضية {gb} جيجا.", f"{gb} GB free.", free_bytes=free)


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def check_workspace(ctx: DoctorContext) -> CheckResult:
    ws = Path(ctx.workspace)
    if ctx.frozen and _inside(ws, Path(ctx.app_dir)):
        return _red("workspace", "مساحة العمل جوه فولدر البرنامج — لازم تبقى برّاه.",
                    "The workspace is inside the program folder; it must be outside.", "create_workspace", path=str(ws))
    if not ws.is_dir():
        return _red("workspace", f"مساحة العمل مش موجودة: {ws}", f"Workspace folder does not exist: {ws}",
                    "create_workspace", path=str(ws))
    probe = ws / f".mxs-write-{secrets.token_hex(4)}"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError:
        return _red("workspace", "مش قادرين نكتب في مساحة العمل.", "The workspace is not writable.", "create_workspace",
                    path=str(ws))
    return _ok("workspace", f"مساحة العمل جاهزة: {ws}", f"Workspace ready: {ws}", path=str(ws))


def check_arabic_path(ctx: DoctorContext) -> CheckResult:
    """Write → read → child process (path via env) → Node (path via env) round-trip on an Arabic path."""
    base = Path(ctx.workspace) if Path(ctx.workspace).is_dir() else Path(ctx.home)
    folder = base / ".doctor" / f"مسار_عربي_{secrets.token_hex(3)}"
    target = folder / "ملف تجربة.txt"
    steps: dict[str, Any] = {}
    try:
        folder.mkdir(parents=True, exist_ok=True)
        target.write_text(ARABIC_PROBE_TEXT, encoding="utf-8")
        steps["write_read"] = target.read_text(encoding="utf-8") == ARABIC_PROBE_TEXT
        expected = hashlib.sha256(ARABIC_PROBE_TEXT.encode("utf-8")).hexdigest()
        child_env = {"MXS_DOCTOR_RT_PATH": str(target)}
        if not ctx.frozen:  # source checkout: let `-m mxstudio.doctor` import from the repo
            child_env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(program_dir()), os.environ.get("PYTHONPATH")]))
        result = ctx.run(ctx.self_command("--child-roundtrip"), env=child_env, timeout=60)
        echo = target.with_name("رد الابن.txt")
        steps["child_python"] = result.returncode == 0 and echo.is_file() and \
            echo.read_text(encoding="utf-8").strip() == expected
        node, _ = node_paths(ctx)
        if node:
            script = ("const fs=require('fs'),p=require('path');const f=process.env.MXS_DOCTOR_RT_PATH;"
                      "const t=fs.readFileSync(f,'utf8');fs.writeFileSync(p.join(p.dirname(f),'رد نود.txt'),t,'utf8');")
            nres = ctx.run([node, "-e", script], env={"MXS_DOCTOR_RT_PATH": str(target)}, timeout=30)
            nout = target.with_name("رد نود.txt")
            steps["child_node"] = nres.returncode == 0 and nout.is_file() and \
                nout.read_text(encoding="utf-8") == ARABIC_PROBE_TEXT
    except (OSError, ValueError) as exc:
        steps["error"] = type(exc).__name__
    finally:
        for leftover in sorted(folder.glob("*"), reverse=True) if folder.is_dir() else []:
            leftover.unlink(missing_ok=True)
        if folder.is_dir():
            folder.rmdir()
    passed = [k for k, v in steps.items() if v is True]
    failed = [k for k, v in steps.items() if v is not True]
    if failed:
        return _red("arabic_path", "المسارات العربي بتبوظ في: " + "، ".join(failed),
                    "Arabic path round-trip failed at: " + ", ".join(failed), "arabic_path_help", steps=steps,
                    folder=str(folder))
    return _ok("arabic_path", "المسارات العربي سليمة (كتابة وقراءة وعملية فرعية" + (" و Node" if "child_node" in passed else "") + ").",
               "Arabic path round-trip OK (" + ", ".join(passed) + ").", steps=steps)


def child_roundtrip() -> int:
    """Run inside the child: read the Arabic path from env, write its sha256 next to it."""
    target = Path(os.environ["MXS_DOCTOR_RT_PATH"])
    digest = hashlib.sha256(target.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
    target.with_name("رد الابن.txt").write_text(digest, encoding="utf-8")
    return 0


CHECKS: list[Callable[[DoctorContext], CheckResult]] = [
    check_python, check_node, check_office, check_pypdfium2, check_fonts, check_shapes, check_webview2, check_providers,
    *[_system_check(*spec) for spec in OPERATOR_SYSTEMS],
    check_workspace, check_disk, check_arabic_path,
]


def _connection():
    from mxstudio.doctor import connection  # noqa: PLC0415 - imports this module's helpers
    return connection


def check_ids() -> list[str]:
    return ["python", "node", "office", "pypdfium2", "fonts", "shapes", "webview2", "providers",
            *[spec[0] for spec in OPERATOR_SYSTEMS], "workspace", "disk", "arabic_path", *_connection().IDS]


def all_checks() -> list[Callable[[DoctorContext], CheckResult]]:
    return [*CHECKS, *_connection().CHECKS]


def run_all(ctx: DoctorContext | None = None, only: list[str] | None = None) -> list[dict[str, Any]]:
    ctx = ctx or DoctorContext.default()
    results = []
    for check, cid in zip(all_checks(), check_ids()):
        if only and cid not in only:
            continue
        try:
            results.append(check(ctx).to_dict())
        except Exception as exc:
            results.append(CheckResult(cid, False, "الفحص ده وقع بخطأ غير متوقع.", f"Check crashed: {type(exc).__name__}",
                                       "reinstall_app", "red", {"error": repr(exc)[:300]}).to_dict())
    return results


def summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    red = [r["id"] for r in results if r["level"] == "red"]
    return {"ok": not red, "red": red, "warn": [r["id"] for r in results if r["level"] == "warn"],
            "count": len(results)}
