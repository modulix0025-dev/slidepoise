"""Read-only probe of the operator's estate: templates, fonts, accounts, Office, routes, health, model licences.

Rules:
* read-only — files are opened for reading (PPTX as zip), nothing is written in the estate;
* children only through :func:`mxstudio.proc.run_hidden` (injectable ``runner`` for tests);
* nothing is guessed: a fact that cannot be read is reported as ``unknown`` with the reason;
* the model-licence probe reports and suggests; it never edits a workflow.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import sys
import unicodedata
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from lxml import etree

from ._util import read_text, rel_posix, walk_files
from .discover import system_dir

Runner = Callable[..., Any]
HttpGet = Callable[[str], int]

NS = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main",
      "p": "http://schemas.openxmlformats.org/presentationml/2006/main"}
DEFAULT_BASE_NAMES = ("إياد", "جيداء", "ليلى", "Eyad", "Gaidaa")
EMU_PER_CM = 360000
LAM_ALEF_FORMS = range(0xFEF5, 0xFEFD)
PREFIX_LETTERS = "لبوفك"
TATWEEL = "ـ"
_ALEF_UNIFY = str.maketrans({"إ": "ا", "أ": "ا", "آ": "ا", "ٱ": "ا"})

_SLIDE_RE = re.compile(r"^ppt/slides/slide(\d+)\.xml$")
_PH_PIC_RE = re.compile(rb'<p:ph[^>]*type="pic"')


def _default_runner(cmd, **kw):
    from mxstudio.proc import run_hidden

    return run_hidden(cmd, **kw)


# ---------------------------------------------------------------- templates ----

def _codepoints(text: str) -> list[str]:
    return [f"U+{ord(c):04X}" for c in text]


def _norm_map(text: str) -> tuple[str, list[int]]:
    """NFKC + alef-unified text and, for each normalised char, the index of its source char."""
    out: list[str] = []
    idx: list[int] = []
    for i, ch in enumerate(text):
        for c in unicodedata.normalize("NFKC", ch).translate(_ALEF_UNIFY):
            out.append(c)
            idx.append(i)
    return "".join(out), idx


def name_occurrences(runs: list[str], base_name: str) -> list[dict]:
    """Every occurrence of ``base_name`` (incl. prefix-attached and presentation-form spellings)."""
    text = "".join(runs)
    norm, idx = _norm_map(text)
    key = unicodedata.normalize("NFKC", base_name).translate(_ALEF_UNIFY)
    bounds = []
    pos = 0
    for r in runs:
        bounds.append((pos, pos + len(r)))
        pos += len(r)
    hits = []
    start = norm.find(key)
    while start >= 0 and key:
        s = start
        prefix = ""
        if s >= 1 and norm[s - 1] == TATWEEL and s >= 2 and norm[s - 2] in PREFIX_LETTERS:
            prefix, s = norm[s - 2:start], s - 2
        elif s >= 1 and norm[s - 1] in PREFIX_LETTERS and (s < 2 or not norm[s - 2].isalpha()):
            prefix, s = norm[s - 1], s - 1
        o_start, o_end = idx[s], idx[start + len(key) - 1] + 1
        original = text[o_start:o_end]
        name_part = text[idx[start]:o_end]
        runs_hit = [i for i, (a, b) in enumerate(bounds) if a < o_end and b > o_start]
        cps = [ord(c) for c in original]
        hits.append({
            "base_name": base_name, "original": original, "codepoints": _codepoints(original),
            "prefix": prefix, "literal_match": base_name in original,
            "inside_longer_word": o_end < len(text) and text[o_end].isalpha(),
            "name_part_codepoints": _codepoints(name_part),
            "lam_alef_ligature": any(c in LAM_ALEF_FORMS for c in cps),
            "presentation_forms": any(0xFB50 <= c <= 0xFDFF or 0xFE70 <= c <= 0xFEFF for c in cps),
            "runs": runs_hit, "single_run": len(runs_hit) == 1,
        })
        start = norm.find(key, start + len(key))
    return hits


def template_anatomy(path: Path, base_names: tuple[str, ...] = DEFAULT_BASE_NAMES) -> dict[str, Any]:
    out: dict[str, Any] = {"file": path.name, "bytes": path.stat().st_size, "slides": []}
    try:
        with zipfile.ZipFile(path) as z:
            pres = z.read("ppt/presentation.xml")
            m = re.search(rb'<p:sldSz[^>]*cx="(\d+)"[^>]*cy="(\d+)"', pres)
            if m:
                cx, cy = int(m.group(1)), int(m.group(2))
                out["slide_size_emu"] = [cx, cy]
                out["slide_size_cm"] = [round(cx / EMU_PER_CM, 3), round(cy / EMU_PER_CM, 3)]
            names = sorted((int(mm.group(1)), n) for n in z.namelist() if (mm := _SLIDE_RE.match(n)))
            ligatures: list[dict] = []
            occurrences: list[dict] = []
            for number, name in names:
                xml = z.read(name)
                root = etree.fromstring(xml)
                paragraphs = []
                for p_index, para in enumerate(root.iter(f"{{{NS['a']}}}p")):
                    runs = [t.text or "" for t in para.iter(f"{{{NS['a']}}}t")]
                    if runs:
                        paragraphs.append(runs)
                        joined = "".join(runs)
                        for bn in base_names:
                            for hit in name_occurrences(runs, bn):
                                occurrences.append({"slide": number, "paragraph": p_index, **hit})
                        for i, ch in enumerate(joined):
                            if ord(ch) in LAM_ALEF_FORMS:
                                ctx = joined[max(0, i - 2): i + 6]
                                ligatures.append({"slide": number, "paragraph": p_index, "char": f"U+{ord(ch):04X}",
                                                  "context_codepoints": _codepoints(ctx)})
                hidden = bool(re.search(rb'<p:sld\b[^>]*\bshow="0"', xml))
                out["slides"].append({
                    "slide": number, "hidden": hidden,
                    "ph_pic": len(_PH_PIC_RE.findall(xml)),
                    "p_pic": len(re.findall(rb"<p:pic\b", xml)),
                    "p_sp": len(re.findall(rb"<p:sp\b", xml)),
                    "texts": ["".join(r) for r in paragraphs],
                    "sizes_pt": sorted({int(s) / 100 for s in re.findall(rb'\bsz="(\d+)"', xml)}),
                    "typefaces": sorted({t.decode("utf-8", "replace") for t in
                                         re.findall(rb'<a:(?:latin|ea|cs|sym)\b[^>]*typeface="([^"]*)"', xml)}),
                    "rtl_paragraphs": len(re.findall(rb'\brtl="1"', xml)),
                })
            out["slide_count"] = len(names)
            out["hidden_slides"] = [s["slide"] for s in out["slides"] if s["hidden"]]
            out["typefaces"] = sorted({t for s in out["slides"] for t in s["typefaces"]})
            out["name_occurrences"] = occurrences
            out["lam_alef_ligatures"] = ligatures
            out["picture_slots"] = {s["slide"]: s["ph_pic"] for s in out["slides"] if s["ph_pic"]}
    except (zipfile.BadZipFile, KeyError, etree.XMLSyntaxError, OSError) as exc:
        out["error"] = f"{exc.__class__.__name__}: {exc}"
    return out


def registry_base_names(om_dir: Path) -> list[str]:
    """Base names written literally in OM's story_engine.py (defaults); the live registry is in Postgres."""
    path = om_dir / "app" / "services" / "story_engine.py"
    try:
        text = read_text(path)
    except (OSError, UnicodeDecodeError):
        return []
    names = set(re.findall(r"""["']base_name["']\s*:\s*["']([^"']{2,40})["']""", text))
    names |= set(re.findall(r"""_base\s*=\s*["']([^"']{2,40})["']""", text))
    return sorted(names)


