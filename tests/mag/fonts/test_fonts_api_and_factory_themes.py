"""Fonts area mounts in the Studio, and factory themes take their fonts from certified type themes."""
from __future__ import annotations

import json
import warnings

import pytest

from mxstudio.factory.products import theme_from_type_theme
from mxstudio.fonts.paths import QA_JSON
from mxstudio.fonts.themes import load_themes


def test_every_type_theme_becomes_a_factory_theme_with_certified_fonts():
    qa = {f["family"]: f for f in json.loads(QA_JSON.read_text(encoding="utf-8"))["families"]}
    for entry in load_themes()["themes"]:
        for language in ("ar", "en"):
            theme = theme_from_type_theme(entry["id"], {"text": "#222222", "panel": "#FFFFFF", "outline": "#333333"},
                                          language=language)
            for family in theme.type_theme.values():
                assert qa[family]["status"] == "certified_print", (entry["id"], family)
            assert theme.layout_theme()["fonts"]["title"] == theme.type_theme["title"]


def test_unknown_type_theme_is_refused():
    with pytest.raises(ValueError):
        theme_from_type_theme("no_such_theme", {})


def test_fonts_tools_mount_and_answer(tmp_path, monkeypatch):
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    from mxstudio.app.server import create_app
    from mxstudio.app.state import AppState
    monkeypatch.setenv("MXS_WORKSPACE", str(tmp_path / "ws"))
    state = AppState.create(tmp_path / "home")
    create_app(state)
    names = {s["name"] for s in state.tools.specs()}
    assert {"fonts.list_themes", "fonts.role_defaults", "fonts.check_allowed"} <= names
    allowed = state.tools.call("fonts.check_allowed", {"family": "Lemonada", "role": "handwriting-dedication",
                                                       "script": "ar"}, actor="agent")
    assert allowed["ok"] and allowed["result"]["allowed"] is True
    refused = state.tools.call("fonts.check_allowed", {"family": "No Such Font", "role": "body", "script": "ar"},
                               actor="agent")
    assert refused["ok"] and refused["result"]["findings"] == ["font_not_in_qa"]
