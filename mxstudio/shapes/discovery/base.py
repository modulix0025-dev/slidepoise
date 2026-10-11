"""Licence gate, provenance and a polite HTTP client for official asset APIs.

Rules enforced here
* Print allowlist comes from ``catalog/licence_policy.json`` (CC0/PD, MIT, ISC, BSD-2/3,
  Apache-2.0, OFL-1.1, CC-BY-4.0 + credits page). Everything else is refused for print:
  CC BY-SA, any NC/ND, GPL/MPL, "personal use", unknown, and the operator-pending ids
  (Unlicense, CC-BY-3.0) until the operator decides.
* Only the official APIs in ``catalog/shapes/sources.json`` are queried; general-web results are
  ``inspiration`` only and can never be imported.
* Fetched text (titles, authors, tags) is *data*: HTML stripped, control/bidi-override characters
  removed, length-capped, and never interpolated into instructions.
* Nothing is imported without an operator's approval; every import records provenance
  (source URL, author, licence + URL, retrieved_at, sha256).
"""
from __future__ import annotations

import hashlib
import html
import ipaddress
import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[3]
POLICY_PATH = ROOT / "catalog" / "licence_policy.json"
SOURCES_PATH = ROOT / "catalog" / "shapes" / "sources.json"
ORIGINAL_WORK = "LicenseRef-ModuleX-Original"

PRINT_OK = "print_ok"
PRINT_OK_WITH_CREDITS = "print_ok_with_credits"
PENDING_OPERATOR = "pending_operator"
REFUSED = "refused"


class DiscoveryError(RuntimeError):
    code = "discovery_error"


class LicenceRefused(DiscoveryError):
    code = "licence_refused"


class InspirationOnly(DiscoveryError):
    code = "inspiration_only"


class ApprovalRequired(DiscoveryError):
    code = "approval_required"


class SourceDisabled(DiscoveryError):
    code = "source_disabled"


@lru_cache(maxsize=1)
def policy() -> dict:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def sources() -> dict:
    return json.loads(SOURCES_PATH.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ text as data
_TAG = re.compile(r"<[^>]{0,2000}>")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​-‏‪-‮⁠-⁩﻿]")


def clean_text(value, limit: int = 200) -> str:
    """Fetched text -> inert, single-line data (HTML stripped, controls removed, capped)."""
    if value is None:
        return ""
    text = str(value)
    text = _TAG.sub(" ", text)
    text = html.unescape(text)
    text = _TAG.sub(" ", text)
    text = _CTRL.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


# ------------------------------------------------------------------ licences
_SIMPLE = {
    "cc0": "CC0-1.0", "cc0-1.0": "CC0-1.0", "cc0 1.0": "CC0-1.0", "cc zero": "CC0-1.0",
    "creative commons zero": "CC0-1.0", "cc0 1.0 universal": "CC0-1.0",
    "pdm": "PDM", "pdm-1.0": "PDM", "pd": "PDM", "public domain": "PDM", "public-domain": "PDM",
    "public domain mark": "PDM",
    "mit": "MIT", "mit license": "MIT", "isc": "ISC", "isc license": "ISC",
    "bsd-2-clause": "BSD-2-Clause", "bsd 2-clause": "BSD-2-Clause", "bsd-3-clause": "BSD-3-Clause",
    "bsd 3-clause": "BSD-3-Clause",
    "apache-2.0": "Apache-2.0", "apache 2.0": "Apache-2.0", "apache license 2.0": "Apache-2.0",
    "apache license, version 2.0": "Apache-2.0",
    "ofl-1.1": "OFL-1.1", "ofl": "OFL-1.1", "sil open font license 1.1": "OFL-1.1",
    "unlicense": "Unlicense", "the unlicense": "Unlicense",
    "mpl-2.0": "MPL-2.0", "gpl-2.0-only": "GPL-2.0-only", "gpl-2.0-or-later": "GPL-2.0-or-later",
    "gpl-3.0": "GPL-3.0", "gpl-3.0-only": "GPL-3.0", "gpl-3.0-or-later": "GPL-3.0-or-later",
    ORIGINAL_WORK.lower(): ORIGINAL_WORK,
}
_PERSONAL = re.compile(r"personal[\s_-]*use|non[\s_-]*commercial[\s_-]*use[\s_-]*only|free for personal", re.I)
_CC = re.compile(r"^(?:cc[\s_-]*)?(by(?:[\s_-]*(?:nc|nd|sa))*)(?:[\s_-]*v?(\d(?:\.\d)?))?$", re.I)


