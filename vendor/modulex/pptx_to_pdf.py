# -*- coding: utf-8 -*-
"""pptx_to_pdf.py — ★ P21 2026-08-25: THE MAGAZINE PDF IS THE DECK, EXPORTED.

═══════════════════════════════════════════════════════════════════════════════
WHAT WAS WRONG  (measured on order B7F49373, 2026-08-25)
═══════════════════════════════════════════════════════════════════════════════
The file the store hands the customer — «فتح الـPDF» / «تحميل الـPDF» —
was `order_{oid}_final.pdf`, and the console built it by COPYING custody's
`magazine.pdf`. That file is what `services/magazine_assembly` makes: Pillow
binding the rendered page IMAGES into a PDF. Measured on the real delivered
file:

    order_83178d43-…_final.pdf   13 pages   /Font → 0   13 × DCTDecode
    اياد - الصدق مع الأرنب (AR) [A5] — ModuleX.pptx   16 slides, full Arabic text

So the customer received a stack of pictures with ZERO text, three pages short
of their own magazine, while the real product — the injected A5 deck, with the
story written on every page — sat in the same folder untouched. The two
artefacts were never the same thing and nothing ever made the PDF from the deck.

═══════════════════════════════════════════════════════════════════════════════
WHAT THIS DOES
═══════════════════════════════════════════════════════════════════════════════
One job: turn a .pptx into a .pdf, and prove the result carries text.

    injected «— ModuleX.pptx»  ──►  convert()  ──►  order_{oid}_final.pdf
                                        │
                                        ├─ PowerPoint (COM, out-of-process)
                                        └─ LibreOffice (soffice --headless)

  1. POWERPOINT FIRST, BY DEFAULT. The deck is Arabic, right-to-left, with
     decorated banner shapes and the fonts the template was designed in.
     PowerPoint renders it EXACTLY as the operator sees it on screen; that is
     the whole reason it is first. LibreOffice is the fallback for a machine
     with no Office, and it is honest about substituting fonts.
     Order is operator-controlled: MODULEX_PPTX_PDF_ENGINES=soffice,powerpoint

  2. COM NEVER RUNS INSIDE THE CONSOLE. PowerPoint is driven from a short-lived
     PowerShell child process. The console is a frozen PyInstaller app, so
     `sys.executable` is the console itself and a Python subprocess is not
     available to it; PowerShell always is, needs no package in any venv, and —
     the point that matters — a PowerPoint that hangs on a modal dialog kills a
     child process on a timeout instead of wedging the server's event loop.

  3. THE OUTPUT IS PROVEN, NOT ASSUMED. `pdf_stats` reads the produced bytes —
     raw AND through every FlateDecode stream — and counts pages and font
     objects. A PDF with no font object is an image-only PDF: that is precisely
     the artefact this module exists to stop, so `convert()` REFUSES to return
     it. The check is the same one that identified the defect.

  4. IT NEVER INVENTS A FALLBACK. Every engine failed → a named exception with
     each engine's own reason. The caller's job is to say so loudly; nobody's
     job is to quietly ship the picture PDF again.

  ROLLBACK: MODULEX_ORDER_FINAL_PDF_FROM_PPTX=0 restores the pre-P21 copy.

Stdlib only. Windows-first, but the LibreOffice path is cross-platform.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import subprocess
import tempfile
import zlib
from pathlib import Path

log = logging.getLogger("comfy-mvp")

#: ppSaveAsPDF — the PowerPoint SaveAs format id for PDF.
PP_SAVE_AS_PDF = 32
#: A 24 MB Arabic deck through PowerPoint measured well under a minute; this is
#: the ceiling before the child is killed, not an expectation.
DEFAULT_TIMEOUT = int(os.environ.get("MODULEX_PPTX_PDF_TIMEOUT", "420") or "420")
#: Bounds on the stream walk in `pdf_stats` — a pathological PDF may not hang a
#: delivery decision.
_MAX_STREAMS = 4000
_MAX_INFLATED = 96 * 1024 * 1024


class ConversionError(RuntimeError):
    """Every engine refused. `.attempts` carries each one's own reason BY NAME."""

    def __init__(self, message: str, attempts: list | None = None):
        super().__init__(message)
        self.attempts = list(attempts or [])


