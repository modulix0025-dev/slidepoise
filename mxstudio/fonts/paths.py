"""Where the font catalog lives and which google/fonts commit it is pinned to."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]
CATALOG_DIR = ROOT / "catalog" / "fonts"
CATALOG_JSON = CATALOG_DIR / "catalog.json"
LEDGER_JSON = CATALOG_DIR / "font_license_ledger.json"
QA_JSON = CATALOG_DIR / "qa_status.json"
THEMES_JSON = CATALOG_DIR / "type_themes.json"
NAMES_JSON = CATALOG_DIR / "egyptian_names.json"
HARAKAT_JSON = CATALOG_DIR / "harakat_corpus.json"
OFFICE_BUILDS_JSON = CATALOG_DIR / "office_builds.json"
APPENDIX_TSV = ROOT / "docs" / "mag" / "catalog" / "fonts_appendix_f.tsv"
PHASE0_MEASURED = ROOT / "docs" / "mag" / "phase-0" / "evidence" / "font_catalog_measured.json"
LICENCE_POLICY = ROOT / "catalog" / "licence_policy.json"

PINNED_COMMIT = "bd8f81ddb5c74d5c8897b36ad88b440266245103"
REPO_URL = "https://github.com/google/fonts"
RAW_BASE = "https://raw.githubusercontent.com/google/fonts"


def raw_url(repo_dir: str, file: str, commit: str = PINNED_COMMIT) -> str:
    """Raw URL of one file at the pinned commit. Brackets (and commas) in variable-font names are percent-encoded."""
    parts = [quote(part, safe="") for part in f"{repo_dir}/{file}".split("/")]
    return f"{RAW_BASE}/{commit}/" + "/".join(parts)
