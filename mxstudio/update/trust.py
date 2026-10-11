"""What the app trusts for updates: embedded public keys, the manifest URL, allowed hosts.

Rule: ``trust.json`` ships inside the app (PyInstaller datas). The repository copy holds
no key until the operator runs ``keygen`` and commits the public half, or the release
workflow embeds it from the repository *variable* ``MXS_UPDATE_PUBLIC_KEY`` at build time
(``python -m mxstudio.update embed``). The private key is never involved here.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .manifest import DEFAULT_ALLOWED_HOSTS

TRUST_FILE = Path(__file__).with_name("trust.json")


@dataclass
class Trust:
    public_keys: dict[str, str] = field(default_factory=dict)
    manifest_url: str = ""
    allowed_hosts: tuple[str, ...] = DEFAULT_ALLOWED_HOSTS
    release_repo: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"public_keys": dict(self.public_keys), "manifest_url": self.manifest_url,
                "allowed_hosts": list(self.allowed_hosts), "release_repo": self.release_repo}


def _candidates() -> list[Path]:
    out = [TRUST_FILE]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        out.insert(0, Path(meipass) / "mxstudio" / "update" / "trust.json")
    return out


def load(path: Path | None = None) -> Trust:
    for candidate in ([path] if path else _candidates()):
        if candidate and candidate.is_file():
            data = json.loads(candidate.read_text(encoding="utf-8"))
            return Trust(public_keys=dict(data.get("public_keys") or {}),
                         manifest_url=str(data.get("manifest_url") or ""),
                         allowed_hosts=tuple(data.get("allowed_hosts") or DEFAULT_ALLOWED_HOSTS),
                         release_repo=str(data.get("release_repo") or ""))
    return Trust()


def save(trust: Trust, path: Path | None = None) -> Path:
    target = path or TRUST_FILE
    target.write_text(json.dumps(trust.to_dict(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return target


def stable_manifest_url(repo: str) -> str:
    return f"https://github.com/{repo}/releases/latest/download/latest.json"