# --------------------------------------------------------------------------- #
# what the produced bytes actually ARE
# --------------------------------------------------------------------------- #
def _inflated_chunks(data: bytes):
    """`data` itself, then every FlateDecode stream in it that inflates.

    PowerPoint and LibreOffice both write PDF ≥1.5, where the page tree and the
    font dictionaries usually live INSIDE compressed object streams — invisible
    to a raw byte scan. Reading only the raw bytes is how a text-bearing PDF
    gets mislabelled image-only, so the streams are opened.
    """
    yield data
    total = 0
    for n, m in enumerate(re.finditer(rb"stream\r?\n", data)):
        if n >= _MAX_STREAMS or total >= _MAX_INFLATED:
            break
        start = m.end()
        end = data.find(b"endstream", start)
        if end < 0:
            continue
        try:
            raw = zlib.decompress(data[start:end])
        except Exception:  # noqa: BLE001 — not Flate, or not a stream at all
            continue
        total += len(raw)
        yield raw


def pdf_stats(data: bytes) -> dict:
    """{"ok","pages","fonts","has_text","bytes"} — never raises.

    `has_text` is the deliverable gate: a PDF built by binding page images
    (Pillow, `magazine_assembly`) contains no font object anywhere, and a PDF
    exported from a deck always does.
    """
    out = {"ok": False, "pages": 0, "fonts": 0, "has_text": False,
           "bytes": len(data or b"")}
    if not data or not data[:5].startswith(b"%PDF-"):
        return out
    out["ok"] = True
    pages = fonts = 0
    try:
        for chunk in _inflated_chunks(data):
            pages += len(re.findall(rb"/Type\s*/Page(?![sR\w])", chunk))
            fonts += len(re.findall(rb"/(?:BaseFont|FontFile\d?|Type0)\b", chunk))
    except Exception:  # noqa: BLE001
        log.debug("[pptx_to_pdf] pdf_stats scan aborted", exc_info=True)
    out["pages"], out["fonts"] = pages, fonts
    out["has_text"] = fonts > 0
    return out


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------- #
# engine discovery
# --------------------------------------------------------------------------- #
def _is_windows() -> bool:
    return os.name == "nt"


def engine_order() -> list:
    """Operator-controlled. Default: PowerPoint first — it is the renderer the
    deck was designed against, so its PDF is the deck, not an interpretation of
    it. Off-Windows the COM entry is simply not reachable and is dropped."""
    raw = (os.environ.get("MODULEX_PPTX_PDF_ENGINES") or "").strip()
    names = [n.strip().lower() for n in raw.split(",") if n.strip()] \
        or ["powerpoint", "soffice"]
    seen, out = set(), []
    for n in names:
        n = {"pp": "powerpoint", "office": "powerpoint", "msoffice": "powerpoint",
             "libreoffice": "soffice", "lo": "soffice"}.get(n, n)
        if n in ("powerpoint", "soffice") and n not in seen:
            seen.add(n)
            out.append(n)
    if not _is_windows():
        out = [n for n in out if n != "powerpoint"]
    return out or ["soffice"]


def _powershell() -> str:
    for exe in ("powershell.exe", "pwsh.exe", "powershell", "pwsh"):
        p = shutil.which(exe)
        if p:
            return p
    win = os.environ.get("SystemRoot") or r"C:\Windows"
    cand = Path(win) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    return str(cand) if cand.is_file() else ""


def _powerpoint_available() -> tuple:
    """(ok, detail). Asks the REGISTRY for the COM class, which costs nothing and
    does not start PowerPoint — probing must never open an Office window on an
    operator's desktop just to fill in a preflight row."""
    if not _is_windows():
        return False, "PowerPoint automation is Windows-only"
    if not _powershell():
        return False, "powershell.exe was not found — COM cannot be driven"
    try:
        import winreg  # noqa: PLC0415 — Windows-only, imported where it is used
    except Exception as exc:  # noqa: BLE001
        return False, f"winreg is unavailable ({exc.__class__.__name__})"
    for root in (getattr(winreg, "HKEY_CLASSES_ROOT", None),):
        for key in ("PowerPoint.Application", "PowerPoint.Application.16",
                    "PowerPoint.Application.15"):
            try:
                with winreg.OpenKey(root, key + r"\CLSID"):
                    return True, f"Microsoft PowerPoint (COM: {key})"
            except Exception:  # noqa: BLE001
                continue
    return False, ("Microsoft PowerPoint is not registered for automation on this "
                   "machine (no PowerPoint.Application COM class)")


