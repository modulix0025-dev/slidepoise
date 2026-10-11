"""Update state machine: check → download (resume) → verify → stage → consent → apply on next
launch → applied | failed, plus one-click rollback.

States (``state.json`` under ``<app_home>/update``)::

    idle ──check──▶ available ──download──▶ downloaded ──stage──▶ staged
      ▲                                                            │ consent(yes)
      │                                                            ▼
    applied ◀──on_launch(version matches)── applying ◀──apply (next launch, consent given)
    failed  ◀──on_launch(version did not change)┘
    staged/idle/applied/failed ──rollback──▶ rolling_back ──on_launch──▶ rolled_back | failed

Rules:
* nothing is installed without the operator's consent; consent is cleared after every
  attempt so a failing installer never loops;
* every file is re-verified against its sha256 immediately before it is executed;
* a signed manifest is trusted only for versions strictly newer than the running one and
  not in ``skipped_versions`` (a rollback skips the version rolled back from);
* the previous installer and a version record are kept (``installers/`` + ``history.json``)
  so rollback works offline; older installers are pruned (current + previous kept).
"""
from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import manifest as mf
from . import signing, versioning
from . import trust as trust_mod
from .download import Progress, Transport, download, verify_file
from .errors import UpdateError

INSTALLER_PREFIX = "ModuleX-MagazineStudio-Setup-"
SILENT_ARGS = ["/S", "/RELAUNCH=1"]

Spawner = Callable[[list[str]], Any]
Fetcher = Callable[[str], bytes]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _default_home() -> Path:
    from mxstudio.config import app_home
    return app_home()


def _default_version() -> str:
    from mxstudio.config import APP_VERSION
    return APP_VERSION