def templates(om_dir: Path, base_names: tuple[str, ...]) -> dict[str, Any]:
    tdir = om_dir / "story_templates"
    if not tdir.is_dir():
        return {"dir": str(tdir), "exists": False, "files": []}
    names = tuple(dict.fromkeys(list(base_names) + registry_base_names(om_dir)))
    files = [template_anatomy(p, names) for p in sorted(tdir.iterdir()) if p.suffix.lower() == ".pptx"]
    others = sorted(p.name for p in tdir.iterdir() if p.is_file() and p.suffix.lower() != ".pptx")
    return {"dir": str(tdir), "exists": True, "base_names": list(names), "files": files, "other_files": others}


# ---------------------------------------------------------------- fonts ----

_FONT_SUFFIX = re.compile(r"\s*\((?:TrueType|OpenType|Type 1|All res)\)\s*$", re.IGNORECASE)
_STYLE_WORDS = re.compile(r"\s+(?:Regular|Bold|Italic|Light|Medium|Black|Thin|SemiBold|ExtraBold|ExtraLight|"
                          r"Bold Italic|Oblique)(?:\s+(?:Italic|Oblique))?$", re.IGNORECASE)


def _registry_fonts() -> list[dict]:
    try:
        import winreg
    except ImportError:
        return []
    found = []
    key_path = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"
    for scope, hive in (("machine", winreg.HKEY_LOCAL_MACHINE), ("user", winreg.HKEY_CURRENT_USER)):
        try:
            with winreg.OpenKey(hive, key_path) as key:
                i = 0
                while True:
                    try:
                        name, value, _ = winreg.EnumValue(key, i)
                    except OSError:
                        break
                    found.append({"name": _FONT_SUFFIX.sub("", name), "file": str(value), "scope": scope})
                    i += 1
        except OSError:
            continue
    return found


