"""Bilingual error type shared by the updater, the payload downloader and their callers.

Rule: every refusal carries a stable machine code plus an Egyptian-Arabic and an English
sentence, so the UI never has to invent wording and logs never contain secrets.
"""
from __future__ import annotations


class UpdateError(Exception):
    """A refusal with a stable code and bilingual text."""

    def __init__(self, code: str, ar: str, en: str):
        super().__init__(f"{code}: {en}")
        self.code = code
        self.ar = ar
        self.en = en

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "ar": self.ar, "en": self.en}


class SignatureError(UpdateError):
    """The manifest is unsigned, signed by an unknown key, or was changed after signing."""


class ManifestError(UpdateError):
    """The manifest does not follow schema mxs-update/1 or breaks the URL/name policy."""


class IntegrityError(UpdateError):
    """A downloaded or kept file does not match its pinned sha256/size."""
