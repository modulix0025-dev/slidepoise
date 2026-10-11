"""Story Desk: one story, four hand-written payloads (ولد/بنت × عربي/English).

Gendered Arabic is written per variant (verbs, pronouns, adjectives) by the
author, never derived by find/replace. The hero's sample name is a token run.
The optional تشكيل assistant only *proposes* vowelisation; the operator accepts
word by word, and the name token is never vowelised.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from mxstudio.factory.payloads import VARIANTS

STORY_KEY = re.compile(r"^[a-z][a-z0-9_]{2,40}$")
NAME_TOKEN = "{NAME}"
DEFAULT_BASE_NAMES = {"ar_boy": "إياد", "ar_girl": "جيداء", "en_boy": "Eyad", "en_girl": "Gaidaa"}
PAGE_KINDS = ("cover", "scene", "dedication", "back", "certificate", "about_me", "qr_back", "coloring", "bilingual")


@dataclass
class Page:
    kind: str
    texts: dict[str, str] = field(default_factory=dict)  # variant -> text with {NAME} tokens
    scene: str = ""            # what the per-order scene shows (for the ComfyUI workflow / art brief)
    figure: bool = True        # does the child's figure appear on this page
    extra_characters: list[str] = field(default_factory=list)
    title: dict[str, str] = field(default_factory=dict)  # optional page title per variant

    def validate(self, variants: tuple[str, ...]) -> list[str]:
        problems = []
        if self.kind not in PAGE_KINDS:
            problems.append(f"unknown page kind {self.kind!r}")
        if self.kind in {"scene", "dedication", "cover"}:
            for variant in variants:
                if not self.texts.get(variant, "").strip():
                    problems.append(f"{self.kind} page has no text for {variant}")
        if self.kind == "dedication":
            for variant in variants:
                if NAME_TOKEN not in self.texts.get(variant, ""):
                    problems.append(f"dedication for {variant} does not name the child")
        return problems


@dataclass
class Story:
    key: str
    title: dict[str, str]
    pages: list[Page]
    base_names: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_BASE_NAMES))
    variants: tuple[str, ...] = VARIANTS
    figure_prompt_male: str = ""
    figure_prompt_female: str = ""
    characters_count: int = 1
    extra_characters: list[str] = field(default_factory=list)
    theme: str = "مرح كلاسيكي"

    def validate(self) -> list[str]:
        problems = []
        if not STORY_KEY.match(self.key):
            problems.append("story key must be ascii lowercase (e.g. moon_trip)")
        for variant in self.variants:
            if variant not in VARIANTS:
                problems.append(f"unknown variant {variant}")
            if not self.title.get(variant.split("_")[0]):
                problems.append(f"missing title for {variant.split('_')[0]}")
            if not self.base_names.get(variant):
                problems.append(f"missing base name for {variant}")
        if not any(page.kind == "scene" for page in self.pages):
            problems.append("a story needs at least one scene page")
        for number, page in enumerate(self.pages, 1):
            problems += [f"page {number}: {p}" for p in page.validate(self.variants)]
        boy = " ".join(p.texts.get("ar_boy", "") for p in self.pages)
        girl = " ".join(p.texts.get("ar_girl", "") for p in self.pages)
        if "ar_boy" in self.variants and "ar_girl" in self.variants and boy and boy == girl:
            problems.append("the Arabic girl text is identical to the boy text — write the girl's version")
        return problems

    def as_dict(self) -> dict:
        data = asdict(self)
        data["variants"] = list(self.variants)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Story":
        pages = [Page(**page) for page in data["pages"]]
        rest = {k: v for k, v in data.items() if k != "pages"}
        rest["variants"] = tuple(rest.get("variants", VARIANTS))
        return cls(pages=pages, **rest)


def runs_for(text: str, base_name: str) -> list[dict]:
    """Split text on {NAME} so the base name is one whole run with role child_name."""
    runs: list[dict] = []
    parts = text.split(NAME_TOKEN)
    for index, part in enumerate(parts):
        if part:
            runs.append({"text": part})
        if index < len(parts) - 1:
            runs.append({"text": base_name, "role": "child_name"})
    return runs


def apply_tashkeel(text: str, proposals: dict[str, str], accepted: set[str]) -> str:
    """Replace only the accepted words with their vowelised proposal; {NAME} is never touched."""
    out = []
    for token in re.split(r"(\s+)", text):
        if NAME_TOKEN in token or token.isspace() or not token:
            out.append(token)
            continue
        out.append(proposals[token] if token in accepted and token in proposals else token)
    return "".join(out)