def _default_fetch(url: str) -> bytes:
    import urllib.request
    request = urllib.request.Request(url, headers={"User-Agent": "ModuleX-MagazineStudio-Updater"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read(1_048_576)


def _default_spawn(cmd: list[str]) -> Any:
    from mxstudio.proc import spawn_hidden
    return spawn_hidden(cmd)


def installer_name(version: str) -> str:
    return f"{INSTALLER_PREFIX}{version}.exe"


class UpdateManager:
    """All update operations. Every collaborator is injectable so tests never use the network."""

    def __init__(self, home: Path | None = None, *, current_version: str | None = None,
                 trust: trust_mod.Trust | None = None, fetch: Fetcher | None = None,
                 transport: Transport | None = None, spawn: Spawner | None = None, digits: str = "arabic_indic"):
        self.root = Path(home or _default_home()) / "update"
        self.current = current_version or _default_version()
        self.trust = trust if trust is not None else trust_mod.load()
        self.fetch = fetch if fetch is not None else _default_fetch
        self.transport = transport
        self.spawn = spawn if spawn is not None else _default_spawn
        self.digits = digits
        self.downloads = self.root / "downloads"
        self.staged_dir = self.root / "staged"
        self.installers = self.root / "installers"   # NSIS copies $EXEPATH here too
        self.state_file = self.root / "state.json"
        self.history_file = self.root / "history.json"

    # ---- persistence ----
    def state(self) -> dict[str, Any]:
        if self.state_file.is_file():
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
        else:
            data = {}
        data.setdefault("state", "idle")
        data.setdefault("skipped_versions", [])
        data.setdefault("consent", False)
        data["current_version"] = self.current
        return data

    def _save(self, data: dict[str, Any]) -> dict[str, Any]:
        data["updated_at"] = _now()
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.state_file)
        return data

    def history(self) -> list[dict[str, Any]]:
        if self.history_file.is_file():
            return json.loads(self.history_file.read_text(encoding="utf-8"))
        return []

    def _save_history(self, records: list[dict[str, Any]]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.history_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.history_file)

    def _fail(self, data: dict[str, Any], err: UpdateError, state: str | None = None) -> dict[str, Any]:
        data["error"] = err.to_dict()
        if state:
            data["state"] = state
        return self._save(data)

    # ---- check ----
    def parse_manifest(self, raw: bytes) -> dict[str, Any]:
        try:
            manifest = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise mf.ManifestError("manifest_invalid", "ملف التحديث مش JSON سليم.", "latest.json is not valid JSON.") from exc
        signing.verify_manifest(manifest, self.trust.public_keys)  # signature first: never act on unsigned data
        return mf.validate(manifest, allowed_hosts=self.trust.allowed_hosts)

    def check(self, url: str | None = None) -> dict[str, Any]:
        data = self.state()
        url = url or self.trust.manifest_url
        data["last_check"] = _now()
        if data["state"] in ("applying", "rolling_back"):
            data["result"] = "busy"
            return self._save(data)
        if not url:
            return self._fail(data, UpdateError("no_manifest_url", "مفيش رابط تحديث مضبوط في النسخة دي.",
                                                "This build has no update URL configured."))
        try:
            manifest = self.parse_manifest(self.fetch(url))
        except UpdateError as err:
            return self._fail(data, err)
        except OSError as exc:
            return self._fail(data, UpdateError("offline", "مش قادرين نوصل لسيرفر التحديثات دلوقتي.",
                                                f"Could not reach the update server ({type(exc).__name__})."))
        data.pop("error", None)
        version = manifest["version"]
        if not versioning.is_newer(version, self.current) or version in data["skipped_versions"]:
            if data["state"] in ("available", "failed") or (data.get("staged") and not versioning.is_newer(
                    data["staged"]["version"], self.current)):
                data.update(state="idle", available=None, staged=None, consent=False)
            data["result"] = "up_to_date"
            return self._save(data)
        data["result"] = "update_available"
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "latest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
        staged = data.get("staged")
        if staged and staged.get("version") == version and data["state"] in ("staged", "downloaded"):
            return self._save(data)  # already have it
        asset = manifest["assets"]["online"]
        data.update(state="available", consent=False, staged=None,
                    available={"version": version, "asset": asset, "notes_ar": manifest.get("notes_ar", ""),
                               "notes_en": manifest.get("notes_en", ""), "released_at": manifest["released_at"]})
        return self._save(data)

    # ---- download / verify / stage ----
    def download(self, progress: Progress | None = None, cancel=None) -> dict[str, Any]:
        data = self.state()
        if data["state"] not in ("available", "downloading", "failed") or not data.get("available"):
            raise UpdateError("nothing_to_download", "مفيش تحديث متاح للتنزيل.", "No update is available to download.")
        asset = data["available"]["asset"]
        data["state"] = "downloading"
        self._save(data)

        last: dict[str, Any] = {"percent": -1}

        def _progress(line: dict) -> None:
            if progress:
                progress(line)
            if line.get("percent") != last["percent"]:  # the UI polls this file; write once per percent
                last["percent"] = line.get("percent")
                (self.root / "progress.json").write_text(json.dumps(line, ensure_ascii=False), encoding="utf-8")

        try:
            path = download(asset["url"], self.downloads / asset["name"], sha256=asset["sha256"], size=asset["size"],
                            transport=self.transport, progress=_progress, label_ar="التحديث",
                            label_en="the update", digits=self.digits, cancel=cancel)
        except UpdateError as err:
            resumable = err.code in ("cancelled", "interrupted", "offline")
            return self._fail(self.state() | {"state": "available" if resumable else "failed"}, err)
        data = self.state()
        data.pop("error", None)
        data.update(state="downloaded", downloaded={"path": str(path), "version": data["available"]["version"],
                                                    "sha256": asset["sha256"], "size": asset["size"]})
        return self._save(data)

    def verify(self) -> bool:
        data = self.state()
        item = data.get("staged") or data.get("downloaded")
        if not item:
            return False
        return verify_file(Path(item["path"]), item["sha256"], item.get("size"), raise_on_fail=False)

    def stage(self) -> dict[str, Any]:
        data = self.state()
        item = data.get("downloaded")
        if data["state"] != "downloaded" or not item:
            raise UpdateError("not_downloaded", "التحديث لسه ما نزلش.", "The update has not been downloaded.")
        src = Path(item["path"])
        verify_file(src, item["sha256"], item.get("size"))
        self.staged_dir.mkdir(parents=True, exist_ok=True)
        dest = self.staged_dir / src.name
        os.replace(src, dest)
        data.update(state="staged", consent=False, downloaded=None,
                    staged={"version": item["version"], "path": str(dest), "sha256": item["sha256"],
                            "size": item.get("size")})
        return self._save(data)

    def consent(self, yes: bool = True) -> dict[str, Any]:
        """Record the operator's answer; a failed attempt can be retried by agreeing again."""
        data = self.state()
        if data["state"] not in ("staged", "failed") or not data.get("staged"):
            raise UpdateError("not_staged", "مفيش تحديث جاهز.", "No update is staged.")
        data.update(state="staged", consent=bool(yes))
        return self._save(data)

    def pending(self) -> bool:
        data = self.state()
        return data["state"] == "staged" and bool(data.get("consent"))

    # ---- apply (next launch) ----
    def apply(self) -> bool:
        """Run the staged installer silently. Returns True when the caller must exit now."""
        data = self.state()
        staged = data.get("staged")
        if data["state"] != "staged" or not staged:
            return False
        if not data.get("consent"):
            raise UpdateError("no_consent", "محتاجين موافقتك الأول قبل ما نثبّت التحديث.",
                              "The operator has not agreed to install this update.")
        path = Path(staged["path"])
        if not verify_file(path, staged["sha256"], staged.get("size"), raise_on_fail=False):
            data.update(state="failed", consent=False, staged=None)
            path.unlink(missing_ok=True)
            self._fail(data, UpdateError("sha256_mismatch", "ملف التحديث اتغيّر بعد التنزيل واتمسح.",
                                         "The staged installer changed after download and was deleted."))
            return False
        self.installers.mkdir(parents=True, exist_ok=True)
        keep = self.installers / installer_name(staged["version"])
        if not keep.is_file() or not verify_file(keep, staged["sha256"], raise_on_fail=False):
            shutil.copy2(path, keep)
        self._remember(staged["version"], keep, staged["sha256"], source="update")
        data.update(state="applying", consent=False, from_version=self.current,
                    apply_attempts=int(data.get("apply_attempts") or 0) + 1, apply_started=_now())
        self._save(data)
        self.spawn([str(keep), *SILENT_ARGS])
        return True

    # ---- launch hook ----
    def on_launch(self) -> dict[str, Any]:
        """Call once at every app start: record the running version, settle apply/rollback."""
        self.record_running_version()
        data = self.state()
        if data["state"] == "applying":
            target = (data.get("staged") or {}).get("version")
            if target and target == self.current:
                Path(data["staged"]["path"]).unlink(missing_ok=True)
                data.update(state="applied", staged=None, available=None, apply_attempts=0, applied_at=_now())
                data.pop("error", None)
            else:
                # the verified file stays staged; consent was cleared, so it never loops
                return self._fail(data, UpdateError(
                    "apply_failed", "التحديث ما اتثبّتش — البرنامج لسه على النسخة القديمة. تقدر تجرّب تاني أو تتجاهله.",
                    "The update did not install; the app is still on the previous version."), state="failed")
        elif data["state"] == "rolling_back":
            target = (data.get("rollback") or {}).get("to")
            if target == self.current:
                data["state"] = "rolled_back"
                data.pop("error", None)
            else:
                return self._fail(data, UpdateError("rollback_failed", "الرجوع للنسخة السابقة ما نجحش.",
                                                    "Rollback did not complete."), state="failed")
        saved = self._save(data)
        self.prune()
        return saved

    def launch_hook(self) -> bool:
        """`open` calls this first; True means an installer was started and the app must exit."""
        self.on_launch()
        return self.apply() if self.pending() else False

    # ---- history / rollback ----
    def _remember(self, version: str, installer: Path | None, sha256: str | None, *, source: str) -> None:
        records = self.history()
        for record in records:
            if record["version"] == version:
                if installer and not record.get("installer"):
                    record.update(installer=installer.name, sha256=sha256, size=installer.stat().st_size)
                break
        else:
            records.append({"version": version, "installer": installer.name if installer else None,
                            "sha256": sha256, "size": installer.stat().st_size if installer else None,
                            "source": source, "first_seen": _now()})
        self._save_history(records)

    def record_running_version(self) -> None:
        kept = self.installers / installer_name(self.current)
        sha = mf.file_sha256(kept) if kept.is_file() else None
        known = {r["version"]: r for r in self.history()}
        if self.current in known and known[self.current].get("installer"):
            return
        self._remember(self.current, kept if kept.is_file() else None, sha, source="installer")

    def rollback_target(self) -> dict[str, Any] | None:
        records = self.history()
        index = next((i for i, r in enumerate(records) if r["version"] == self.current), len(records))
        for record in reversed(records[:index]):
            if record["version"] != self.current and record.get("installer") and \
                    (self.installers / record["installer"]).is_file():
                return record
        return None

    def rollback(self) -> bool:
        record = self.rollback_target()
        data = self.state()
        if not record:
            self._fail(data, UpdateError("no_previous", "مفيش نسخة سابقة محفوظة نرجع لها.",
                                         "No previous installer is kept, so rollback is not possible."))
            return False
        path = self.installers / record["installer"]
        if not record.get("sha256") or not verify_file(path, record["sha256"], record.get("size"), raise_on_fail=False):
            self._fail(data, UpdateError("sha256_mismatch", "مثبّت النسخة السابقة اتغيّر، فمش هنشغّله.",
                                         "The kept previous installer no longer matches its record; refused."))
            return False
        skipped = list(dict.fromkeys([*data["skipped_versions"], self.current]))
        data.update(state="rolling_back", consent=False, skipped_versions=skipped,
                    rollback={"from": self.current, "to": record["version"], "started": _now()})
        data.pop("error", None)
        self._save(data)
        self.spawn([str(path), *SILENT_ARGS])
        return True

    def prune(self) -> list[str]:
        """Keep installers for the running version and the rollback target only."""
        if not self.installers.is_dir():
            return []
        keep = {installer_name(self.current)}
        target = self.rollback_target()
        if target:
            keep.add(target["installer"])
        data = self.state()
        if data.get("state") in ("applying", "rolling_back"):
            return []
        removed = []
        for path in self.installers.glob(f"{INSTALLER_PREFIX}*.exe"):
            if path.name not in keep:
                path.unlink(missing_ok=True)
                removed.append(path.name)
        return removed
