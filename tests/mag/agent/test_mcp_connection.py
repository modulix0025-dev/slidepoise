"""Claude Desktop always finds the Studio (phase 16): install location, fixed launcher, every config, self-heal,
restart detection, Claude Desktop's log, a robust MCP server, the inbox, requests without an API key, one window.

Windows-only behaviour (registry, mutex, real installer, Claude.exe) runs through injected fakes here and for real in
installer/windows_sandbox/mcp_connection_proof.ps1 on windows-latest (mag-release.yml).
"""
from __future__ import annotations

import base64
import io
import json
import os
import subprocess
import sys
import threading
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from mxstudio.mcp import clients
from mxstudio.winsys import ProcessInfo, default_install_dir, record_install, sync_folder_reason

ROOT = Path(__file__).resolve().parents[3]
FONTS = ROOT / "tests" / "mag" / "fixtures" / "fonts"
warnings.filterwarnings("ignore", category=DeprecationWarning)
HANDSHAKE = clients.HANDSHAKE


class FakeSystem:
    platform = "win32"

    def __init__(self, env=None, attributes=None, processes=None):
        self._env, self._attributes, self._processes = env or {}, attributes or {}, processes or {}
        self.registry: dict[str, str] = {}

    def env(self, name):
        return self._env.get(name)

    def file_attributes(self, path):
        return self._attributes.get(str(path), 0)

    def reg_get(self, name, key=None):
        return self.registry.get(name)

    def reg_set(self, name, value, key=None):
        self.registry[name] = value
        return True

    def processes(self, image):
        return list(self._processes.get(image.casefold(), []))

    def known_desktop(self):
        return Path(self._env.get("DESKTOP", "/tmp"))


def _png(colour="#F2A33A", size=(64, 48)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, "PNG")
    return out.getvalue()


# ------------------------------------------------------------------ 1) install location
def test_sync_folders_are_recognised_and_the_default_is_not():
    od = r"C:\Users\Myfam\OneDrive"
    system = FakeSystem(env={"OneDrive": od, "LOCALAPPDATA": r"C:\Users\Myfam\AppData\Local"})
    assert sync_folder_reason(od + r"\Desktop\ModuleX Magazine Studio", system)["kind"] == "onedrive"
    assert sync_folder_reason(r"D:\Dropbox\Apps\ModuleX Magazine Studio", system)["kind"] == "dropbox"
    assert sync_folder_reason(r"G:\My Drive\Studio", system)["kind"] == "my_drive"
    assert sync_folder_reason(r"C:\Users\Myfam\OneDrive - ModuleX\Desktop\Studio", system)["kind"] == "onedrive"
    on_demand = FakeSystem(attributes={r"D:\Cloud": 0x00400000})
    assert sync_folder_reason(r"D:\Cloud\Programs\Studio", on_demand)["kind"] == "cloud_files"
    # negative controls: the default folder and an ordinary drive folder are fine
    assert sync_folder_reason(default_install_dir(system), system) is None
    assert sync_folder_reason(r"D:\Programs\ModuleX Magazine Studio", system) is None
    assert sync_folder_reason(r"C:\Users\Myfam\AppData\Local\Programs\OneNote helper", system) is None


def test_install_dir_registry_follows_the_real_folder():
    system = FakeSystem()
    first = record_install(Path(r"C:\A\ModuleX Magazine Studio"), "0.2.0", system)
    assert set(first["changed"]) == {"InstallDir", "Version"} and system.registry["InstallDir"].endswith("Studio")
    assert record_install(Path(r"C:\A\ModuleX Magazine Studio"), "0.2.0", system)["changed"] == []
    moved = record_install(Path(r"D:\B\ModuleX Magazine Studio"), "0.2.1", system)
    assert moved["changed"] == ["InstallDir", "Version"] and system.registry["InstallDir"].startswith("D:")


def test_installer_refuses_sync_folders_and_records_install_dir():
    nsi = (ROOT / "installer" / "nsis" / "MagazineStudio.nsi").read_text(encoding="utf-8")
    assert "Function IsSyncPath" in nsi and "OneDriveConsumer" in nsi and "0x441000" in nsi
    leave = nsi[nsi.index("Function DirLeave"):nsi.index("FunctionEnd", nsi.index("Function DirLeave"))]
    assert leave.index("Call IsSyncPath") < leave.index("Call CheckFolder")  # warned before anything else
    assert 'WriteRegStr HKCU "${MXS_KEY}" "InstallDir" "$INSTDIR"' in nsi
    assert 'WriteRegStr HKCU "${MXS_KEY}" "Version" "${APP_VER}"' in nsi
    install = nsi[nsi.index('Section "Install"'):]
    assert install.index("Call IsSyncPath") < install.index("Call CheckFolder")  # silent: moved to the default


