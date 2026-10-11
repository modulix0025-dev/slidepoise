"""Pin LibreOffice for the Full installer from The Document Foundation's own published hash.

    python installer/pin_libreoffice.py [--branch still|fresh] [--write] [--save PATH]

1. reads the official ``stable/`` listing on download.documentfoundation.org and picks the
   newest patch of the chosen series ("still" = the mature series TDF recommends for
   conservative deployments; "fresh" = the newest features);
2. takes the sha256 TDF publishes next to the MSI (``<msi>.sha256``, else the hash printed on
   ``<msi>.mirrorlist``) — never a hash computed from the bytes alone;
3. downloads the MSI and refuses unless its sha256 equals the published one;
4. prints the pin as JSON; ``--write`` stores it in installer/downloads.json, ``--save`` keeps
   the verified MSI (the payload fetcher then re-verifies it instead of downloading again).

Runs in CI (the release workflow's offline-payload job) where TDF is reachable. The pin it
prints is meant to be committed so that tag builds stay strict.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as _dt
import hashlib
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://download.documentfoundation.org/libreoffice/stable/"
UA = {"User-Agent": "ModuleX-MagazineStudio-Release"}


def _get(url: str, timeout: float = 60.0) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as response:
        return response.read()


def versions(listing: str) -> list[tuple[int, ...]]:
    found = {tuple(int(p) for p in m) for m in re.findall(r'href="(\d+)\.(\d+)\.(\d+)/"', listing)}
    return sorted(found)


def choose(found: list[tuple[int, ...]], branch: str) -> str:
    if not found:
        raise SystemExit("no versions in the TDF stable/ listing")
    series = sorted({v[:2] for v in found})
    pick = series[0] if branch == "still" and len(series) > 1 else series[-1]
    return ".".join(str(p) for p in max(v for v in found if v[:2] == pick))


def msi_url(version: str) -> str:
    return f"{BASE}{version}/win/x86_64/LibreOffice_{version}_Win_x86-64.msi"


def published_sha256(url: str, get=_get) -> tuple[str, str]:
    """(sha256, where it came from) as published by TDF for ``url``."""
    for suffix in (".sha256", ".mirrorlist"):
        try:
            text = get(url + suffix).decode("utf-8", "replace")
        except OSError:
            continue
        if suffix == ".sha256":
            match = re.match(r"\s*([0-9a-fA-F]{64})\b", text)
        else:
            match = re.search(r"SHA-?256.{0,200}?\b([0-9a-fA-F]{64})\b", text, re.DOTALL)
        if match:
            return match.group(1).lower(), url + suffix
    raise SystemExit(f"TDF publishes no sha256 for {url}; refusing to pin from computed bytes alone")


def download_verified(url: str, expected: str, dest: Path | None) -> int:
    digest, size = hashlib.sha256(), 0
    tmp = dest.with_name(dest.name + ".part") if dest else None
    if tmp:
        tmp.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as response, \
            (open(tmp, "wb") if tmp else contextlib.nullcontext()) as handle:
        while True:
            block = response.read(1 << 20)
            if not block:
                break
            digest.update(block)
            size += len(block)
            if handle:
                handle.write(block)
    if digest.hexdigest() != expected:
        if tmp:
            tmp.unlink(missing_ok=True)
        raise SystemExit(f"sha256 mismatch: TDF published {expected}, downloaded {digest.hexdigest()}")
    if tmp:
        tmp.replace(dest)
    return size


def write_pin(pin: dict, manifest_path: Path) -> None:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = data["entries"]["libreoffice_msi"]
    entry.update({"version": pin["version"], "url": pin["url"], "sha256": pin["sha256"], "size": pin["size"],
                  "pinned_from": f"{pin['hash_source']} (retrieved {pin['retrieved']})"})
    manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--branch", choices=["still", "fresh"], default="still")
    parser.add_argument("--write", action="store_true", help="store the pin in installer/downloads.json")
    parser.add_argument("--manifest", default=str(ROOT / "installer" / "downloads.json"))
    parser.add_argument("--save", help="keep the verified MSI at this path")
    args = parser.parse_args(argv)
    version = choose(versions(_get(BASE).decode("utf-8", "replace")), args.branch)
    url = msi_url(version)
    sha, source = published_sha256(url)
    size = download_verified(url, sha, Path(args.save) if args.save else None)
    pin = {"version": version, "url": url, "sha256": sha, "size": size, "hash_source": source,
           "retrieved": _dt.date.today().isoformat(), "branch": args.branch}
    print("LIBREOFFICE_PIN " + json.dumps(pin))
    if args.write:
        write_pin(pin, Path(args.manifest))
    return 0


if __name__ == "__main__":
    sys.exit(main())