def normalise_licence(raw: str | None, version: str | None = None) -> str:
    """Map API licence spellings (SPDX, Openverse codes, Commons short names) to one id.

    Unknown spellings map to ``UNKNOWN`` (refused), never to the closest guess.
    """
    if not raw:
        return "UNKNOWN"
    text = clean_text(raw, 120)
    low = text.lower().strip()
    if _PERSONAL.search(low):
        return "personal-use"
    if low in _SIMPLE:
        return _SIMPLE[low]
    low = low.replace("creative commons", "cc").replace("attribution", "by").replace("sharealike", "sa")
    low = low.replace("noncommercial", "nc").replace("noderivatives", "nd").replace("noderivs", "nd")
    low = re.sub(r"\s*international\s*$|\s*unported\s*$|\s*generic\s*$", "", low).strip()
    if low.startswith("cc-") or low.startswith("cc ") or low.startswith("by"):
        m = _CC.match(low.replace("cc-", "cc ").strip())
        if m:
            parts = re.split(r"[\s_-]+", m.group(1).lower())
            ver = m.group(2) or (str(version).strip() if version else "")
            if not re.fullmatch(r"\d\.\d", ver or ""):
                if ver and re.fullmatch(r"\d", ver):
                    ver = ver + ".0"
                else:
                    return "UNKNOWN" if parts == ["by"] else "CC-" + "-".join(p.upper() for p in parts) + "-UNKNOWN"
            return "CC-" + "-".join(p.upper() for p in parts) + "-" + ver
    return "UNKNOWN"


@dataclass(frozen=True)
class LicenceDecision:
    licence: str
    status: str
    credits_required: bool
    reason_ar: str
    reason_en: str

    @property
    def printable(self) -> bool:
        return self.status in (PRINT_OK, PRINT_OK_WITH_CREDITS)

    def to_json(self) -> dict:
        return asdict(self) | {"printable": self.printable}


def licence_gate(licence: str, *, attribution_required: bool = False) -> LicenceDecision:
    """Print decision for a normalised licence id (see module rules)."""
    pol = policy()
    if licence == ORIGINAL_WORK:
        return LicenceDecision(licence, PRINT_OK, False, "تصميم أصلي من الاستوديو", "original Studio work")
    if licence in pol["print_asset_allowlist"]:
        credits = licence in pol["print_asset_requires_credits"] or attribution_required
        return LicenceDecision(licence, PRINT_OK_WITH_CREDITS if credits else PRINT_OK, credits,
                               "مسموح للطباعة" + (" مع صفحة اعتمادات" if credits else ""),
                               "allowed for print" + (" with a credits page entry" if credits else ""))
    if licence in pol.get("print_asset_pending_operator", []):
        return LicenceDecision(licence, PENDING_OPERATOR, False, "مستني قرار المشغّل؛ مرفوض للطباعة لحد ما يقرر",
                               "awaiting the operator's decision; refused for print until then")
    if "-NC" in licence or "-ND" in licence:
        return LicenceDecision(licence, REFUSED, False, "رخصة غير تجارية أو بدون اشتقاق: مرفوضة للطباعة",
                               "non-commercial / no-derivatives licence: refused for print")
    if "-SA" in licence:
        return LicenceDecision(licence, REFUSED, False, "رخصة المشاركة بالمثل (SA): مرفوضة للطباعة",
                               "share-alike licence: refused for print")
    if licence == "personal-use":
        return LicenceDecision(licence, REFUSED, False, "للاستخدام الشخصي بس: مرفوضة", "personal use only: refused")
    if licence == "UNKNOWN" or licence.endswith("-UNKNOWN"):
        return LicenceDecision(licence, REFUSED, False, "الرخصة مش معروفة: مرفوضة", "unknown licence: refused")
    return LicenceDecision(licence, REFUSED, False, "الرخصة مش في قائمة الطباعة المسموحة: مرفوضة",
                           "licence is not on the print allowlist: refused")


