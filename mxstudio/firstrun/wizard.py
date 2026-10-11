"""First-run wizard backend: workspace → providers → discovery → doctor.

Rules:
* state lives in settings under ``firstrun`` so the wizard resumes where it stopped after a
  restart; the UI only renders what :meth:`Wizard.state` returns;
* workspace is mandatory, must be absolute, writable, and **outside the program folder**
  (an agent with workspace access must not be able to modify the program); Arabic paths
  are first-class;
* provider API keys are handed to the injected secret store (DPAPI) and only their
  fingerprint is persisted — a key never lands in ``settings.json``;
* discovery uses the Integration Kit when it is available and is skippable;
* the doctor step records the red lines; red lines do not block finishing (the Doctor page
  keeps offering «إصلاح»), but they are reported, never hidden.
"""
from __future__ import annotations

import hashlib
import os
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from mxstudio.config import Settings, default_workspace

STEPS = ("workspace", "providers", "discovery", "doctor")
SKIPPABLE = {"providers", "discovery"}
PROVIDER_FIELDS = {"kind", "base_url", "model", "workflow", "enabled"}


class SecretStore(Protocol):
    def put(self, name: str, secret: str) -> str:  # returns fingerprint sha256(secret)[:8]
        ...


class WizardError(Exception):
    def __init__(self, code: str, ar: str, en: str):
        super().__init__(f"{code}: {en}")
        self.code, self.ar, self.en = code, ar, en

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "ar": self.ar, "en": self.en}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _program_dir() -> Path | None:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    local = os.environ.get("LOCALAPPDATA")
    return Path(local) / "Programs" / "ModuleX Magazine Studio" if local else None


def _default_discover() -> dict[str, Any]:
    try:
        from mxstudio import kit  # type: ignore[attr-defined]
    except ImportError:
        return {"available": False, "ar": "الـKit مش موجود في النسخة دي — تقدر تعمل الاكتشاف بعدين من صفحة الـKit.",
                "en": "The Integration Kit is not in this build; run discovery later from the Kit page."}
    discover = getattr(kit, "discover", None)
    discover = getattr(discover, "discover", discover)
    if not callable(discover):
        return {"available": False, "ar": "الـKit مفيهوش اكتشاف لسه.", "en": "The Kit exposes no discovery yet."}
    result = discover()
    return {"available": True, "result": result}


def _default_doctor() -> list[dict[str, Any]]:
    from mxstudio.doctor import run_all
    return run_all()


