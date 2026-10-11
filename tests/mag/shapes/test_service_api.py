"""Service layer + HTTP routes (mounted the way mxstudio.app.features mounts an area)."""
from __future__ import annotations

import base64
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from mxstudio.shapes.service import ENDPOINTS, ServiceError, ShapeService


@pytest.fixture
def service(tmp_path, cassette_client):
    def factory():
        client, _ = cassette_client("iconify_search_cat.json")
        return client

    svc = ShapeService.at(tmp_path / "lib.sqlite3", client_factory=factory)
    yield svc
    svc.library.close()


def test_generate_and_preset_xml(service):
    out = service.generate({"name": "cloud_frame", "seed": 4, "params": {"bumps": 12}})
    assert out["layers"][0]["custgeom"].startswith("<a:custGeom") and "<svg" in out["svg_preview"]
    with pytest.raises(ServiceError) as exc:
        service.generate({"name": "nope"})
    assert exc.value.code == "UNKNOWN_GENERATOR"
    px = service.preset_xml({"prst": "cloudCallout", "adj": {"adj1": -30000}})
    assert px["adj"] == {"adj1": -30000, "adj2": 62500} and 'prst="cloudCallout"' in px["xml"]
    assert service.warp_xml({"prst": "textArchUp"})["adj"] == {"adj": 10800000}
    with pytest.raises(ServiceError):
        service.preset_xml({"prst": "cloud", "adj": {"zzz": 1}})


def test_canvas_commit_boolean_and_save(service):
    sq = [["M", 100, 100], ["L", 300, 100], ["L", 300, 300], ["L", 100, 300], ["Z"]]
    sq2 = [["M", 200, 200], ["L", 400, 200], ["L", 400, 400], ["L", 200, 400], ["Z"]]
    union = service.boolean({"op": "union", "subject": [{"commands": sq}, {"commands": sq2}]})
    assert len(union["geometry"]["parts"][0]["commands"]) == 9  # one 8-corner outline: M + 7 L + Z
    sub = service.boolean({"op": "subtract", "subject": [{"commands": sq}], "clip": [{"commands": sq2}]})
    assert sub["custgeom"].count("<a:lnTo>") == 5
    stroke = [["M", 50, 50], ["C", 100, 0, 200, 100, 250, 50]]
    res = service.canvas_commit({"width": 1000, "height": 700, "line": {"width_pt": 2, "dash": "dash"},
                                 "paths": [{"commands": sq, "closed": True, "fill": True},
                                           {"commands": stroke, "closed": False}]})
    assert res["bbox"] == pytest.approx([50, 35.63, 250, 264.37], abs=0.05)  # x, y, w, h and res["line"]["dash"] == "dash"
    assert 'fill="none"' in res["custgeom"]
    with pytest.raises(ServiceError) as exc:
        service.canvas_commit({"paths": [{"commands": sq}], "save": True})
    assert exc.value.code == "APPROVAL"
    saved = service.canvas_commit({"paths": [{"commands": sq, "fill": True}], "save": True, "author": "Mustafa",
                                   "name_ar": "مربع", "style": "flat"})
    found = service.library_search({"q": "مربع"})["assets"]
    assert [a["id"] for a in found] == [saved["asset_id"]] and found[0]["licence"] == "LicenseRef-ModuleX-Original"
    with pytest.raises(ServiceError):
        service.canvas_commit({"paths": [{"commands": [["L", 1, 1]]}]})


def test_vectorize_candidate_needs_approval(service):
    img = np.full((200, 200, 3), 255, np.uint8)
    cv2.circle(img, (100, 100), 70, (0, 0, 0), -1)
    b64 = base64.b64encode(cv2.imencode(".png", img)[1].tobytes()).decode()
    cand = service.vectorize({"image_base64": b64})
    assert cand["status"] == "awaiting_operator" and cand["iou_vs_input"] > 0.97
    with pytest.raises(ServiceError):
        service.approve_candidate({"candidate_id": cand["candidate_id"]})
    ok = service.approve_candidate({"candidate_id": cand["candidate_id"], "approved_by": "Mustafa", "name_en": "disc"})
    assert service.library_get({"id": ok["asset_id"]})["origin"] == "vectorized"
    with pytest.raises(ServiceError):
        service.vectorize({"image_base64": "%%%"})


def test_discover_prefers_library_then_imports_server_side_copy(service):
    out = service.discover({"query": "cat", "sources": ["iconify"]})
    assert out["from"] == "apis" and out["printable"] and out["refused"]
    keys = {c["source_id"]: c["key"] for c in out["printable"]}
    with pytest.raises(ServiceError) as exc:  # a tampered/unknown key is never imported
        service.import_asset({"key": "iconify:openmoji:cat-edited", "approved_by": "Mustafa"})
    assert exc.value.code == "UNKNOWN_RESULT"
    refused_key = [c["key"] for c in out["refused"] if c["source_id"] == "openmoji:cat"][0]
    with pytest.raises(ServiceError) as exc:
        service.import_asset({"key": refused_key, "approved_by": "Mustafa"})
    assert exc.value.code == "LICENCE_REFUSED"
    imported = service.import_asset({"key": keys["tabler:cat"], "approved_by": "Mustafa", "name_en": "cat outline"})
    assert imported["provenance"]["licence"] == "MIT" and "script" in imported["findings"]
    report = service.licence_report({"asset_ids": [imported["asset_id"]]})
    assert report["summary"]["total"] == 1 and not report["credits_page_required"]
    for i in range(3):
        service.canvas_commit({"paths": [{"commands": [["M", 0, 0], ["L", 9, 0], ["L", 9, 9], ["Z"]], "fill": True}],
                               "save": True, "author": "M", "name_en": f"cat sketch {i}"})
    assert service.discover({"query": "cat"})["from"] == "library"


def test_routes_mount_like_a_feature_area(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from mxstudio.agent.tools import ToolRegistry
    from mxstudio.config import Settings
    from mxstudio.shapes import api

    state = SimpleNamespace(home=tmp_path, settings=Settings(tmp_path / "settings.json"),
                            workspace=SimpleNamespace(root=tmp_path / "ws"), tools=ToolRegistry(tmp_path / "agent.sqlite3"))
    app = FastAPI()
    api.register(app, state)
    client = TestClient(app)
    paths = {r.path for r in app.routes}
    assert {p for _, p, _ in ENDPOINTS} <= paths
    assert client.get("/api/shapes/presets").json()["count"] == 187
    assert client.get("/api/shapes/warps").json()["count"] == 41
    r = client.post("/api/shapes/generate", json={"name": "blob", "seed": 1})
    assert r.status_code == 200 and r.json()["layers"]
    bad = client.post("/api/shapes/svg-to-custgeom", json={"svg": "<!DOCTYPE x><svg/>"})
    assert bad.status_code == 400 and bad.json()["code"] == "SVG_REJECTED"
    assert client.post("/api/shapes/ai/describe", json={"brief": "x"}).json()["code"] == "NO_PROVIDER"
    assert client.post("/api/shapes/generate", json={}).status_code == 400
    assert {"shapes.generate", "shapes.library_search", "shapes.licence_report"} <= {t["name"] for t in state.tools.specs()}
    app.state.mxs_shapes.library.close()
