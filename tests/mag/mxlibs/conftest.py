"""Fixtures for the mxlibs suites (builder in `_mxfixtures.py`)."""

from __future__ import annotations

from pathlib import Path

import pytest
from _mxfixtures import TAJAWAL, build_pdf


@pytest.fixture(scope="session")
def pdf_factory(tmp_path_factory):
    base = tmp_path_factory.mktemp("mx_pdfs")

    def _make(name: str, **kwargs) -> Path:
        return build_pdf(base / f"{name}.pdf", **kwargs)

    return _make


@pytest.fixture(scope="session")
def tajawal_path() -> Path:
    return TAJAWAL