def installed_fonts(runner: Runner | None = None) -> dict[str, Any]:
    if sys.platform == "win32":
        entries = _registry_fonts()
    else:
        entries = []
        run = runner or _default_runner
        try:
            res = run(["fc-list", ":", "family"], timeout=60)
            for line in (res.stdout or b"").decode("utf-8", "replace").splitlines():
                for fam in line.split(","):
                    if fam.strip():
                        entries.append({"name": fam.strip(), "scope": "machine"})
        except Exception as exc:  # noqa: BLE001
            return {"available": False, "reason": f"fc-list: {exc}", "fonts": []}
    families = {}
    for e in entries:
        fam = _STYLE_WORDS.sub("", e["name"]).strip()
        families.setdefault(fam, set()).add(e.get("scope", "machine"))
    return {"available": True, "count": len(entries),
            "families": {k: sorted(v) for k, v in sorted(families.items())}}


def typeface_visibility(typefaces: list[str], fonts: dict[str, Any]) -> list[dict]:
    """Exact typeface match (ends trimmed only — «Blabeloo  MagdySoliman» keeps its two spaces)."""
    fam = fonts.get("families", {})
    rows = []
    for tf in typefaces:
        name = tf.strip()
        if not name or name.startswith("+"):  # theme fonts (+mj-lt, +mn-cs …)
            continue
        scopes = fam.get(name)
        rows.append({"typeface": name, "installed": bool(scopes), "scopes": scopes or [],
                     "user_scope_only": scopes == ["user"]})
    return rows


# ---------------------------------------------------------------- processes / office ----

_PS_OWNERS = r"""
$ErrorActionPreference = 'SilentlyContinue'
$out = @()
foreach ($port in 8000,6060,8200,9000) {
  $c = Get-NetTCPConnection -LocalPort $port -State Listen | Select-Object -First 1
  if ($c) {
    $p = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $c.OwningProcess)
    $o = Invoke-CimMethod -InputObject $p -MethodName GetOwner
    $out += [pscustomobject]@{port=$port; pid=$p.ProcessId; name=$p.Name; exe=$p.ExecutablePath; user=("" + $o.Domain + "\" + $o.User)}
  }
}
$out | ConvertTo-Json -Compress
"""


def process_owners(runner: Runner | None = None) -> dict[str, Any]:
    """Which Windows account runs the services on 8000/6060/8200/9000 (PowerShell CIM, then tasklist)."""
    if sys.platform != "win32" and runner is None:
        return {"available": False, "reason": "Windows only — pending on-device probe"}
    run = runner or _default_runner
    studio_user = f"{os.environ.get('USERDOMAIN', '')}\\{os.environ.get('USERNAME', '')}".strip("\\")
    try:
        res = run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _PS_OWNERS], timeout=60)
        raw = (res.stdout or b"").decode("utf-8", "replace").strip()
        data = json.loads(raw) if raw else []
        if isinstance(data, dict):
            data = [data]
        if data:
            return {"available": True, "method": "powershell-cim", "studio_user": studio_user, "listeners": data,
                    "same_account_as_studio": all(d.get("user", "").lower().endswith(
                        os.environ.get("USERNAME", "\0").lower()) for d in data)}
    except Exception as exc:  # noqa: BLE001
        ps_error = str(exc)
    else:
        ps_error = "no listener found by Get-NetTCPConnection"
    try:
        res = run(["tasklist", "/v", "/fo", "csv"], timeout=60)
        rows = list(csv.DictReader(io.StringIO((res.stdout or b"").decode("utf-8", "replace"))))
        keep = [{"name": r.get("Image Name"), "pid": r.get("PID"), "user": r.get("User Name")}
                for r in rows if re.search(r"python|uvicorn|modulex|console|soffice|powerpnt",
                                           (r.get("Image Name") or ""), re.IGNORECASE)]
        return {"available": True, "method": "tasklist", "studio_user": studio_user, "processes": keep,
                "powershell_error": ps_error}
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": f"powershell: {ps_error}; tasklist: {exc}"}