# ------------------------------------------------------------------ 2) fixed launcher, every config
def test_entry_is_the_fixed_launcher_wherever_the_program_lives(tmp_path):
    home = tmp_path / "home"
    a = clients.expected_entry(home, tmp_path / "A" / "ModuleX Magazine Studio", frozen=True, platform="win32")
    b = clients.expected_entry(home, tmp_path / "other" / "B", frozen=True, platform="win32")
    assert a == b == {"command": str(home / "bin" / "mxstudio-mcp.exe"), "args": []}
    assert "Programs" not in a["command"]  # never the program's own exe


def test_launcher_is_copied_into_the_app_home_and_refreshed(tmp_path):
    app, home = tmp_path / "app", tmp_path / "home"
    (app / "mcp").mkdir(parents=True)
    (app / "mcp" / "mxstudio-mcp.exe").write_bytes(b"MZ v1")
    assert clients.ensure_launcher(home, app)["action"] == "copied"
    assert clients.ensure_launcher(home, app)["action"] == "current"
    (app / "mcp" / "mxstudio-mcp.exe").write_bytes(b"MZ v2")
    assert clients.ensure_launcher(home, app)["action"] == "copied"
    assert (home / "bin" / "mxstudio-mcp.exe").read_bytes() == b"MZ v2"


def test_launcher_source_is_tiny_and_finds_the_program_through_the_registry():
    source = (ROOT / "installer" / "mcp_launcher" / "mxstudio_mcp.c").read_text(encoding="utf-8")
    assert 'L"Software\\\\ModuleX\\\\MagazineStudio"' in source and 'L"InstallDir"' in source
    assert "STARTF_USESTDHANDLES" in source and "JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE" in source
    assert "CREATE_NO_WINDOW" in source and '" mcp"' in source


@pytest.mark.skipif(not __import__("shutil").which("x86_64-w64-mingw32-gcc"), reason="mingw-w64 not installed here")
def test_launcher_builds_as_a_small_windowless_exe(tmp_path):
    out = tmp_path / "mxstudio-mcp.exe"
    subprocess.run(["sh", str(ROOT / "installer" / "mcp_launcher" / "build.sh"), str(out)], check=True,
                   capture_output=True, timeout=300)
    data = out.read_bytes()
    assert data[:2] == b"MZ" and len(data) < 64 * 1024
    pe = int.from_bytes(data[0x3C:0x40], "little")
    subsystem = int.from_bytes(data[pe + 24 + 68:pe + 24 + 70], "little")
    assert subsystem == 2  # IMAGE_SUBSYSTEM_WINDOWS_GUI: no console window, ever


def _claude_pc(tmp_path):
    classic = tmp_path / "Roaming" / "Claude" / "claude_desktop_config.json"
    store = tmp_path / "Packages" / "Claude_pzs8sxrjxfjjc" / "LocalCache" / "Roaming" / "Claude" / "claude_desktop_config.json"
    classic.parent.mkdir(parents=True)
    store.parent.mkdir(parents=True)
    classic.write_text(json.dumps({"mcpServers": {"filesystem": {"command": "npx", "args": ["x"]}},
                                   "globalShortcut": "Ctrl+Space"}), encoding="utf-8")
    store.write_text(json.dumps({"mcpServers": {"github": {"command": "gh"}},
                                 "mcpServersOld": {"modulex-studio": {"command": "old"}}}), encoding="utf-8")
    return classic, store


