"""installer/downloads.json: pinned or explicitly TO-PIN; unpinned payloads are refused; zips extract safely."""
from __future__ import annotations

import hashlib
import json
import zipfile

import pytest

from mxstudio.update import payloads
from mxstudio.update.download import download, progress_line
from mxstudio.update.errors import IntegrityError, UpdateError


def test_manifest_shape_and_honest_pins():
    data = payloads.load()
    entries = data["entries"]
    assert {"libreoffice_msi", "node_runtime", "webview2_bootstrapper", "font_vault", "shape_packs"} <= set(entries)
    for name, item in entries.items():
        assert item.get("label_ar") and item.get("label_en"), name
        if item.get("recipe"):  # font vault / shape packs: assembled from per-file pins (test_asset_bundles.py)
            assert payloads.is_pinned(item), name
            continue
        assert item["url"].startswith("https://"), name
        sha = str(item["sha256"])
        # either a real 64-hex pin, the explicit TO-PIN marker, or verified another way (Authenticode)
        assert payloads.is_pinned(item) or sha == "TO-PIN" or item.get("verify", "").startswith("authenticode:"), name
    assert payloads.is_pinned(entries["node_runtime"])  # pinned from nodejs.org SHASUMS256.txt
    lo = entries["libreoffice_msi"]
    assert lo["install"]["method"] == "msi_admin_extract" and lo["install"]["needs_admin"] is False
    assert lo["install"]["command"][:2] == ["msiexec", "/a"] and "/qn" in lo["install"]["command"]
    assert any(part.startswith("TARGETDIR=") for part in lo["install"]["command"])
    assert lo["fallback"]["needs_admin"] is True
    # what is still open is visible, not hidden
    assert set(payloads.unpinned(data)) == {n for n, e in entries.items()
                                            if not e.get("verify") and not payloads.is_pinned(e)}


def test_unpinned_entry_is_refused(tmp_path, server):
    manifest = {"schema": payloads.SCHEMA_ID, "entries": {"x": {
        "label_ar": "س", "label_en": "x", "url": "https://example.org/x.zip", "sha256": "TO-PIN", "file_name": "x.zip"}}}
    server.add("https://example.org/x.zip", b"data")
    with pytest.raises(IntegrityError) as info:
        payloads.fetch("x", tmp_path, manifest=manifest, transport=server)
    assert info.value.code == "unpinned" and "TO-PIN" in info.value.ar
    assert server.requests == []  # nothing was even requested


def test_pinned_entry_downloads_and_offline_copy_wins(tmp_path, server):
    data = b"font vault" * 100
    url = "https://github.com/o/r/releases/download/a/v.zip"
    sha = server.add(url, data)
    item = {"label_ar": "خطوط", "label_en": "fonts", "url": url, "sha256": sha, "size": len(data),
            "file_name": "v.zip", "offline_path": "fonts/v.zip", "version": "1"}
    manifest = {"schema": payloads.SCHEMA_ID, "entries": {"font_vault": item}}
    got = payloads.fetch("font_vault", tmp_path / "dl", manifest=manifest, transport=server)
    assert got.read_bytes() == data and len(server.requests) == 1
    app = tmp_path / "app"
    (app / "offline" / "fonts").mkdir(parents=True)
    (app / "offline" / "fonts" / "v.zip").write_bytes(data)
    assert payloads.fetch("font_vault", tmp_path / "dl2", app_dir=app, manifest=manifest, transport=server) == \
        app / "offline" / "fonts" / "v.zip"
    assert len(server.requests) == 1  # offline copy used, no network