class Wizard:
    def __init__(self, settings: Settings | None = None, *, secret_store: SecretStore | None = None,
                 discover: Callable[[], dict[str, Any]] | None = None,
                 doctor: Callable[[], list[dict[str, Any]]] | None = None, program_dir: Path | None = None):
        self.settings = settings or Settings()
        self.secret_store = secret_store
        self.discover = discover or _default_discover
        self.doctor = doctor or _default_doctor
        self.program_dir = program_dir if program_dir is not None else _program_dir()

    # ---- state ----
    def state(self) -> dict[str, Any]:
        data = self.settings.load()
        fr = dict(data.get("firstrun") or {})
        fr.setdefault("step", STEPS[0])
        fr.setdefault("completed", [])
        fr.setdefault("skipped", [])
        fr.setdefault("done", False)
        fr["steps"] = list(STEPS)
        fr["workspace_default"] = str(default_workspace())
        fr["workspace"] = data.get("workspace") or str(default_workspace())
        return fr

    def needed(self) -> bool:
        return not self.state()["done"]

    def _save(self, fr: dict[str, Any]) -> dict[str, Any]:
        keep = {k: v for k, v in fr.items() if k not in ("steps", "workspace_default", "workspace")}
        keep["updated_at"] = _now()
        self.settings.update({"firstrun": keep})
        return self.state()

    def _advance(self, fr: dict[str, Any], step: str, *, skipped: bool = False) -> dict[str, Any]:
        if step not in fr["completed"]:
            fr["completed"] = [*fr["completed"], step]
        if skipped and step not in fr["skipped"]:
            fr["skipped"] = [*fr["skipped"], step]
        remaining = [s for s in STEPS if s not in fr["completed"]]
        fr["step"] = remaining[0] if remaining else "done"
        fr["done"] = not remaining
        if fr["done"]:
            fr["finished_at"] = _now()
        return self._save(fr)

    def _require_current(self, step: str) -> dict[str, Any]:
        if step not in STEPS:
            raise WizardError("unknown_step", f"مفيش خطوة اسمها {step}.", f"Unknown step {step}.")
        fr = self.state()
        allowed = [s for s in STEPS if s in fr["completed"]] + [fr["step"]]
        if step not in allowed:
            raise WizardError("out_of_order", "لازم تخلّص الخطوات اللي قبلها الأول.", "Finish the previous steps first.")
        return fr

    # ---- steps ----
    def validate_workspace(self, raw: str) -> Path:
        if not raw or not str(raw).strip():
            raise WizardError("workspace_empty", "اختار فولدر لمساحة العمل.", "Choose a workspace folder.")
        path = Path(str(raw).strip())
        if not path.is_absolute():
            raise WizardError("workspace_relative", "المسار لازم يكون كامل (يبدأ بحرف القرص).",
                              "The path must be absolute.")
        if self.program_dir:
            try:
                path.resolve().relative_to(Path(self.program_dir).resolve())
                raise WizardError("workspace_in_program",
                                  "مساحة العمل مينفعش تكون جوه فولدر البرنامج — اختار مكان برّاه (الافتراضي C:\\المشروع).",
                                  "The workspace cannot be inside the program folder.")
            except ValueError:
                pass
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".mxs-write-test"
            probe.write_text("مساحة العمل", encoding="utf-8")
            ok = probe.read_text(encoding="utf-8") == "مساحة العمل"
            probe.unlink()
        except OSError as exc:
            raise WizardError("workspace_unwritable", f"مش قادرين نكتب في {path}.",
                              f"Cannot write to {path} ({exc.strerror}).") from exc
        if not ok:
            raise WizardError("workspace_roundtrip", "الكتابة والقراءة في المسار ده مش مطابقين.",
                              "Write/read round-trip on this path failed.")
        return path

    def submit(self, step: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        fr = self._require_current(step)
        payload = payload or {}
        if step == "workspace":
            path = self.validate_workspace(payload.get("path") or str(default_workspace()))
            for sub in ("stories", "art", "templates", "packs", "exports"):
                (path / sub).mkdir(exist_ok=True)
            self.settings.update({"workspace": str(path)})
            fr["workspace_set"] = str(path)
        elif step == "providers":
            fr["providers"] = self._providers(payload)
        elif step == "discovery":
            result = self.discover()
            fr["discovery"] = {"at": _now(), **result}
        elif step == "doctor":
            results = self.doctor()
            red = [r["id"] for r in results if r.get("level") == "red" or not r.get("ok", True)]
            fr["doctor"] = {"at": _now(), "red": red, "count": len(results)}
        return self._advance(fr, step)

    def _providers(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.settings.load().get("providers") or {}
        patch: dict[str, Any] = {}
        fingerprints: dict[str, str] = {}
        for name, cfg in (payload or {}).items():
            if not isinstance(cfg, dict):
                continue
            secret = cfg.get("api_key")
            if secret:
                if self.secret_store is None:
                    raise WizardError("no_secret_store", "مخزن المفاتيح (DPAPI) مش متاح — مش هنحفظ المفتاح في ملف عادي.",
                                      "The DPAPI key store is unavailable; the key is not saved in plain settings.")
                fingerprints[name] = self.secret_store.put(f"provider:{name}", secret)
            clean = {k: v for k, v in cfg.items() if k in PROVIDER_FIELDS}
            if name in current or clean:
                patch[name] = clean
        if patch:
            self.settings.update({"providers": patch})
        return {"configured": sorted(patch), "key_fingerprints": fingerprints}

    def skip(self, step: str) -> dict[str, Any]:
        fr = self._require_current(step)
        if step not in SKIPPABLE:
            raise WizardError("not_skippable", "الخطوة دي مينفعش تتخطّى.", "This step cannot be skipped.")
        return self._advance(fr, step, skipped=True)

    def back(self) -> dict[str, Any]:
        fr = self.state()
        if not fr["completed"]:
            return fr
        last = fr["completed"][-1]
        fr["completed"] = fr["completed"][:-1]
        fr["skipped"] = [s for s in fr["skipped"] if s != last]
        fr["step"], fr["done"] = last, False
        return self._save(fr)

    def reset(self) -> dict[str, Any]:
        return self._save({"step": STEPS[0], "completed": [], "skipped": [], "done": False, "finished_at": None,
                           "workspace_set": None, "providers": None, "discovery": None, "doctor": None})


def fingerprint(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()[:8]
