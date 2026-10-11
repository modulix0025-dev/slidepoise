"""latest.json: Ed25519 sign/verify with a test key; every kind of tampering is rejected."""
from __future__ import annotations

import copy
import json

import pytest

from mxstudio.update import manifest as mf
from mxstudio.update import signing, versioning
from mxstudio.update.errors import ManifestError, SignatureError

SHA = "a" * 64


def _manifest(version="0.3.0", url=None, name=None):
    name = name or f"ModuleX-MagazineStudio-Setup-{version}.exe"
    return {"schema": mf.SCHEMA_ID, "app": mf.APP_ID, "version": version, "released_at": "2026-10-11T00:00:00Z",
            "notes_ar": "تحسينات في الخطوط العربي", "notes_en": "Arabic font fixes",
            "assets": {"online": {"name": name, "url": url or f"https://github.com/o/r/releases/download/mxs-v{version}/{name}",
                                  "sha256": SHA, "size": 1234}}}


def test_sign_then_verify_roundtrip(keypair):
    private, public = keypair
    signed = signing.sign_manifest(_manifest(), private)
    assert signed["signature"]["alg"] == "Ed25519"
    assert signing.verify_manifest(signed, [public]) == signing.key_id(public)
    # re-serialising (different key order / indentation / escaping) keeps the signature valid
    reloaded = json.loads(json.dumps(signed, ensure_ascii=True, indent=4, sort_keys=False))
    assert signing.verify_manifest(reloaded, {signing.key_id(public): public})
    mf.validate(reloaded)


@pytest.mark.parametrize("path,value", [
    (("version",), "0.3.1"),
    (("assets", "online", "sha256"), "b" * 64),
    (("assets", "online", "url"), "https://github.com/evil/r/releases/download/x/ModuleX-MagazineStudio-Setup-0.3.0.exe"),
    (("assets", "online", "size"), 1235),
    (("notes_ar",), "ملاحظات متغيّرة"),
])
def test_tampered_manifest_is_rejected(keypair, path, value):
    private, public = keypair
    signed = signing.sign_manifest(_manifest(), private)
    tampered = copy.deepcopy(signed)
    node = tampered
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    with pytest.raises(SignatureError) as info:
        signing.verify_manifest(tampered, [public])
    assert info.value.code == "bad_signature"
    assert info.value.ar and info.value.en


def test_added_field_is_rejected(keypair):
    private, public = keypair
    signed = signing.sign_manifest(_manifest(), private)
    signed["min_version"] = "0.0.1"
    with pytest.raises(SignatureError):
        signing.verify_manifest(signed, [public])


def test_unsigned_unknown_key_and_no_key_are_rejected(keypair):
    private, public = keypair
    with pytest.raises(SignatureError) as info:
        signing.verify_manifest(_manifest(), [public])
    assert info.value.code == "unsigned"
    other_private, _ = signing.generate_keypair()
    with pytest.raises(SignatureError) as info:
        signing.verify_manifest(signing.sign_manifest(_manifest(), other_private), [public])
    assert info.value.code == "unknown_key"
    with pytest.raises(SignatureError) as info:
        signing.verify_manifest(signing.sign_manifest(_manifest(), private), {})
    assert info.value.code == "no_trusted_key"


def test_signature_swapped_between_manifests_is_rejected(keypair):
    private, public = keypair
    a = signing.sign_manifest(_manifest("0.3.0"), private)
    b = signing.sign_manifest(_manifest("0.4.0"), private)
    a["signature"] = b["signature"]
    with pytest.raises(SignatureError):
        signing.verify_manifest(a, [public])


def test_pem_private_key_is_accepted(keypair):
    from cryptography.hazmat.primitives import serialization
    private, public = keypair
    pem = signing.load_private(private).private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                      serialization.NoEncryption()).decode()
    assert signing.public_from_private(pem) == public
    signing.verify_manifest(signing.sign_manifest(_manifest(), pem), [public])


@pytest.mark.parametrize("bad", ["", "not base64!!", "AAAA"])
def test_bad_private_keys_fail_closed(bad):
    with pytest.raises(SignatureError):
        signing.sign_manifest(_manifest(), bad)


@pytest.mark.parametrize("mutate,code_part", [
    (lambda m: m["assets"]["online"].update(url="http://github.com/o/r/x.exe"), "https"),
    (lambda m: m["assets"]["online"].update(url="https://example.com/ModuleX-MagazineStudio-Setup-0.3.0.exe"), "https"),
    (lambda m: m["assets"]["online"].update(name="..\\evil.exe"), "unsafe name"),
    (lambda m: m["assets"]["online"].update(sha256="ABC"), "sha256"),
    (lambda m: m["assets"]["online"].update(size=0), "size"),
    (lambda m: m.update(version="latest"), "version"),
    (lambda m: m.update(schema="mxs-update/0"), "schema"),
    (lambda m: m["assets"].update(beta=m["assets"]["online"]), "flavour"),
])
def test_manifest_policy_negative_controls(mutate, code_part):
    m = _manifest()
    mutate(m)
    with pytest.raises(ManifestError) as info:
        mf.validate(m)
    assert code_part in info.value.en