def test_every_claude_desktop_config_gets_the_same_entry_and_keeps_its_servers(tmp_path):
    classic, store = _claude_pc(tmp_path)
    home = tmp_path / "home"
    entry = clients.expected_entry(home, tmp_path / "app", frozen=True, platform="win32")
    done = clients.install(entry, [classic, store], home)
    assert [c["changed"] for c in done["configs"]] == [True, True] and all(c["backup"] for c in done["configs"])
    a, b = (json.loads(p.read_text(encoding="utf-8")) for p in (classic, store))
    assert a["mcpServers"]["modulex-studio"] == b["mcpServers"]["modulex-studio"] == entry
    assert a["mcpServers"]["filesystem"]["command"] == "npx" and a["globalShortcut"] == "Ctrl+Space"
    assert b["mcpServers"]["github"]["command"] == "gh" and b["mcpServersOld"]  # unknown keys kept as they are
    assert clients.read_state(home)["config_changed_at"] > 0
    again = clients.install(entry, [classic, store], home)
    assert [c["changed"] for c in again["configs"]] == [False, False]  # nothing rewritten when already right
    gone = clients.remove([classic, store], home)
    assert gone["removed"] and all("modulex-studio" not in json.loads(p.read_text())["mcpServers"] for p in (classic, store))
    assert json.loads(classic.read_text())["mcpServers"]["filesystem"]["command"] == "npx"


def test_one_broken_config_stops_install_before_anything_is_written(tmp_path):
    classic, store = _claude_pc(tmp_path)
    store.write_text("{ broken", encoding="utf-8")
    before = classic.read_text(encoding="utf-8")
    with pytest.raises(clients.ConfigProblem) as problem:
        clients.install({"command": "x", "args": []}, [classic, store], tmp_path / "home")
    assert problem.value.ar and classic.read_text(encoding="utf-8") == before and store.read_text() == "{ broken"


def test_acceptance_install_connect_uninstall_reinstall_elsewhere_needs_no_config_change(tmp_path):
    """سطّب ← وصّل ← uninstall ← سطّب في مسار تاني ← نفس المدخل يشتغل من غير ما الإعدادات تتلمس."""
    classic, store = _claude_pc(tmp_path)
    home = tmp_path / "home"
    first_app = tmp_path / "Programs" / "ModuleX Magazine Studio"
    entry = clients.expected_entry(home, first_app, frozen=True, platform="win32")
    clients.install(entry, [classic, store], home)
    connected = classic.read_bytes()
    clients.remove([classic, store], home)  # the uninstaller
    second_app = tmp_path / "D" / "Programs" / "ModuleX Magazine Studio"
    entry2 = clients.expected_entry(home, second_app, frozen=True, platform="win32")
    clients.install(entry2, [classic, store], home)  # the next installer
    assert entry2 == entry and json.loads(classic.read_bytes()) == json.loads(connected)


# ------------------------------------------------------------------ 3) self-heal
def test_self_heal_fixes_missing_broken_and_stale_entries_and_never_touches_invalid_json(tmp_path):
    classic, store = _claude_pc(tmp_path)
    home = tmp_path / "home"
    launcher = home / "bin" / "mxstudio-mcp.exe"
    launcher.parent.mkdir(parents=True)
    launcher.write_bytes(b"MZ")
    entry = {"command": str(launcher), "args": []}
    report = clients.heal(entry, [classic, store], home)
    assert [c["action"] for c in report["configs"]] == ["fixed", "fixed"]
    assert report["configs"][0]["reason"] == "missing" and report["configs"][0]["kept_servers"] == ["filesystem"]
    assert [c["action"] for c in clients.heal(entry, [classic, store], home)["configs"]] == ["ok", "ok"]
    # pointing at a program folder that is gone (the operator's real failure)
    data = json.loads(classic.read_text())
    data["mcpServers"]["modulex-studio"] = {"command": str(tmp_path / "gone" / "mxstudio-cli.exe"), "args": ["mcp"]}
    classic.write_text(json.dumps(data), encoding="utf-8")
    fixed = clients.heal(entry, [classic, store], home)["configs"][0]
    assert fixed["action"] == "fixed" and fixed["reason"] == "different"
    assert json.loads(classic.read_text())["mcpServers"]["modulex-studio"] == entry
    store.write_text("{ not json", encoding="utf-8")
    report = clients.heal(entry, [classic, store], home)
    assert report["invalid"][0]["action"] == "untouched_invalid" and "مش هلمسه" in report["invalid"][0]["ar"]
    assert store.read_text() == "{ not json"
    launcher.unlink()
    assert clients.entry_problem(entry, entry) == "command_missing"