def soffice_path() -> str:
    """The LibreOffice binary, or "". MODULEX_SOFFICE wins over every guess."""
    env = (os.environ.get("MODULEX_SOFFICE") or "").strip().strip('"')
    if env and Path(env).is_file():
        return env
    for name in ("soffice.exe", "soffice", "libreoffice"):
        p = shutil.which(name)
        if p:
            return p
    for base in (os.environ.get("ProgramFiles") or r"C:\Program Files",
                 os.environ.get("ProgramFiles(x86)") or r"C:\Program Files (x86)",
                 r"C:\Program Files", "/usr/lib/libreoffice", "/opt/libreoffice",
                 "/Applications/LibreOffice.app/Contents"):
        for rel in ("LibreOffice/program/soffice.exe", "LibreOffice/program/soffice",
                    "program/soffice", "MacOS/soffice"):
            cand = Path(base) / rel
            try:
                if cand.is_file():
                    return str(cand)
            except Exception:  # noqa: BLE001
                continue
    return ""


def probe() -> dict:
    """Converter availability for the preflight card. Never raises, never starts
    an Office application."""
    if not enabled():
        return {"ok": None, "engine": None, "engines": [],
                "detail": "deck→PDF export disabled "
                          "(MODULEX_ORDER_FINAL_PDF_FROM_PPTX=0) — the order PDF "
                          "falls back to the image-only build"}
    order = engine_order()
    found, detail = [], []
    pp_ok, pp_why = _powerpoint_available()
    so = soffice_path()
    for name in order:
        if name == "powerpoint" and pp_ok:
            found.append("powerpoint")
            detail.append(pp_why)
        elif name == "soffice" and so:
            found.append("soffice")
            detail.append(f"LibreOffice ({so})")
    if found:
        return {"ok": True, "engine": found[0], "engines": found,
                "detail": " · ".join(detail)}
    why = []
    if "powerpoint" in order:
        why.append(f"PowerPoint: {pp_why}")
    if "soffice" in order:
        why.append("LibreOffice: soffice was not found (set MODULEX_SOFFICE)")
    return {"ok": False, "engine": None, "engines": [],
            "detail": "; ".join(why) or "no converter configured"}


def enabled() -> bool:
    """★ P21 ROLLBACK. =0 restores the pre-P21 behaviour byte-for-byte: the
    order PDF is copied from custody's image-only magazine.pdf."""
    return (os.environ.get("MODULEX_ORDER_FINAL_PDF_FROM_PPTX", "1") or "1") \
        .strip().lower() not in ("0", "false", "no", "off")


# --------------------------------------------------------------------------- #
# engine: Microsoft PowerPoint, through a short-lived PowerShell child
# --------------------------------------------------------------------------- #
#: Everything the deck needs to become a PDF, and nothing else.
#:   * paths arrive through the ENVIRONMENT, never the command line — the estate
#:     lives under «C:\المشروع» and an Arabic argv through cmd's codepage is the
#:     exact class of bug that already cost this project a launcher rewrite;
#:   * DisplayAlerts = ppAlertsNone: a modal dialog is how COM automation hangs
#:     forever, so PowerPoint is told not to raise one;
#:   * AutomationSecurity = msoAutomationSecurityForceDisable: an unattended
#:     night run does not execute macros out of a template;
#:   * Open(…, ReadOnly, Untitled=false, WithWindow=false): the deck on disk is
#:     never modified and no window appears on the operator's desktop;
#:   * ★ Quit ONLY IF WE STARTED IT. The operator very often has PowerPoint open
#:     with their own work — killing it to tidy up after a background export
#:     would be the worst kind of "helpful". If POWERPNT was already running we
#:     close OUR presentation and leave their application exactly as we found it.
_PS_EXPORT = r"""
$ErrorActionPreference = 'Stop'
$src = $env:MX_PPTX_SRC
$dst = $env:MX_PPTX_DST
$code = 0
$msg  = ''
$wasRunning = [bool](Get-Process -Name POWERPNT -ErrorAction SilentlyContinue)
$app = $null
$pres = $null
try {
    $app = New-Object -ComObject PowerPoint.Application
    try { $app.DisplayAlerts = 1 } catch {}
    try { $app.AutomationSecurity = 3 } catch {}
    $pres = $app.Presentations.Open($src, -1, 0, 0)
    $pres.SaveAs($dst, 32, 0)
    $pres.Close()
    $pres = $null
} catch {
    $code = 3
    $msg  = $_.Exception.Message
}
if ($pres -ne $null) { try { $pres.Close() } catch {} }
if (($app -ne $null) -and (-not $wasRunning)) { try { $app.Quit() } catch {} }
if ($msg -ne '') { [Console]::Error.WriteLine($msg) }
exit $code
"""