def office_versions(runner: Runner | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"powerpoint": None, "libreoffice": None}
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"PowerPoint.Application\CurVer") as key:
            out["powerpoint"] = winreg.QueryValue(key, None)
    except Exception as exc:  # noqa: BLE001
        out["powerpoint_reason"] = "not Windows" if sys.platform != "win32" else f"not registered ({exc})"
    from . import _vendor

    try:
        soffice = _vendor.pptx_to_pdf().soffice_path()
    except Exception:  # noqa: BLE001
        soffice = ""
    out["soffice_path_found"] = bool(soffice)
    if soffice:
        program = Path(soffice).parent
        for ini in ("version.ini", "versionrc"):
            try:
                m = re.search(r"(?:MsiProductVersion|ProductVersion|buildid)\s*=\s*(\S+)",
                              (program / ini).read_text(encoding="utf-8", errors="replace"))
                if m:
                    out["libreoffice"] = m.group(1)
                    break
            except OSError:
                continue
        if not out["libreoffice"] and sys.platform != "win32":
            try:
                res = (runner or _default_runner)([soffice, "--version"], timeout=60)
                out["libreoffice"] = (res.stdout or b"").decode("utf-8", "replace").strip()[:120] or None
            except Exception as exc:  # noqa: BLE001
                out["libreoffice_reason"] = str(exc)
    try:
        out["converter_probe"] = _vendor.pptx_to_pdf().probe()
    except Exception as exc:  # noqa: BLE001
        out["converter_probe"] = {"error": str(exc)}
    return out


# ---------------------------------------------------------------- code facts ----

def editor_routes(om_dir: Path) -> dict[str, Any]:
    """Where /api/editor is served and which static mounts exist (grep, read-only)."""
    routes, statics, html = [], [], []
    for path in walk_files(om_dir, suffixes=(".py", ".html", ".js"), max_depth=6):
        rel = rel_posix(path, om_dir)
        try:
            text = read_text(path)
        except (OSError, UnicodeDecodeError):
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if "/api/editor" in line and len(routes) < 80:
                routes.append({"file": rel, "line": n, "text": line.strip()[:200]})
            if "StaticFiles(" in line and len(statics) < 40:
                statics.append({"file": rel, "line": n, "text": line.strip()[:200]})
        if path.suffix == ".html" and "editor" in rel.lower():
            html.append(rel)
    return {"api_editor_refs": routes, "static_mounts": statics, "editor_html": html[:40]}


def qa_presence(console_dir: Path) -> dict[str, Any]:
    def where(name):
        return [rel_posix(p, console_dir) for p in walk_files(console_dir, names=(name,), max_depth=6)]

    qa_refs = [rel_posix(p, console_dir) for p in walk_files(console_dir, max_depth=3)
               if "qa_refs" in rel_posix(p, console_dir).split("/")[:-1]][:20]
    return {"qc_agent.py": where("qc_agent.py"), "qc_store.py": where("qc_store.py"), "qa_refs_sample": qa_refs}


# ---------------------------------------------------------------- health ----

HEALTH_PORTS = {"OM": 8000, "Console": 6060, "Store": 8200, "Orchestrator": 9000}
HEALTH_PATHS = ("/health", "/api/health", "/healthz", "/v1/health")


def _http_get(url: str) -> int:
    import httpx

    return httpx.get(url, timeout=2.0).status_code


def health(http_get: HttpGet | None = None) -> dict[str, Any]:
    get = http_get or _http_get
    out = {}
    for system, port in HEALTH_PORTS.items():
        rows = []
        for path in HEALTH_PATHS:
            url = f"http://127.0.0.1:{port}{path}"
            try:
                rows.append({"path": path, "status": get(url)})
            except Exception as exc:  # noqa: BLE001
                rows.append({"path": path, "error": exc.__class__.__name__})
        out[system] = {"port": port, "responses": rows,
                       "up": any(r.get("status") for r in rows),
                       "healthy_path": next((r["path"] for r in rows if r.get("status") == 200), None)}
    return out


# ---------------------------------------------------------------- model licences ----

MODEL_KEYS = ("ckpt_name", "unet_name", "clip_name", "clip_name1", "clip_name2", "clip_name3", "vae_name",
              "lora_name", "model_name", "control_net_name", "style_model_name", "ipadapter_file")