def test_heal_all_restores_a_deleted_entry_like_opening_the_studio(tmp_path, monkeypatch):
    """امسح المدخل يدوي ← افتح الاستوديو ← المدخل رجع، وself_test شغّال، ومفيش سيرفر تاني اتمسح."""
    from mxstudio.app.state import AppState
    from mxstudio.mcp.heal import heal_all
    monkeypatch.setenv("MXS_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    classic, store = _claude_pc(tmp_path)
    state = AppState.create(tmp_path / "home")
    try:
        entry = clients.expected_entry(state.home)
        clients.install(entry, [classic, store], state.home)
        data = json.loads(classic.read_text())
        del data["mcpServers"]["modulex-studio"]
        classic.write_text(json.dumps(data), encoding="utf-8")
        monkeypatch.setenv("MXS_HOME", str(state.home))
        report = heal_all(state, None, candidates=[classic, store], shortcut=False)
    finally:
        state.close()
    assert report["configs"]["fixed"] == 1 and report["self_test"]["ok"], report
    after = json.loads(classic.read_text())["mcpServers"]
    assert after["modulex-studio"] == entry and after["filesystem"]["command"] == "npx"
    assert clients.read_state(tmp_path / "home")["last_heal"]["self_test"]["ok"]


def test_installer_connects_on_install_and_disconnects_only_ours_on_uninstall():
    nsi = (ROOT / "installer" / "nsis" / "MagazineStudio.nsi").read_text(encoding="utf-8")
    assert "connect install --out" in nsi and "connect remove --out" in nsi
    assert '${DATA_DIR}\\bin\\${MCP_EXE}' in nsi
    uninstall = nsi[nsi.index('Section "Uninstall"'):]
    assert uninstall.index("connect remove") < uninstall.index("RMDir /r \"$INSTDIR\"")


# ------------------------------------------------------------------ 4) restart Claude Desktop
def test_restart_is_pending_only_for_a_claude_that_started_before_the_change(tmp_path):
    home = tmp_path / "home"
    clients.remember_change(home, ["x"], "install", when=1000.0)
    old = FakeSystem(processes={"claude.exe": [ProcessInfo(1, "Claude.exe", "C:/x/claude.exe", 900.0)]})
    new = FakeSystem(processes={"claude.exe": [ProcessInfo(2, "Claude.exe", "C:/x/claude.exe", 1100.0)]})
    closed = FakeSystem()
    assert clients.restart_pending(home, old)["pending"] and "لازم يتقفل" in clients.restart_pending(home, old)["ar"]
    assert not clients.restart_pending(home, new)["pending"]
    assert not clients.restart_pending(home, closed)["pending"]


def test_restart_quits_and_reopens_store_and_classic_builds(tmp_path, monkeypatch):
    calls = []

    class Gone(FakeSystem):
        def __init__(self, path):
            super().__init__()
            self.path, self.ticks = path, 0

        def processes(self, image):
            self.ticks += 1
            return [ProcessInfo(1, "Claude.exe", self.path, 1.0)] if self.ticks == 1 else []

    def run(cmd, **_):
        calls.append(cmd)
        out = b"Claude_pzs8sxrjxfjjc!Claude" if cmd[0] == "powershell.exe" else b""
        return SimpleNamespace(returncode=0, stdout=out, stderr=b"")

    store = clients.restart_claude(Gone(r"C:\Program Files\WindowsApps\Claude_1.0\app\Claude.exe"), run=run,
                                   sleep=lambda s: None)
    assert store["ok"] and calls[0][:2] == ["taskkill", "/T"] and calls[-1] == ["explorer.exe",
                                                                                "shell:AppsFolder\\Claude_pzs8sxrjxfjjc!Claude"]
    exe = tmp_path / "AnthropicClaude" / "claude.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"MZ")
    spawned = []
    monkeypatch.setattr("mxstudio.proc.spawn_hidden", lambda cmd, **_: spawned.append(cmd))
    calls.clear()
    classic = clients.restart_claude(Gone(str(exe)), run=run, sleep=lambda s: None)
    assert classic["ok"] and spawned == [[str(exe)]] and not any(c[0] == "explorer.exe" for c in calls)


def test_claude_desktop_log_last_state(tmp_path):
    log = tmp_path / "mcp-server-modulex-studio.log"
    assert clients.claude_log_state([log])["state"] == "no_log"
    log.write_text("2026-10-11T10:00:00Z [modulex-studio] [info] Initializing server...\n", encoding="utf-8")
    assert clients.claude_log_state([log])["state"] == "starting"
    with log.open("a", encoding="utf-8") as handle:
        handle.write("2026-10-11T10:00:01Z [modulex-studio] [info] Server started and connected successfully\n")
    assert clients.claude_log_state([log])["state"] == "connected"
    with log.open("a", encoding="utf-8") as handle:
        handle.write("2026-10-11T10:05:00Z [modulex-studio] [error] spawn C:\\gone\\mxstudio-cli.exe ENOENT\n")
    state = clients.claude_log_state([log])
    assert state["state"] == "error" and "ENOENT" in state["line"]


# ------------------------------------------------------------------ 5) the MCP server itself
def _env(tmp_path, home="home"):
    return dict(os.environ, MXS_HOME=str(tmp_path / home), MXS_WORKSPACE=str(tmp_path / "المشروع" / "ws"),
                PYTHONPATH=str(ROOT), PYTHONUTF8="1")


def _handshake(env) -> dict:
    started = time.time()
    proc = subprocess.Popen([sys.executable, "-m", "mxstudio", "mcp"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=env, cwd=str(ROOT))
    proc.stdin.write(HANDSHAKE)
    proc.stdin.flush()
    replies, junk = [], []
    while len(replies) < 2:
        line = proc.stdout.readline()
        if not line:
            break
        try:
            replies.append(json.loads(line))
        except json.JSONDecodeError:
            junk.append(line)
    seconds = time.time() - started
    proc.stdin.close()
    rest = proc.stdout.read()
    proc.wait(60)
    junk += [l for l in rest.splitlines() if l.strip()]
    return {"seconds": seconds, "replies": replies, "junk": junk, "tools": len(replies[-1]["result"]["tools"])
            if replies and "result" in replies[-1] else 0}


def test_handshake_20_times_and_in_parallel_with_the_window_open_is_fast_and_pure(tmp_path):
    """mxstudio-mcp ×20 in a row and ×20 at once while the Studio server runs: every handshake < 2 s, stdout is
    JSON-RPC only. (The real launcher on a clean Windows PC: mcp_connection_proof.ps1.)"""
    from mxstudio.app.runner import serve
    env = _env(tmp_path)
    os.environ_backup = dict(os.environ)
    for key in ("MXS_HOME", "MXS_WORKSPACE"):
        os.environ[key] = env[key]
    try:
        server, thread, port = serve(Path(env["MXS_HOME"]), block=False)  # the Studio window's server
        first = _handshake(env)  # cold: no tools cache yet
        serial = [_handshake(env) for _ in range(20)]
        with ThreadPoolExecutor(max_workers=20) as pool:
            parallel = list(pool.map(lambda _i: _handshake(env), range(20)))
    finally:
        server.should_exit = True
        thread.join(30)
        os.environ.clear()
        os.environ.update(os.environ_backup)
    assert first["tools"] > 50 and not first["junk"]
    for result in serial + parallel:
        assert result["tools"] == first["tools"] and result["junk"] == [], result
    assert max(r["seconds"] for r in serial) < 2.0, [round(r["seconds"], 2) for r in serial]
    assert max(r["seconds"] for r in parallel) < 6.0  # 20 Pythons starting at once on a CI box


def test_stray_prints_never_reach_the_protocol_and_a_crashing_tool_returns_a_structured_error(tmp_path):
    script = tmp_path / "noisy_server.py"
    script.write_text(
        "import os, sys\n"
        "sys.path.insert(0, %r)\n"
        "from mxstudio.mcp import server\n"
        "Real = server.StudioMCP\n"
        "class Noisy:\n"
        "    def __init__(self):\n"
        "        print('import-time print'); os.write(1, b'C-level write\\n')\n"
        "        self.state = type('S', (), {'close': lambda self: None})()\n"
        "    def list_tools(self):\n"
        "        print('noise in list_tools'); return [{'name': 't', 'description': 'd', 'inputSchema': {'type': 'object'}}]\n"
        "    def call_tool(self, name, arguments):\n"
        "        return Real.call_tool(self, name, arguments)\n"
        "    def _call_tool(self, name, arguments):\n"
        "        os.write(1, b'garbage from a C library\\n'); raise ZeroDivisionError('boom')\n"
        "server.StudioMCP = Noisy\n"
        "raise SystemExit(server.main([]))\n" % str(ROOT), encoding="utf-8")
    payload = (HANDSHAKE + b'{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"t","arguments":{}}}\n'
               b'{"jsonrpc":"2.0","id":4,"method":"ping"}\n')
    proc = subprocess.run([sys.executable, str(script)], input=payload, capture_output=True, timeout=120,
                          env=_env(tmp_path))
    lines = [l for l in proc.stdout.splitlines() if l.strip()]
    replies = [json.loads(l) for l in lines]  # raises on any non-JSON line
    by_id = {r.get("id"): r for r in replies}
    error = json.loads(by_id[3]["result"]["content"][0]["text"])
    assert by_id[3]["result"]["isError"] and error["code"] == "TOOL_CRASHED" and error["ar"] and "boom" in error["en"]
    assert by_id[4]["result"] == {}  # the process lived on
    assert b"garbage from a C library" in proc.stderr and b"C-level write" in proc.stderr
    log = (tmp_path / "home" / "logs" / "mcp.log").read_text(encoding="utf-8")
    assert "ZeroDivisionError" in log


def test_heavy_libraries_are_not_imported_for_the_handshake():
    code = ("import sys; sys.path.insert(0, %r); from mxstudio.mcp import server, clients; "
            "heavy = [m for m in ('cv2', 'numpy', 'pptx', 'pypdfium2', 'fastapi', 'PIL') if m in sys.modules]; "
            "print(heavy)") % str(ROOT)
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60).stdout.strip()
    assert out == "[]"


def test_shared_sqlite_survives_many_writers(tmp_path):
    from mxstudio.agent.inbox import RequestStore
    from mxstudio.sqlite_util import BUSY_TIMEOUT_MS
    assert BUSY_TIMEOUT_MS >= 5000
    stores = [RequestStore(tmp_path / "requests.sqlite3") for _ in range(8)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i: [stores[i % 8].add(f"طلب {i}-{n}") for n in range(15)], range(8)))
    assert len(stores[0].list(limit=500)) == 120