def _run_powerpoint(src: Path, dst: Path, timeout: int) -> None:
    ps = _powershell()
    if not ps:
        raise RuntimeError("powershell.exe was not found")
    with tempfile.TemporaryDirectory(prefix="mx_pp2pdf_") as td:
        script = Path(td) / "export.ps1"
        # UTF-8 **with BOM**: Windows PowerShell 5.1 reads a BOM-less UTF-8 file
        # as the ANSI codepage. The script body is ASCII today, and the BOM keeps
        # it correct the day it is not.
        script.write_text(_PS_EXPORT, encoding="utf-8-sig")
        env = dict(os.environ)
        env["MX_PPTX_SRC"] = str(src)
        env["MX_PPTX_DST"] = str(dst)
        cmd = [ps, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
               "-File", str(script)]
        try:
            proc = subprocess.run(cmd, env=env, timeout=timeout,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"PowerPoint did not finish within {timeout}s — the child was "
                f"killed (a modal dialog on the desktop is the usual cause)")
        if proc.returncode != 0:
            err = (proc.stderr or b"").decode("utf-8", "replace").strip() \
                or (proc.stdout or b"").decode("utf-8", "replace").strip()
            raise RuntimeError(f"PowerPoint refused the export: "
                               f"{err or f'exit {proc.returncode}'}")
    if not dst.is_file():
        raise RuntimeError("PowerPoint reported success but wrote no file")


# --------------------------------------------------------------------------- #
# engine: LibreOffice
# --------------------------------------------------------------------------- #
def _run_soffice(src: Path, dst: Path, timeout: int) -> None:
    exe = soffice_path()
    if not exe:
        raise RuntimeError("soffice was not found (set MODULEX_SOFFICE)")
    with tempfile.TemporaryDirectory(prefix="mx_lo2pdf_") as td:
        outdir = Path(td) / "out"
        outdir.mkdir()
        # A PRIVATE user profile. Without it, a headless convert silently does
        # nothing whenever the operator already has LibreOffice open — it
        # attaches to the running instance instead of converting.
        profile = (Path(td) / "profile").as_uri()
        cmd = [exe, f"-env:UserInstallation={profile}", "--headless", "--norestore",
               "--invisible", "--nolockcheck", "--nodefault",
               "--convert-to", "pdf:impress_pdf_Export",
               "--outdir", str(outdir), str(src)]
        try:
            proc = subprocess.run(cmd, timeout=timeout, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE)
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"LibreOffice did not finish within {timeout}s")
        made = sorted(outdir.glob("*.pdf"))
        if not made:
            err = (proc.stderr or b"").decode("utf-8", "replace").strip() \
                or (proc.stdout or b"").decode("utf-8", "replace").strip()
            raise RuntimeError(f"LibreOffice produced no PDF "
                               f"({err or f'exit {proc.returncode}'})")
        shutil.copyfile(made[0], dst)


_ENGINES = {"powerpoint": _run_powerpoint, "soffice": _run_soffice}
_ENGINE_LABEL = {"powerpoint": "Microsoft PowerPoint", "soffice": "LibreOffice"}