def test_build_manifest_from_files(tmp_path):
    exe = tmp_path / "ModuleX-MagazineStudio-Setup-0.3.0.exe"
    exe.write_bytes(b"installer bytes")
    built = mf.build("0.3.0", "https://github.com/o/r/releases/download/mxs-v0.3.0", {"online": exe})
    assert built["assets"]["online"]["size"] == len(b"installer bytes")
    assert built["assets"]["online"]["url"].endswith("/mxs-v0.3.0/ModuleX-MagazineStudio-Setup-0.3.0.exe")


def test_versions_order():
    assert versioning.is_newer("0.3.0", "0.2.9")
    assert versioning.is_newer("0.10.0", "0.9.9")
    assert versioning.is_newer("0.3.0", "0.3.0-rc.2")
    assert versioning.is_newer("0.3.0-rc.10", "0.3.0-rc.2")
    assert not versioning.is_newer("0.2.0", "0.2.0")
    assert not versioning.is_newer("0.1.9", "0.2.0")


def test_cli_keygen_sign_verify_and_tamper(tmp_path, capsys):
    from mxstudio.update.cli import main
    key_file = tmp_path / "private.txt"
    assert main(["keygen", "--out-private", str(key_file)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert key_file.read_text().strip() not in json.dumps(out)  # private key never printed
    assert main(["keygen", "--out-private", str(key_file)]) == 1  # refuses to overwrite
    capsys.readouterr()
    exe = tmp_path / "ModuleX-MagazineStudio-Setup-0.3.0.exe"
    exe.write_bytes(b"x" * 2048)
    unsigned, signed = tmp_path / "u.json", tmp_path / "latest.json"
    assert main(["manifest", "--version", "0.3.0", "--base-url", "https://github.com/o/r/releases/download/mxs-v0.3.0",
                 "--online", str(exe), "--out", str(unsigned)]) == 0
    assert main(["sign", "--manifest", str(unsigned), "--out", str(signed), "--key-file", str(key_file)]) == 0
    capsys.readouterr()
    assert main(["verify", "--manifest", str(signed), "--pubkey", out["public_key"], "--assets-dir", str(tmp_path)]) == 0
    capsys.readouterr()
    exe.write_bytes(b"y" * 2048)  # asset replaced after signing
    assert main(["verify", "--manifest", str(signed), "--pubkey", out["public_key"], "--assets-dir", str(tmp_path)]) == 1
    data = json.loads(signed.read_text(encoding="utf-8"))
    data["version"] = "9.9.9"
    signed.write_text(json.dumps(data), encoding="utf-8")
    capsys.readouterr()
    assert main(["verify", "--manifest", str(signed), "--pubkey", out["public_key"]]) == 1
    assert "bad_signature" in capsys.readouterr().out


def test_embed_writes_public_key_only(tmp_path, keypair, capsys):
    from mxstudio.update.cli import main
    from mxstudio.update.trust import load
    private, public = keypair
    trust_file = tmp_path / "trust.json"
    trust_file.write_text('{"public_keys": {}, "manifest_url": ""}', encoding="utf-8")
    assert main(["embed", "--trust-file", str(trust_file), "--repo", "o/r", "--pubkey", public]) == 0
    loaded = load(trust_file)
    assert loaded.public_keys == {signing.key_id(public): public}
    assert loaded.manifest_url == "https://github.com/o/r/releases/latest/download/latest.json"
    assert private not in trust_file.read_text(encoding="utf-8")


def test_repository_trust_file_holds_no_private_material():
    from mxstudio.update.trust import TRUST_FILE
    data = json.loads(TRUST_FILE.read_text(encoding="utf-8"))
    assert set(data) <= {"public_keys", "manifest_url", "allowed_hosts", "release_repo"}
    for key in data["public_keys"].values():
        signing.load_public(key)  # only 32-byte public keys


def test_repository_trust_file_pins_the_release_key():
    # the release signing key's public half ships in the app; without it installed apps refuse every latest.json
    from mxstudio.update.trust import TRUST_FILE
    data = json.loads(TRUST_FILE.read_text(encoding="utf-8"))
    assert data["public_keys"], "no update public key committed: installed apps could never auto-update"
    for key_id, key in data["public_keys"].items():
        assert signing.key_id(key) == key_id