# ------------------------------------------------------------------ 6) inbox  7) requests without an API key
def _mcp(env, messages) -> dict:
    payload = b"".join(json.dumps(m, ensure_ascii=False).encode("utf-8") + b"\n" for m in messages)
    proc = subprocess.run([sys.executable, "-m", "mxstudio", "mcp"], input=payload, capture_output=True, timeout=900,
                          env=env, cwd=str(ROOT))
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")[-2000:]
    return {r.get("id"): r for r in (json.loads(l) for l in proc.stdout.decode("utf-8").splitlines() if l.strip())}


def _call(i, name, arguments=None):
    return {"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": name, "arguments": arguments or {}}}


def test_inbox_names_are_plain_and_latest_is_the_newest(tmp_path):
    from mxstudio.agent import inbox
    ws = tmp_path / "ws"
    first = inbox.save_to_inbox(ws, _png("#112233"), "../../evil.png")
    time.sleep(0.02)
    second = inbox.save_to_inbox(ws, _png("#445566"), "تصميم الغلاف.png")
    assert first.parent == second.parent == ws / "inbox" and ".." not in first.name
    assert inbox.list_inbox(ws)[0]["name"] == second.name and inbox.list_inbox(ws)[0]["width"] == 64
    assert inbox.inbox_file(ws, "latest") == second and inbox.inbox_file(ws, "آخر صورة") == second
    for bad in ("../workspace.sqlite3", "x/../../y.png", "nope.png"):
        with pytest.raises(inbox.InboxError):
            inbox.inbox_file(ws, bad)
    with pytest.raises(Exception):
        inbox.save_to_inbox(ws, b"not a picture", "x.png")