# ------------------------------------------------------------------ provenance
REQUIRED_PROVENANCE = ("source", "source_url", "author", "licence", "licence_url", "retrieved_at", "sha256")


@dataclass
class Provenance:
    source: str
    source_url: str
    author: str
    licence: str
    licence_url: str
    retrieved_at: str
    sha256: str
    title: str = ""
    asset_url: str = ""
    source_id: str = ""
    author_url: str = ""
    licence_raw: str = ""
    attribution: str = ""
    credits_required: bool = False
    approved_by: str = ""
    extra: dict = field(default_factory=dict)

    def missing(self) -> list[str]:
        out = [k for k in REQUIRED_PROVENANCE if not str(getattr(self, k) or "").strip()]
        if self.licence == ORIGINAL_WORK:
            out = [k for k in out if k not in ("licence_url",)]
        return out

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict) -> "Provenance":
        known = {k: data[k] for k in cls.__dataclass_fields__ if k in data}
        return cls(**known)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ------------------------------------------------------------------ candidates
@dataclass
class Candidate:
    source: str
    source_id: str
    title: str
    kind: str  # "importable" | "inspiration"
    media: str  # "svg" | "raster"
    asset_url: str
    landing_url: str
    licence: str
    licence_raw: str
    licence_url: str
    author: str
    author_url: str
    decision: LicenceDecision
    attribution: str = ""
    tags: list[str] = field(default_factory=list)
    preview_url: str = ""
    findings: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        d = asdict(self)
        d["decision"] = self.decision.to_json()
        return d


def inspiration_candidate(url: str, title: str = "", note: str = "") -> Candidate:
    """A general-web find: shown to the generator as inspiration, never importable."""
    return Candidate(source="general_web", source_id=url, title=clean_text(title), kind="inspiration", media="none",
                     asset_url="", landing_url=url, licence="UNKNOWN", licence_raw="", licence_url="", author="",
                     author_url="", decision=licence_gate("UNKNOWN"), findings=["general_web_inspiration_only"],
                     attribution=clean_text(note))


# ------------------------------------------------------------------ HTTP
class PoliteClient:
    """Cached, rate-limited, host-allow-listed GET client (``httpx.Client`` injected).

    Tests hand in an ``httpx.Client(transport=MockTransport(cassette))``; no test touches
    the network.
    """

    def __init__(self, client=None, *, cache_dir: Path | None = None, allowed_hosts: set[str] | None = None,
                 user_agent: str = "ModuleX-Magazine-Studio/0.2 (shape discovery; operator workstation)",
                 min_interval: float = 0.5, max_retries: int = 3, max_bytes: int = 5_000_000,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic) -> None:
        if client is None:
            import httpx

            client = httpx.Client(timeout=20.0, follow_redirects=False)
        self.client = client
        self.cache_dir = cache_dir
        self.allowed_hosts = allowed_hosts or set(sources().get("api_hosts", []))
        self.user_agent = user_agent
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.max_bytes = max_bytes
        self.sleep = sleep
        self.clock = clock
        self._last: dict[str, float] = {}
        self.requests: list[str] = []

    @staticmethod
    def url_with(url: str, params: dict | None) -> str:
        if not params:
            return url
        return url + ("&" if "?" in url else "?") + urlencode(sorted((k, str(v)) for k, v in params.items()))

    def _check_url(self, url: str, asset: bool) -> None:
        parts = urlsplit(url)
        if parts.scheme != "https":
            raise DiscoveryError(f"refused non-https URL: {url[:120]}")
        host = (parts.hostname or "").lower()
        try:
            ip = ipaddress.ip_address(host)
            raise DiscoveryError(f"refused IP-literal host {ip}")
        except ValueError:
            pass
        if host in ("localhost",) or host.endswith(".local") or host.endswith(".internal"):
            raise DiscoveryError(f"refused local host {host}")
        if not asset and host not in self.allowed_hosts:
            raise DiscoveryError(f"host {host} is not an allow-listed official API")
        if asset and host not in self.allowed_hosts and host not in set(sources().get("asset_hosts", [])):
            raise DiscoveryError(f"asset host {host} is not allow-listed")

    def get(self, url: str, params: dict | None = None, *, asset: bool = False) -> tuple[bytes, str]:
        full = self.url_with(url, params)
        self._check_url(full, asset)
        key = sha256_hex(full.encode("utf-8"))
        if self.cache_dir:
            hit = self.cache_dir / f"{key}.bin"
            meta = self.cache_dir / f"{key}.json"
            if hit.is_file() and meta.is_file():
                return hit.read_bytes(), json.loads(meta.read_text(encoding="utf-8")).get("content_type", "")
        host = urlsplit(full).hostname or ""
        wait = self.min_interval - (self.clock() - self._last.get(host, -1e9))
        if wait > 0:
            self.sleep(wait)
        attempt = 0
        while True:
            attempt += 1
            self.requests.append(full)
            try:
                resp = self.client.get(full, headers={"User-Agent": self.user_agent, "Accept": "*/*"})
            except Exception as exc:  # httpx.HTTPError and transport failures -> one named error
                if isinstance(exc, AssertionError):  # test cassettes: an unrecorded request must fail loudly
                    raise
                raise DiscoveryError(f"network error from {host}: {type(exc).__name__}") from None
            self._last[host] = self.clock()
            if resp.status_code in (429, 502, 503, 504) and attempt <= self.max_retries:
                retry = resp.headers.get("Retry-After", "")
                delay = float(retry) if retry.replace(".", "", 1).isdigit() else 2.0 ** attempt
                self.sleep(min(delay, 30.0))
                continue
            if resp.status_code != 200:
                raise DiscoveryError(f"HTTP {resp.status_code} from {host}")
            data = resp.content
            if len(data) > self.max_bytes:
                raise DiscoveryError(f"response from {host} exceeds {self.max_bytes} bytes")
            ctype = resp.headers.get("Content-Type", "")
            if self.cache_dir:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                (self.cache_dir / f"{key}.bin").write_bytes(data)
                (self.cache_dir / f"{key}.json").write_text(json.dumps({"url": full, "content_type": ctype}),
                                                            encoding="utf-8")
            return data, ctype

    def get_json(self, url: str, params: dict | None = None):
        data, _ = self.get(url, params)
        try:
            return json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DiscoveryError(f"invalid JSON from {urlsplit(url).hostname}") from exc