# --------------------------------------------------------------------------- #
# the public call
# --------------------------------------------------------------------------- #
def convert(src, dest, *, timeout: int | None = None, require_text: bool = True,
            expect_pages: int = 0, engines: list | None = None) -> dict:
    """Export `src` (.pptx) to `dest` (.pdf). Returns the record, or RAISES.

    The engines are tried in order and each one is judged on its OUTPUT, not on
    its exit code: a converter that returns 0 and writes an image-only PDF has
    failed at the only thing that matters here, so it is recorded as a failure
    and the next engine gets its turn (`require_text=False` turns that judgement
    off for a caller that genuinely wants pictures).

    `dest` is replaced ATOMICALLY and only ever by a PDF that passed. A failed
    run cannot leave a half-written file where a delivery will find it, and it
    cannot damage a good PDF that is already there.

    `expect_pages` (the deck's slide count) is compared and REPORTED — a
    mismatch is a named warning in the record, never a silent trim. It does not
    veto: PowerPoint legitimately drops a slide marked hidden, and refusing the
    magazine over that would trade a real deliverable for a rule.
    """
    src, dest = Path(src), Path(dest)
    if not src.is_file():
        raise ConversionError(f"the deck does not exist: {src}")
    tmo = int(timeout or DEFAULT_TIMEOUT)
    order = [e for e in (engines or engine_order()) if e in _ENGINES]
    if not order:
        raise ConversionError("no usable converter is configured "
                              "(MODULEX_PPTX_PDF_ENGINES)")
    dest.parent.mkdir(parents=True, exist_ok=True)
    attempts = []
    for name in order:
        tmp = dest.with_name(dest.name + f".{name}.tmp")
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:  # noqa: BLE001
            pass
        try:
            log.info("[pptx_to_pdf] %s → PDF via %s …", src.name, name)
            _ENGINES[name](src, tmp, tmo)
            data = tmp.read_bytes()
            st = pdf_stats(data)
            if not st["ok"]:
                raise RuntimeError("the produced file is not a PDF")
            if require_text and not st["has_text"]:
                raise RuntimeError(
                    f"the produced PDF carries NO font object ({st['pages']} "
                    f"page(s)) — that is an image-only PDF, which is the exact "
                    f"defect this export exists to end")
            os.replace(tmp, dest)
            rec = {"ok": True, "engine": name,
                   "engine_label": _ENGINE_LABEL.get(name, name),
                   "path": str(dest), "bytes": len(data), "sha256": sha256(data),
                   "pages": st["pages"], "fonts": st["fonts"],
                   "has_text": st["has_text"], "expect_pages": int(expect_pages or 0),
                   "source_pptx": str(src), "attempts": attempts}
            if expect_pages and st["pages"] and st["pages"] != int(expect_pages):
                rec["page_mismatch"] = (
                    f"the deck has {int(expect_pages)} slide(s) and the PDF has "
                    f"{st['pages']} page(s)")
                log.warning("[pptx_to_pdf] %s", rec["page_mismatch"])
            log.info("[pptx_to_pdf] %s → %s via %s · %d page(s), %d font object(s), "
                     "%d bytes, sha %s…", src.name, dest.name, name, st["pages"],
                     st["fonts"], len(data), rec["sha256"][:12])
            return rec
        except Exception as exc:  # noqa: BLE001
            attempts.append({"engine": name, "error": f"{exc}"})
            log.warning("[pptx_to_pdf] %s could not export %s: %s",
                        _ENGINE_LABEL.get(name, name), src.name, exc)
        finally:
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:  # noqa: BLE001
                pass
    raise ConversionError(
        "no converter could turn the deck into a text-bearing PDF — "
        + "; ".join(f"{_ENGINE_LABEL.get(a['engine'], a['engine'])}: {a['error']}"
                    for a in attempts),
        attempts)


# --------------------------------------------------------------------------- #
# CLI — `python -m execution_console.services.pptx_to_pdf <in.pptx> [out.pdf]`
# The same code path the console uses, runnable by hand on any deck in the
# estate. This is what P21_VERIFY and the operator's re-export button call.
# --------------------------------------------------------------------------- #
def _main(argv: list) -> int:
    import json as _json
    if not argv:
        print(_json.dumps({"probe": probe(), "engine_order": engine_order()},
                          ensure_ascii=False, indent=1))
        return 0
    src = Path(argv[0])
    dst = Path(argv[1]) if len(argv) > 1 else src.with_suffix(".pdf")
    try:
        rec = convert(src, dst)
    except ConversionError as exc:
        print(_json.dumps({"ok": False, "error": str(exc),
                           "attempts": exc.attempts}, ensure_ascii=False, indent=1))
        return 2
    print(_json.dumps(rec, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(_main(sys.argv[1:]))