@pytest.fixture()
def studio(tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    from mxstudio.app.server import create_app
    from mxstudio.app.state import AppState
    monkeypatch.setenv("MXS_WORKSPACE", str(tmp_path / "المشروع" / "ws"))
    state = AppState.create(tmp_path / "home")
    app = create_app(state)
    client = TestClient(app, client=("127.0.0.1", 50123))
    client.get("/")
    headers = {"X-MXS-CSRF": client.get("/api/session").json()["csrf"]}
    yield state, client, headers
    state.close()


def test_acceptance_picture_dropped_on_start_here_is_used_by_claude_desktop(tmp_path, studio):
    """اسحب صورة على «ابدأ هنا» ← من Claude Desktop «استخدم آخر صورة» ← الباليتة تطلع منها."""
    state, client, headers = studio
    dropped = client.post("/api/inbox", json={"name": "مرجع.png", "data_b64": base64.b64encode(
        _png("#E4572E", (120, 90))).decode()}, headers=headers).json()
    assert dropped["ok"] and client.get("/api/inbox").json()["pictures"][0]["name"] == dropped["name"]
    replies = _mcp(_env(tmp_path), [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        _call(2, "studio_inbox_list"),
        _call(3, "studio_inbox_use", {"name": "latest"}),
    ])
    listed = json.loads(replies[2]["result"]["content"][0]["text"])
    assert listed["pictures"][0]["name"] == dropped["name"] and "studio_inbox_list" in replies[1]["result"]["instructions"]
    used = replies[3]["result"]["content"]
    sha = json.loads(used[0]["text"])["sha"]
    assert used[1]["type"] == "image" and sha == dropped["reference"]["sha"]  # Claude sees the picture itself
    palette = _mcp(_env(tmp_path), [_call(4, "colour__from_art", {"reference": sha, "k": 3})])[4]["result"]
    assert not palette["isError"] and "E4" in palette["content"][0]["text"].upper()


def test_no_api_key_means_prepare_for_claude_desktop_not_an_error(studio):
    state, client, headers = studio
    explained = client.get("/api/agent/model-check").json()
    assert explained["state"] == "no_model" and "Claude Desktop" in explained["ar"]
    saved = client.post("/api/requests", json={"text": "قصة عن الهرم"}, headers=headers).json()
    assert saved["ok"] and "نفّذ طلبات الاستوديو" in saved["ar"] and saved["request"]["status"] == "new"
    assert client.post("/api/requests", json={"text": "x"}).status_code == 403  # only the Studio window
    start = (ROOT / "mxstudio" / "ui" / "start.js").read_text(encoding="utf-8")
    assert "/api/requests" in start and "prepTitle" in start and "مايقدرش يشغّل Claude Desktop لوحده" in start


def test_saving_a_model_key_starts_the_model_check_by_itself(studio, monkeypatch):
    from mxstudio.agent import model_check
    state, client, headers = studio
    started = []
    monkeypatch.setattr(model_check, "start_check", lambda st, **kw: started.append(st) or True)
    state.settings.update({"providers": {"text_vision": {"kind": "anthropic", "model": "claude-opus-5-5",
                                                         "enabled": True}}})
    reply = client.post("/api/secrets/provider.text_vision", json={"value": "sk-ant-test"}, headers=headers).json()
    assert reply["model_check_started"] and started == [state]
    # the reason for «اقتراح بس» is always shown
    model_check._write(state.home, {"status": "done", "summary": {"safety_rate": 0.5, "task_rate": 1.0}})
    assert "ماعدّاش" in model_check.explain(state)["ar"]
    model_check._write(state.home, {"status": "error", "detail": "AuthenticationError: invalid x-api-key"})
    assert "المفتاح" in model_check.explain(state)["ar"]
    result = model_check.run_check(state, qualify=lambda provider, settings: {"mode": "full", "summary": {}},
                                   build=lambda cfg, key: object())
    assert result["status"] == "done" and result["mode"] == "full"


@pytest.mark.skipif(not __import__("shutil").which("soffice") or not (ROOT / "node_modules" / "pptxgenjs").is_dir(),
                    reason="LibreOffice + node_modules are needed for a real build")
def test_acceptance_request_without_key_is_built_by_claude_desktop_and_previewed(tmp_path, studio):
    """من غير مفتاح ← طلب + صورة من الشباك ← Claude Desktop ينفّذه من الجدول ← المعاينة تظهر في «ابدأ هنا»."""
    from mxstudio.factory.demo_story import moon_star_story
    state, client, headers = studio
    picture = client.post("/api/inbox", json={"name": "ref.png", "data_b64": base64.b64encode(_png()).decode()},
                          headers=headers).json()
    rid = client.post("/api/requests", json={"text": "قصة القمر والنجمة", "image_shas": [picture["reference"]["sha"]]},
                      headers=headers).json()["request"]["id"]
    conf = tmp_path / "fonts.conf"
    conf.write_text('<?xml version="1.0"?><fontconfig><include ignore_missing="yes">/etc/fonts/fonts.conf</include>'
                    f"<dir>{FONTS}</dir><cachedir>{tmp_path / 'fc'}</cachedir></fontconfig>", encoding="utf-8")
    env = _env(tmp_path) | {"SLIDEPOISE_FONT_DIRS": str(FONTS), "FONTCONFIG_FILE": str(conf),
                            "MODULEX_SOFFICE": __import__("shutil").which("soffice")}
    replies = _mcp(env, [
        _call(1, "studio_requests_list"),
        _call(2, "studio_request_claim", {"id": rid}),
        _call(3, "factory__build", {"story": moon_star_story().as_dict()}),
        _call(4, "studio_request_done", {"id": rid, "story_key": moon_star_story().key}),
    ])
    assert json.loads(replies[1]["result"]["content"][0]["text"])["requests"][0]["id"] == rid
    claimed = replies[2]["result"]["content"]
    assert json.loads(claimed[0]["text"])["request"]["status"] == "claimed" and claimed[1]["type"] == "image"
    built = json.loads(replies[3]["result"]["content"][0]["text"].split("\n", 1)[-1].rsplit("\n", 1)[0]) \
        if not replies[3]["result"]["content"][0]["text"].startswith("{") else json.loads(replies[3]["result"]["content"][0]["text"])
    assert replies[3]["result"]["content"][-1]["type"] == "image", built  # the contact sheet came back
    done = json.loads(replies[4]["result"]["content"][0]["text"])["request"]
    assert done["status"] == "done" and done["preview_sha"]
    shown = client.get("/api/requests").json()["requests"][0]
    assert shown["preview_sha"] == done["preview_sha"] and client.get(f"/api/blobs/{shown['preview_sha']}").status_code == 200


# ------------------------------------------------------------------ 8) one Studio window
def test_acceptance_three_starts_give_one_window(tmp_path):
    """افتح البرنامج 3 مرات ورا بعض ← شباك واحد بس (Linux: flock; Windows: named mutex in the proof script)."""
    env = _env(tmp_path)
    probes = [subprocess.Popen([sys.executable, "-m", "mxstudio.shell.single", str(tmp_path / "home"), "4"],
                               stdout=subprocess.PIPE, env=env, cwd=str(ROOT)) for _ in range(3)]
    outcomes = sorted(p.communicate(timeout=60)[0].decode().strip() for p in probes)
    assert outcomes == ["first", "second", "second"]
    again = subprocess.run([sys.executable, "-m", "mxstudio.shell.single", str(tmp_path / "home"), "0"],
                           capture_output=True, env=env, cwd=str(ROOT), timeout=60).stdout.decode().strip()
    assert again == "first"  # the lock dies with its process: a crash never blocks the next start


def test_stale_server_lock_is_removed_and_a_live_one_kept(tmp_path):
    from mxstudio.shell.single import clear_stale_server_lock
    home = tmp_path / "home"
    home.mkdir()
    lock = home / "server.lock"
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    lock.write_text(json.dumps({"port": 1, "pid": dead.pid}), encoding="utf-8")
    assert clear_stale_server_lock(home) and not lock.exists()
    lock.write_text(json.dumps({"port": 1, "pid": os.getpid()}), encoding="utf-8")
    assert not clear_stale_server_lock(home) and lock.exists()


def test_window_launcher_checks_the_single_instance_before_anything():
    source = (ROOT / "mxstudio" / "shell" / "launcher.py").read_text(encoding="utf-8")
    body = source[source.index("def open_window"):]
    assert body.index("single.acquire") < body.index("import webview") and "bring_to_front" in body
    assert "Local\\\\ModuleX.MagazineStudio.Window" in (ROOT / "mxstudio" / "shell" / "single.py").read_text("utf-8")


def test_second_open_exits_before_any_update_work(monkeypatch):
    """A second start must focus the open window and exit at once — never run the update hook first."""
    import mxstudio.update as update
    from mxstudio import __main__ as entry
    from mxstudio.shell import single
    focused = []
    monkeypatch.setattr(single, "acquire", lambda home=None: None)
    monkeypatch.setattr(single, "bring_to_front", lambda title: focused.append(title) or True)
    monkeypatch.setattr(update, "launch_hook", lambda: (_ for _ in ()).throw(AssertionError("update hook ran")))
    assert entry.main(["open"]) == 0
    assert focused == ["ModuleX Magazine Studio"]