def test_offline_copy_recorded_unpinned_is_used_only_when_it_matches(tmp_path, server):
    data = b"msi bytes" * 10
    item = {"label_ar": "ليبر", "label_en": "lo", "url": "https://x.org/TO-PIN.msi", "sha256": "TO-PIN",
            "file_name": "lo.msi", "offline_path": "libreoffice/lo.msi"}
    manifest = {"schema": payloads.SCHEMA_ID, "entries": {"libreoffice_msi": item}}
    app = tmp_path / "app"
    (app / "offline" / "libreoffice").mkdir(parents=True)
    (app / "offline" / "libreoffice" / "lo.msi").write_bytes(data)
    record = {"entries": {"libreoffice_msi": {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}}}
    (app / "offline" / "offline_manifest.json").write_text(json.dumps(record), encoding="utf-8")
    assert payloads.fetch("libreoffice_msi", tmp_path, app_dir=app, manifest=manifest, transport=server).is_file()
    (app / "offline" / "libreoffice" / "lo.msi").write_bytes(b"other")
    with pytest.raises(IntegrityError):
        payloads.fetch("libreoffice_msi", tmp_path, app_dir=app, manifest=manifest, transport=server)


def test_download_refuses_http_and_unpinned(tmp_path, server):
    with pytest.raises(UpdateError) as info:
        download("http://github.com/x", tmp_path / "x", sha256="a" * 64, transport=server)
    assert info.value.code == "insecure_url"
    with pytest.raises(IntegrityError):
        download("https://github.com/x", tmp_path / "x", sha256="TO-PIN", transport=server)


def test_stale_partial_from_another_file_is_discarded(tmp_path, server):
    data = b"new file" * 500
    url = "https://github.com/o/r/new.bin"
    sha = server.add(url, data)
    part = tmp_path / "f.bin.part"
    part.write_bytes(b"garbage from an older download")
    (tmp_path / "f.bin.part.json").write_text(json.dumps({"url": "https://github.com/o/r/old.bin", "sha256": "0" * 64}))
    download(url, tmp_path / "f.bin", sha256=sha, size=len(data), transport=server)
    assert (tmp_path / "f.bin").read_bytes() == data
    assert server.requests[-1][1] == 0


def test_progress_lines_are_bilingual_with_arabic_digits():
    line = progress_line("LibreOffice", "LibreOffice", 52_428_800, 104_857_600)
    assert line["percent"] == 50 and "٥٠٪" in line["ar"] and "50%" in line["en"]
    assert "50" in progress_line("x", "x", 1, 2, digits="latin")["ar"]


def test_safe_extract_blocks_traversal(tmp_path):
    good = tmp_path / "good.zip"
    with zipfile.ZipFile(good, "w") as zf:
        zf.writestr("خطوط/Amiri-Regular.ttf", b"ttf")
    assert [p.name for p in payloads.safe_extract(good, tmp_path / "out")] == ["Amiri-Regular.ttf"]
    for evil_name in ("../evil.txt", "/abs.txt", "C:/win.txt", "a/../../b.txt"):
        evil = tmp_path / "evil.zip"
        with zipfile.ZipFile(evil, "w") as zf:
            zf.writestr(evil_name, b"x")
        with pytest.raises(UpdateError):
            payloads.safe_extract(evil, tmp_path / "out2")
    assert not (tmp_path / "evil.txt").exists()


def test_fetch_offline_payload_is_strict_by_default(tmp_path, capsys):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "fetch_offline_payload", Path(payloads.__file__).resolve().parents[2] / "installer" / "fetch_offline_payload.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    manifest = tmp_path / "downloads.json"
    manifest.write_text(json.dumps({"schema": payloads.SCHEMA_ID, "entries": {"lo": {
        "url": "https://x.org/TO-PIN.msi", "sha256": "TO-PIN", "file_name": "lo.msi", "offline_path": "lo/lo.msi",
        "flavours": {"full": "bundled"}}}}), encoding="utf-8")
    assert module.main(["--out", str(tmp_path / "o"), "--manifest", str(manifest)]) == 1
    assert "TO-PIN" in capsys.readouterr().err
    assert module.main(["--out", str(tmp_path / "o"), "--manifest", str(manifest), "--allow-unpinned"]) == 0
    record = json.loads((tmp_path / "o" / "offline_manifest.json").read_text(encoding="utf-8"))
    assert record["entries"]["lo"] == {"file": "lo/lo.msi", "pinned": False, "status": "missing", "reason": "url is TO-PIN"}