#: Non-commercial weights are recognised from the policy file (single source of truth, operator
#: decision D13) plus generic spellings; the code itself never names a banned component literally.
_GENERIC_NONCOMMERCIAL = (re.compile(r"kontext", re.IGNORECASE), re.compile(r"flux(?:\.?1)?[-_. ]?dev", re.IGNORECASE))
_FALLBACK_REASON = "FLUX.1 (dev) family: non-commercial licence"
_FALLBACK_ALTERNATIVE = "Qwen-Image / Qwen-Image-Edit-2511 / FLUX.1 schnell (Apache-2.0)"
_PERMISSIVE = (
    (re.compile(r"schnell", re.IGNORECASE), "FLUX.1 schnell", "Apache-2.0"),
    (re.compile(r"qwen[-_. ]?image[-_. ]?edit", re.IGNORECASE), "Qwen-Image-Edit", "Apache-2.0"),
    (re.compile(r"qwen[-_. ]?image", re.IGNORECASE), "Qwen-Image", "Apache-2.0"),
)


def _policy_banned() -> list[dict]:
    path = Path(__file__).resolve().parents[2] / "catalog" / "licence_policy.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("banned_components", [])
    except (OSError, ValueError):
        return []


def classify_model(filename: str) -> dict[str, Any]:
    low = filename.lower()
    if "schnell" not in low:
        for comp in _policy_banned():
            if any(p in low for p in comp.get("patterns", [])):
                return {"family": comp.get("id"), "licence": comp.get("reason"), "commercial_use": False,
                        "free_alternative": comp.get("replacement"), "matched_by": "catalog/licence_policy.json"}
        if any(rx.search(filename) for rx in _GENERIC_NONCOMMERCIAL):
            return {"family": "flux-dev", "licence": _FALLBACK_REASON, "commercial_use": False,
                    "free_alternative": _FALLBACK_ALTERNATIVE, "matched_by": "generic spelling"}
    for rx, family, licence in _PERMISSIVE:
        if rx.search(filename):
            return {"family": family, "licence": licence, "commercial_use": True}
    return {"family": None, "licence": "unknown — verify the model card", "commercial_use": None}


def _model_refs(obj: Any, acc: list[tuple[str, str]]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in MODEL_KEYS and isinstance(v, str):
                acc.append((k, v))
            else:
                _model_refs(v, acc)
        # API format: {"inputs": {...}} handled by recursion; UI format: widgets_values lists
        if obj.get("type", "").endswith(("Loader", "LoaderSimple")) and isinstance(obj.get("widgets_values"), list):
            for w in obj["widgets_values"]:
                if isinstance(w, str) and re.search(r"\.(safetensors|ckpt|gguf|pt|pth|bin)$", w, re.IGNORECASE):
                    acc.append(("widgets_values", w))
    elif isinstance(obj, list):
        for v in obj:
            _model_refs(v, acc)


def model_licences(console_dir: Path) -> dict[str, Any]:
    """List checkpoints referenced by ComfyUI workflow JSON files; flag non-commercial ones. Report only."""
    refs = []
    scanned = 0
    for path in walk_files(console_dir, suffixes=(".json",), max_depth=7):
        try:
            if path.stat().st_size > 5 * 1024 * 1024:
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            continue
        acc: list[tuple[str, str]] = []
        _model_refs(data, acc)
        if not acc:
            continue
        scanned += 1
        for key, value in dict.fromkeys(acc):
            refs.append({"workflow": rel_posix(path, console_dir), "key": key, "file": value,
                         **classify_model(value)})
    flagged = [r for r in refs if r["commercial_use"] is False]
    return {"workflows_with_models": scanned, "references": refs, "non_commercial": flagged,
            "action": "report only — the Kit never edits a workflow (operator decision D13 / R5)"}


# ---------------------------------------------------------------- entry point ----

def probe(found: dict, *, base_names: tuple[str, ...] = DEFAULT_BASE_NAMES, runner: Runner | None = None,
          http_get: HttpGet | None = None, network: bool = True) -> dict[str, Any]:
    om = system_dir(found, "OM")
    console = system_dir(found, "Console")
    out: dict[str, Any] = {"root": found["root"]}
    out["templates"] = templates(om, base_names) if om else {"exists": False, "reason": "OM not found"}
    fonts = installed_fonts(runner)
    out["fonts"] = {k: v for k, v in fonts.items() if k != "families"}
    tfs = sorted({t for f in out["templates"].get("files", []) for t in f.get("typefaces", [])})
    out["template_typefaces"] = typeface_visibility(tfs, fonts) if fonts.get("available") else []
    out["process_owners"] = process_owners(runner)
    out["office"] = office_versions(runner)
    out["editor"] = editor_routes(om) if om else None
    out["qa"] = qa_presence(console) if console else None
    out["health"] = health(http_get) if network else {"skipped": "network disabled"}
    out["model_licences"] = model_licences(console) if console else None
    return out