# ------------------------------------------------------------------ import
@dataclass
class ImportedAsset:
    provenance: Provenance
    media: str
    svg: str | None = None
    raster: bytes | None = None
    findings: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return {"provenance": self.provenance.to_json(), "media": self.media, "svg": self.svg,
                "findings": self.findings, "raster_bytes": len(self.raster or b"")}


def import_candidate(candidate: Candidate, client: PoliteClient, *, approved_by: str,
                     retrieved_at: str | None = None) -> ImportedAsset:
    """Fetch an approved, print-licensed candidate; sanitise SVG; record provenance."""
    from ..sanitize import sanitize_svg

    if candidate.kind != "importable":
        raise InspirationOnly("general-web results are inspiration only; draw or generate an original instead")
    if not candidate.decision.printable:
        raise LicenceRefused(f"{candidate.licence}: {candidate.decision.reason_en}")
    if not (approved_by or "").strip():
        raise ApprovalRequired("an operator must approve before anything enters the library")
    data, ctype = client.get(candidate.asset_url, asset=True)
    findings: list[str] = []
    prov = Provenance(source=candidate.source, source_url=candidate.landing_url, author=candidate.author,
                      licence=candidate.licence, licence_url=candidate.licence_url,
                      retrieved_at=retrieved_at or now_iso(), sha256=sha256_hex(data), title=candidate.title,
                      asset_url=candidate.asset_url, source_id=candidate.source_id, author_url=candidate.author_url,
                      licence_raw=candidate.licence_raw, attribution=candidate.attribution,
                      credits_required=candidate.decision.credits_required, approved_by=approved_by.strip())
    missing = prov.missing()
    if missing:
        raise DiscoveryError(f"provenance incomplete: {missing}")
    if candidate.media == "svg" or "svg" in ctype:
        clean = sanitize_svg(data)
        findings.extend(f.code for f in clean.findings)
        return ImportedAsset(prov, "svg", svg=clean.svg, findings=sorted(set(findings)))
    if not (ctype.startswith("image/png") or ctype.startswith("image/jpeg")):
        raise DiscoveryError(f"unsupported media type {ctype!r}")
    return ImportedAsset(prov, "raster", raster=data, findings=findings)
