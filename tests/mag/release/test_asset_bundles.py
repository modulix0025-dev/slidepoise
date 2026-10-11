"""Full installer payload: font vault + shape packs assembled from per-file pins, LibreOffice pinned
from TDF's published sha256, offline shape search, fonts installed per user without admin."""
from __future__ import annotations

import importlib.util
import io
import json
import re
import tarfile
from pathlib import Path

import pytest

from mxstudio.update import assets, payloads
from mxstudio.update.assets import Input
from mxstudio.update.errors import IntegrityError, UpdateError

ROOT = Path(__file__).resolve().parents[3]


def _load(rel: str):
    spec = importlib.util.spec_from_file_location(Path(rel).stem, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tgz(prefix: str, *, licence: str = "MIT", version: str | None = None, icons: dict | None = None,
         extra: dict[str, bytes] | None = None) -> bytes:
    info = {"name": prefix.title(), "license": {"spdx": licence, "url": "https://example.org/licence"},
            "author": {"name": "Someone", "url": "https://example.org"}}
    if version:
        info["version"] = version
    body = {"prefix": prefix, "width": 24, "height": 24, "icons": icons or {
        "rocket": {"body": '<path fill="#c00" d="M2 2h20v20H2z"/>'},
        "moon-star": {"body": '<path d="M4 4h16v16H4z"/>', "width": 32},
        "stroke-only": {"body": '<path fill="none" stroke="currentColor" d="M2 2L22 22"/>'}},
        "aliases": {"rocket-launch": {"parent": "rocket"}, "rocket-flipped": {"parent": "rocket", "hFlip": True}}}
    members = {"package/icons.json": json.dumps(body).encode(), "package/info.json": json.dumps(info).encode(),
               "package/index.js": b"module.exports = {}", **(extra or {})}
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w:gz") as tar:
        for name, data in members.items():
            member = tarfile.TarInfo(name)
            member.size = len(data)
            tar.addfile(member, io.BytesIO(data))
    return raw.getvalue()


# ------------------------------------------------------------------ the real recipes
def test_font_vault_recipe_is_every_allowed_family_pinned_at_one_commit():
    catalog = json.loads((ROOT / "catalog/fonts/catalog.json").read_text(encoding="utf-8"))
    ledger = json.loads((ROOT / "catalog/fonts/font_license_ledger.json").read_text(encoding="utf-8"))
    allowed = {f["family"] for f in ledger["families"] if f["bundle_with_studio"]["allowed"]}
    items = assets.inputs("font_vault")
    fonts = [i for i in items if i.path.lower().endswith((".ttf", ".otf"))]
    licences = [i for i in items if not i.path.lower().endswith((".ttf", ".otf"))]
    assert len(fonts) == sum(len(f["files"]) for f in catalog["families"] if f["family"] in allowed)
    assert len(licences) == len(allowed)  # one licence file next to every family
    commit = catalog["source"]["commit"]
    for item in items:
        assert re.fullmatch(r"[0-9a-f]{64}", item.sha256), item.url
        assert item.url.startswith(f"https://raw.githubusercontent.com/google/fonts/{commit}/"), item.url
        assert ".." not in item.path and not item.path.startswith("/")
    assert {i.note for i in items} == allowed
    assert assets.version("font_vault") == "google/fonts@" + commit[:12]


def test_shape_packs_are_print_safe_filled_sets_pinned_twice():
    packs = json.loads((ROOT / "catalog/shapes/packs.json").read_text(encoding="utf-8"))
    policy = json.loads((ROOT / "catalog/licence_policy.json").read_text(encoding="utf-8"))
    sources = json.loads((ROOT / "catalog/shapes/sources.json").read_text(encoding="utf-8"))
    sets = assets.shape_sets()
    assert {s["prefix"] for s in sets} == {"noto", "fluent-emoji-flat", "twemoji", "ph", "ri"}
    for s in sets:
        assert s["licence"] in policy["print_asset_allowlist"]
        assert s["prefix"] not in sources["iconify_excluded_prefixes"]
        assert s["url"].startswith(f"https://registry.npmjs.org/@iconify-json/{s['prefix']}/-/")
        assert re.fullmatch(r"[0-9a-f]{64}", s["sha256"]) and s["npm_integrity"].startswith("sha512-")
    assert next(s for s in sets if s["prefix"] == "ri")["set_version"] == "4.8.0"  # Remix Icon cap (Apache-2.0)
    # stroke-only sets cannot become filled custom geometry: left out on purpose, with the reason written down
    assert set(packs["left_out"]) == {"lucide", "tabler"}


def test_policy_violations_in_packs_json_refuse_the_whole_recipe(tmp_path, monkeypatch):
    cat = tmp_path / "catalog"
    (cat / "shapes").mkdir(parents=True)
    for rel in ("licence_policy.json", "shapes/sources.json"):
        (cat / rel).write_text((ROOT / "catalog" / rel).read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(assets, "_catalog_dir", lambda: cat)
    base = {"name": "x", "url": "https://registry.npmjs.org/x.tgz", "sha256": "a" * 64}
    for bad in ({"prefix": "openmoji", "licence": "CC-BY-SA-4.0"}, {"prefix": "cbi", "licence": "MIT"},
                {"prefix": "ri", "licence": "Apache-2.0", "set_version": "4.9.0"},
                {"prefix": "foo", "licence": "CC-BY-NC-4.0"}):
        (cat / "shapes" / "packs.json").write_text(json.dumps({"retrieved_at": "x", "sets": [base | bad]}),
                                                   encoding="utf-8")
        with pytest.raises(UpdateError) as info:
            assets.shape_sets()
        assert info.value.code == "assets_licence", bad


# ------------------------------------------------------------------ building from pins
def test_font_vault_build_verifies_every_file_and_records_provenance(tmp_path, server, monkeypatch):
    font, lic = b"\x00\x01\x00\x00 fake ttf" * 50, b"SIL OPEN FONT LICENSE"
    items = [Input("https://raw.githubusercontent.com/f/a.ttf", server.add("https://raw.githubusercontent.com/f/a.ttf", font),
                   len(font), "ofl/amiri/Amiri-Regular.ttf", "OFL-1.1", "Amiri"),
             Input("https://raw.githubusercontent.com/f/OFL.txt", server.add("https://raw.githubusercontent.com/f/OFL.txt", lic),
                   None, "ofl/amiri/OFL.txt", "OFL-1.1", "Amiri")]
    monkeypatch.setattr(assets, "inputs", lambda name: items)
    target = tmp_path / "vault"
    summary = assets.build_tree("font_vault", target, cache_dir=tmp_path / "cache", transport=server)
    assert summary["files"] == 2 and (target / "ofl/amiri/Amiri-Regular.ttf").read_bytes() == font
    manifest = json.loads((target / "MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["files"][0]["source"] == items[0].url and manifest["files"][0]["family"] == "Amiri"
    assert assets.tree_status(target)["ok"] is True
    # a second build reuses the verified cache: no new requests
    before = len(server.requests)
    assets.build_tree("font_vault", tmp_path / "vault2", cache_dir=tmp_path / "cache", transport=server)
    assert len(server.requests) == before
    # tampering is reported, not hidden
    (target / "ofl/amiri/Amiri-Regular.ttf").write_bytes(b"changed")
    (target / "ofl/amiri/OFL.txt").unlink()
    status = assets.tree_status(target)
    assert status["ok"] is False and status["changed"] == ["ofl/amiri/Amiri-Regular.ttf"]
    assert status["missing"] == ["ofl/amiri/OFL.txt"]


def test_wrong_bytes_are_refused_and_nothing_lands(tmp_path, server, monkeypatch):
    url = "https://raw.githubusercontent.com/f/b.ttf"
    server.add(url, b"what the server sends")
    monkeypatch.setattr(assets, "inputs", lambda name: [Input(url, "0" * 64, None, "ofl/b/b.ttf", "OFL-1.1", "B")])
    with pytest.raises(IntegrityError):
        assets.build_tree("font_vault", tmp_path / "vault", cache_dir=tmp_path / "cache", transport=server)
    assert not (tmp_path / "vault" / "ofl").exists()


def test_unsafe_paths_never_leave_the_bundle(tmp_path, server, monkeypatch):
    url = "https://raw.githubusercontent.com/f/c.ttf"
    sha = server.add(url, b"x")
    for evil in ("../evil.ttf", "/abs.ttf", "C:/win.ttf", "a/../../b.ttf"):
        monkeypatch.setattr(assets, "inputs", lambda name, evil=evil: [Input(url, sha, None, evil, "OFL-1.1", "C")])
        with pytest.raises(UpdateError) as info:
            assets.build_tree("font_vault", tmp_path / "vault", cache_dir=tmp_path / "cache", transport=server)
        assert info.value.code == "unsafe_path"
    assert not (tmp_path / "evil.ttf").exists()


def test_shape_pack_build_takes_only_the_json_and_checks_the_licence_inside(tmp_path, server, monkeypatch):
    good = _tgz("noto", licence="Apache-2.0", extra={"package/../../escape.json": b"{}", "other/icons.json": b"{}"})
    url = "https://registry.npmjs.org/@iconify-json/noto/-/noto-1.0.0.tgz"
    monkeypatch.setattr(assets, "inputs", lambda name: [Input(url, server.add(url, good), None, "noto.tgz",
                                                              "Apache-2.0", "Noto Emoji")])
    target = tmp_path / "shapes"
    summary = assets.build_tree("shape_packs", target, cache_dir=tmp_path / "cache", transport=server)
    assert sorted(p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file()) == [
        "MANIFEST.json", "iconify/noto/icons.json", "iconify/noto/info.json"]
    assert summary["files"] == 2 and not (tmp_path / "escape.json").exists()
    # the licence inside the tarball must equal the pinned one
    lying = _tgz("noto", licence="CC-BY-NC-4.0")
    url2 = "https://registry.npmjs.org/@iconify-json/noto/-/noto-2.0.0.tgz"
    monkeypatch.setattr(assets, "inputs", lambda name: [Input(url2, server.add(url2, lying), None, "noto.tgz",
                                                              "Apache-2.0", "Noto Emoji")])
    with pytest.raises(UpdateError) as info:
        assets.build_tree("shape_packs", tmp_path / "s2", cache_dir=tmp_path / "cache", transport=server)
    assert info.value.code == "assets_licence"


# ------------------------------------------------------------------ manifest + payload tooling
def test_downloads_json_marks_fonts_and_shapes_as_recipes_bundled_in_full():
    entries = payloads.load()["entries"]
    for name, folder in (("font_vault", "fonts"), ("shape_packs", "shapes")):
        item = entries[name]
        assert item["recipe"] == name and item["flavours"] == {"online": "on_demand", "full": "bundled"}
        assert item["offline_path"] == folder and payloads.is_pinned(item)
        assert item["install"]["needs_admin"] is False
        with pytest.raises(UpdateError) as info:
            payloads.fetch(name, Path("."))
        assert info.value.code == "recipe_payload"
    assert "font_vault" not in payloads.unpinned(payloads.load())


def test_offline_payload_builds_recipe_folders(tmp_path, monkeypatch, capsys):
    module = _load("installer/fetch_offline_payload.py")
    monkeypatch.setattr(module.assets, "build_tree", lambda name, dest, cache_dir=None: (
        Path(dest).mkdir(parents=True), {"version": "v1", "files": 3, "inputs": 2})[1])
    manifest = tmp_path / "downloads.json"
    manifest.write_text(json.dumps({"schema": payloads.SCHEMA_ID, "entries": {"font_vault": {
        "recipe": "font_vault", "offline_path": "fonts", "flavours": {"full": "bundled"}}}}), encoding="utf-8")
    assert module.main(["--out", str(tmp_path / "o"), "--manifest", str(manifest)]) == 0
    record = json.loads((tmp_path / "o" / "offline_manifest.json").read_text(encoding="utf-8"))
    assert record["entries"]["font_vault"] == {"dir": "fonts", "recipe": "font_vault", "version": "v1", "files": 3,
                                               "inputs": 2, "pinned": True, "status": "bundled"}


# ------------------------------------------------------------------ LibreOffice pin
def test_libreoffice_pin_uses_tdf_published_hash_only():
    pin = _load("installer/pin_libreoffice.py")
    listing = '<a href="25.2.6/">25.2.6/</a> <a href="25.8.1/">x</a> <a href="25.8.2/">x</a> <a href="25.2.5/">x</a>'
    found = pin.versions(listing)
    assert pin.choose(found, "still") == "25.2.6" and pin.choose(found, "fresh") == "25.8.2"
    assert pin.msi_url("25.2.6").endswith("/stable/25.2.6/win/x86_64/LibreOffice_25.2.6_Win_x86-64.msi")
    sha = "ab" * 32
    pages = {"u.msi.sha256": f"{sha}  LibreOffice.msi\n".encode()}

    def get(url):
        if url not in pages:
            raise OSError(url)
        return pages[url]
    assert pin.published_sha256("u.msi", get) == (sha, "u.msi.sha256")
    pages = {"u.msi.mirrorlist": f"<li>SHA-256 Hash: <tt>{sha.upper()}</tt></li>".encode()}
    assert pin.published_sha256("u.msi", get) == (sha, "u.msi.mirrorlist")
    pages = {}
    with pytest.raises(SystemExit):
        pin.published_sha256("u.msi", get)


def test_libreoffice_pin_writes_only_its_own_entry(tmp_path):
    pin = _load("installer/pin_libreoffice.py")
    manifest = tmp_path / "downloads.json"
    manifest.write_text((ROOT / "installer/downloads.json").read_text(encoding="utf-8"), encoding="utf-8")
    before = json.loads(manifest.read_text(encoding="utf-8"))
    pin.write_pin({"version": "25.2.6", "url": "https://download.documentfoundation.org/x.msi", "sha256": "cd" * 32,
                   "size": 123, "hash_source": "https://download.documentfoundation.org/x.msi.sha256",
                   "retrieved": "2026-10-11"}, manifest)
    after = json.loads(manifest.read_text(encoding="utf-8"))
    assert payloads.is_pinned(after["entries"]["libreoffice_msi"])
    assert after["entries"]["libreoffice_msi"]["install"] == before["entries"]["libreoffice_msi"]["install"]
    assert {k: v for k, v in after["entries"].items() if k != "libreoffice_msi"} == \
        {k: v for k, v in before["entries"].items() if k != "libreoffice_msi"}


# ------------------------------------------------------------------ offline shape search
@pytest.fixture
def packs_dir(tmp_path):
    folder = tmp_path / "offline" / "shapes"
    for prefix, licence, version in (("noto", "Apache-2.0", None), ("ri", "Apache-2.0", "4.9.0"),
                                     ("openmoji", "CC-BY-SA-4.0", None)):
        with tarfile.open(fileobj=io.BytesIO(_tgz(prefix, licence=licence, version=version))) as tar:
            for base in ("icons.json", "info.json"):
                out = folder / "iconify" / prefix / base
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(tar.extractfile(f"package/{base}").read())
    return folder


def test_offline_search_follows_the_online_licence_rules(packs_dir):
    from mxstudio.shapes.discovery.local_sets import LocalSets
    sets = LocalSets([packs_dir])
    found = {c.source_id: c for c in sets.search("rocket", limit=50)}
    assert {"noto:rocket", "noto:rocket-launch", "ri:rocket", "openmoji:rocket"} <= set(found)
    assert "noto:rocket-flipped" not in found  # transformed aliases are not offered
    assert found["noto:rocket"].decision.printable and found["noto:rocket"].licence == "Apache-2.0"
    assert not found["openmoji:rocket"].decision.printable  # excluded set, as online
    assert not found["ri:rocket"].decision.printable and "version_above_cap:ri@4.9.0>4.8.0" in found["ri:rocket"].findings
    assert sets.search("moon star")[0].source_id.endswith(":moon-star")
    assert sets.search("") == [] and sets.search("zzz-nothing") == []
    svg = sets.svg("iconify-local://noto/rocket-launch").decode()
    assert svg.startswith('<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">')
    assert 'width="32"' in sets.svg("iconify-local://noto/moon-star").decode()
    for bad in ("iconify-local://noto/../x", "https://api.iconify.design/noto/rocket.svg", "iconify-local://nope/x"):
        with pytest.raises(KeyError):
            sets.svg(bad)


def test_offline_import_needs_approval_and_records_provenance(tmp_path, packs_dir):
    pytest.importorskip("cv2")
    from mxstudio.shapes.discovery.local_sets import LocalSets
    from mxstudio.shapes.service import ServiceError, ShapeService
    svc = ShapeService.at(tmp_path / "lib.sqlite3", client_factory=None, local_sets=LocalSets([packs_dir]))
    result = svc.discover({"query": "rocket", "force": True, "limit": 40})
    keys = {p["key"] for p in result["printable"]}
    assert "iconify:noto:rocket" in keys and not any(k.startswith("iconify:openmoji") for k in keys)
    with pytest.raises(ServiceError) as info:
        svc.import_asset({"key": "iconify:noto:rocket"})
    assert info.value.code == "APPROVAL_REQUIRED"
    out = svc.import_asset({"key": "iconify:noto:rocket", "approved_by": "ui:operator"})
    assert out["ok"] and out["provenance"]["licence"] == "Apache-2.0"
    assert out["provenance"]["asset_url"] == "iconify-local://noto/rocket"
    assert out["provenance"]["source_url"] == "https://icon-sets.iconify.design/noto/rocket/"
    svc.discover({"query": "stroke", "force": True})
    with pytest.raises(ServiceError) as info:
        svc.import_asset({"key": "iconify:noto:stroke-only", "approved_by": "ui:operator"})
    assert info.value.code == "NO_FILLED_AREA"


# ------------------------------------------------------------------ fonts for this user, Doctor
def test_vault_fonts_install_per_user_without_admin(tmp_path):
    from mxstudio.fonts.install import MemoryBackend
    fonts = sorted(p for p in ROOT.rglob("*.ttf") if "node_modules" not in p.parts and ".git" not in p.parts)[:3]
    if not fonts:
        pytest.skip("no sample .ttf in the repository")
    backend = MemoryBackend(tmp_path / "win")
    result = assets.install_vault_fonts(fonts, backend=backend)
    assert result["ok"] and result["installed"] == len(fonts) and backend.admin is False
    assert len(backend.registry["user"]) >= 1 and backend.registry["machine"] == {}
    broken = tmp_path / "broken.ttf"
    broken.write_bytes(b"not a font")
    result = assets.install_vault_fonts([*fonts[:1], broken], backend=MemoryBackend(tmp_path / "win2"))
    assert result["ok"] is False and result["installed"] == 1 and result["failed"][0]["file"] == "broken.ttf"


def test_doctor_shapes_line_and_fixers_prefer_the_full_copy(tmp_path, packs_dir, monkeypatch):
    from mxstudio.doctor import checks, fixers
    from mxstudio.doctor.context import DoctorContext
    ctx = DoctorContext(settings={}, workspace=tmp_path / "ws", home=tmp_path / "home", app_dir=tmp_path / "app",
                        platform="linux")
    line = checks.check_shapes(ctx)
    assert line.ok and line.level == "warn" and line.fix_id == "fetch_shapes"
    ctx.app_dir = packs_dir.parent.parent  # <app>/offline/shapes
    assert checks.check_shapes(ctx).level == "ok"
    monkeypatch.setattr(assets, "tree_status", lambda folder: {"ok": Path(folder) == packs_dir})
    monkeypatch.setattr(assets, "build_tree", lambda *a, **k: pytest.fail("must not download when Full has it"))
    assert fixers.fix_fetch_shapes(ctx)["ok"] is True
    ctx.app_dir = tmp_path / "online-install"
    monkeypatch.setattr(assets, "build_tree", lambda name, target, **k: {"files": 7, "version": "v"})
    out = fixers.fix_fetch_shapes(ctx)
    assert out["ok"] and out["files"] == 7 and out["folder"] == str(ctx.home / "shapes")


# ------------------------------------------------------------------ installer + CI wiring
def test_full_installer_installs_fonts_for_the_user_hidden_and_ci_pins_libreoffice():
    nsi = (ROOT / "installer/nsis/MagazineStudio.nsi").read_text(encoding="utf-8")
    full = nsi[nsi.index('!if "${FLAVOUR}" == "full"\n  SetOutPath "$INSTDIR\\offline"'):]
    full = full[:full.index("!endif")]
    assert "nsExec::Exec '\"$INSTDIR\\${CLI_EXE}\" assets install-fonts" in full and "ExecWait" not in nsi
    workflow = (ROOT / ".github/workflows/mag-release.yml").read_text(encoding="utf-8")
    step = workflow[workflow.index("Pin LibreOffice from TDF"):]
    step = step[:step.index("- name: Fetch the Full payload")]
    assert "github.ref_type == 'branch'" in step and "continue-on-error: true" in step
    assert "pin_libreoffice.py --write --save workspace/offline/libreoffice/LibreOffice_Win_x86-64.msi" in step
    assert "--cache workspace/asset-cache" in workflow
    proof = (ROOT / "installer/windows_sandbox/sandbox_proof.ps1").read_text(encoding="utf-8")
    assert "fonts installed" in proof and "shape packs" in proof and proof.isascii()


def test_downloads_json_versions_follow_the_catalog_pins():
    entries = payloads.load()["entries"]
    assert [entries[n]["version"] for n in assets.RECIPES] == [assets.version(n) for n in assets.RECIPES]
