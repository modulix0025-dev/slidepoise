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
PAGE_KINDS = ("cover", "scene", "dedication", "back", "certificate", "about_me", "qr_back", "coloring", "bilingual",
              "class_page")


@dataclass
class Page:
    kind: str
    texts: dict[str, str] = field(default_factory=dict)  # variant -> text with {NAME} tokens
    scene: str = ""            # what the per-order scene shows (for the ComfyUI workflow / art brief)
    figure: bool = True        # does the child's figure appear on this page
    extra_characters: list[str] = field(default_factory=list)
    title: dict[str, str] = field(default_factory=dict)  # optional page title per variant
    # landscape storybook/overlay pages (fractions of the trimmed page; defaults per layout when omitted)
    text_box: list[float] | None = None   # [x, y, w, h] of the story text
    name_box: list[float] | None = None   # [x, y, w, h] of the big «name art» (storybook); None = layout default
    name_art: bool | None = None          # show the child's name as art on this page (default: cover + scenes)
    rotate: float | None = None           # degrees, story text («مايل سنة»)
    name_rotate: float | None = None      # degrees, name art
    name_style: str | None = None         # gold | ice | pink
    text_side: str | None = None          # overlay: right | left (dark gradient under the text)
    ink: bool | None = None               # dark text on a light area of the art instead of white text
    art: str = ""                         # sample scene art (workspace sha or file path): contrast check + preview

    def validate(self, variants: tuple[str, ...]) -> list[str]:
        problems = []
        if self.kind not in PAGE_KINDS:
            problems.append(f"unknown page kind {self.kind!r}")
        if self.kind in {"scene", "dedication", "cover", "about_me", "certificate", "qr_back", "coloring", "class_page"}:
            for variant in variants:
                if not self.texts.get(variant, "").strip():
                    problems.append(f"{self.kind} page has no text for {variant}")
        if self.kind == "certificate":
            for language in {v.split("_")[0] for v in variants}:
                if not self.title.get(language):
                    problems.append(f"certificate needs a title in {language}")
        if self.kind == "bilingual":
            for gender in {v.split("_")[1] for v in variants}:
                if not (self.texts.get(f"ar_{gender}") and self.texts.get(f"en_{gender}")):
                    problems.append(f"bilingual page needs Arabic and English text for {gender}")
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
    page: str = "portrait"     # portrait (A4/A5) | landscape_169 (297×167.06 mm + bleed, and its A5 half)
    layout: str = "classic"    # classic | overlay (full scene, gradient under the text) | storybook (scene + name art)

    def validate(self) -> list[str]:
        problems = []
        if not STORY_KEY.match(self.key):
            problems.append("story key must be ascii lowercase (e.g. moon_trip)")
        if self.page not in ("portrait", "landscape_169"):
            problems.append("page must be portrait or landscape_169")
        if self.layout not in ("classic", "overlay", "storybook"):
            problems.append("layout must be classic, overlay or storybook")
        for number, page in enumerate(self.pages, 1):
            for name in ("text_box", "name_box"):
                box = getattr(page, name)
                if box is not None and (len(box) != 4 or not all(0 <= v <= 1 for v in box) or box[2] <= 0
                                        or box[3] <= 0 or box[0] + box[2] > 1.0001 or box[1] + box[3] > 1.0001):
                    problems.append(f"page {number}: {name} must be [x, y, w, h] fractions of the page")
            if page.name_style not in (None, "gold", "ice", "pink"):
                problems.append(f"page {number}: name_style must be gold, ice or pink")
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
