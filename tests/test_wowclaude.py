import tempfile
from pathlib import Path

from PIL import Image

from wowclaude import claude, decode, installer


def make_strip(text: str, cell: int = 4) -> Image.Image:
    """Render a strip exactly like the addon does, so the decoder can be tested without the game."""
    body = text.encode("utf-8")
    s = 0
    for b in body:
        s = (s * 31 + b) % 16777216
    data = bytearray(len(body).to_bytes(4, "little") + s.to_bytes(4, "little") + body)
    while len(data) % 3:
        data.append(0)
    cells = list(decode.MAGIC) + [tuple(data[i:i + 3]) for i in range(0, len(data), 3)]
    img = Image.new("RGB", (700, 200), (20, 20, 20))
    for i, rgb in enumerate(cells):
        x, y = (i % decode.COLS) * cell, (i // decode.COLS) * cell
        for dx in range(cell):
            for dy in range(cell):
                img.putpixel((x + 30 + dx, y + 10 + dy), rgb)  # strip not at the corner: must still be found
    return img


def test_decode_message_and_state():
    text = "#ver|25\n#msg|123|7|Hello | pipe\n#edit|1\n#ctx|Name|Level 5"
    st = decode.decode(make_strip(text))
    assert st.addon_version == 25
    assert (st.message_seq, st.message) == (123, "Hello | pipe")
    assert st.edit_active
    assert "Level 5" in st.context


def test_decode_every_cell_size():
    import pytest
    text = "#ver|26\n#msg|55|2|tiny strip | works\n#ack|50\n#ctx|A|B|C"
    for cell in (1, 2, 3, 4):
        st = decode.decode(make_strip(text, cell))
        assert st is not None, cell
        assert (st.message_seq, st.message) == (55, "tiny strip | works")


def test_decode_rejects_bad_checksum():
    img = make_strip("#msg|1|1|x")
    for dx in range(4):
        for dy in range(4):
            img.putpixel((30 + 11 * 4 + dx, 10 + dy), (1, 2, 3))  # corrupt a payload cell
    assert decode.decode(img) is None


def test_decode_none_without_strip():
    assert decode.decode(Image.new("RGB", (700, 200), (0, 0, 0))) is None


def test_split_and_overlay():
    text, ov = claude.extract_overlay("Short.\n[[overlay Plan|30]]\nline\n[bar 0.5 00ff00] half\n[[/overlay]]")
    assert text == "Short." and ov["title"] == "Plan" and ov["secs"] == 30 and len(ov["lines"]) == 2
    parts = claude.split_reply("word " * 400)
    assert len(parts) <= claude.MAX_CHUNKS and all(len(p) <= claude.CHUNK for p in parts)


def test_command_backend(monkeypatch, tmp_path):
    import sys
    from wowclaude import backends, config
    monkeypatch.setattr(config, "HOME", tmp_path)
    monkeypatch.setattr(config, "CONFIG", tmp_path / "config.json")
    script = tmp_path / "echo.py"
    script.write_text("import sys; t = sys.stdin.read(); print('GOT:' + ('hello there' in t and 'hello there' or 'nothing'))", encoding="utf-8")
    config.save({"backend": "command", "command": [sys.executable, str(script)]})
    assert backends.check()[0]
    session = claude.Session()
    answer = session.ask("hello there")
    assert answer == "GOT:hello there"
    assert session.history[0][0] == "hello there" or session.history[0][0].startswith("hello there")


def test_openai_compatible_backend(monkeypatch, tmp_path):
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from wowclaude import backends, config
    seen = {}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            seen["path"] = self.path
            seen["auth"] = self.headers.get("Authorization")
            seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            out = json.dumps({"choices": [{"message": {"content": " Pong "}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(config, "HOME", tmp_path)
    monkeypatch.setattr(config, "CONFIG", tmp_path / "config.json")
    config.save({"backend": "deepseek", "base_url": f"http://127.0.0.1:{srv.server_port}/v1", "api_key": "k123"})
    assert backends.check()[0]
    session = claude.Session()
    assert session.ask("ping") == "Pong"
    assert seen["path"] == "/v1/chat/completions" and seen["auth"] == "Bearer k123"
    assert seen["body"]["model"] == "deepseek-chat" and seen["body"]["messages"][-1]["content"].startswith("ping")
    srv.shutdown()


def test_api_backend_needs_key(monkeypatch, tmp_path):
    from wowclaude import backends, config
    monkeypatch.setattr(config, "CONFIG", tmp_path / "config.json")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    config.save({"backend": "deepseek"})
    ok, msg = backends.check()
    assert not ok and "DEEPSEEK_API_KEY" in msg


def test_unknown_backend_reports(monkeypatch, tmp_path):
    from wowclaude import backends, config
    monkeypatch.setattr(config, "CONFIG", tmp_path / "config.json")
    config.save({"backend": "nope"})
    assert not backends.check()[0]


def test_no_private_details_in_sources():
    import re
    # generic patterns live here; the maintainer's own names are kept OUT of the repository, in a local file
    words = [r"C:\\\\Users", r"C:\\Users", r"\.claude[/\\]", "@gmail", "@proton"]
    private = Path.home() / ".wowclaude" / "private-words.txt"  # one word per line, never committed
    if private.exists():
        words += [re.escape(w.strip()) for w in private.read_text(encoding="utf-8").splitlines() if w.strip()]
    bad = re.compile("(" + "|".join(words) + ")", re.I)
    for f in Path(__file__).parent.parent.rglob("*"):
        if f.suffix in (".py", ".lua", ".toc", ".md", ".bat", ".toml") and f.name != "test_wowclaude.py":
            hit = bad.search(f.read_text(encoding="utf-8", errors="replace"))
            assert not hit, f"{f}: {hit.group(0)}"


def test_overlay_place_corners(monkeypatch):
    from wowclaude import overlay
    monkeypatch.setattr(overlay, "game_rect", lambda: (100, 50, 1100, 650))
    assert overlay.place(400, 200, "br", 10) == (690, 440)
    assert overlay.place(400, 200, "tl", 10) == (110, 100)


def test_extract_play():
    from wowclaude import claude
    text, url = claude.extract_play("Bitte. [[play https://www.youtube.com/watch?v=abc]]")
    assert url == "https://www.youtube.com/watch?v=abc" and text == "Bitte."
    assert claude.extract_play("zu. [[play off]]")[1] == "off"
    assert claude.extract_play("[[play file:///c:/x.exe]]")[1] is None
    assert claude.extract_play("[[play http://evil]]")[1] is None


def test_vinput_extract_limits_and_validates():
    from wowclaude import vinput
    text, cmds = vinput.extract("ok [[click 100 200]] [[keys {Esc}]] [[click 1 2 R]] [[click x y]] [[keys " + "a" * 100 + "]]")
    assert cmds == ["click 100 200", "keys {Esc}", "click 1 2 R"]
    assert "[[click x y]]" in text
    assert len(vinput.extract("[[click 1 1]]" * 9)[1]) == vinput.MAX_ACTIONS


def test_overlay_compose_is_transparent_in_the_middle():
    from wowclaude import overlay
    im = overlay.compose(300, 200, overlay.TOP)
    assert im.size == (300, 200)
    assert im.getpixel((150, 120))[3] == 0          # browser area: see-through
    assert any(im.getpixel((150, y))[3] > 0 for y in range(0, 9))  # border is drawn (works with generated art too)
    assert overlay.label_width() > 40


def test_bridge_command_browser(monkeypatch):
    from wowclaude import bridge, overlay
    seen = []
    monkeypatch.setattr(overlay, "play", lambda a: seen.append(a))
    assert bridge.handle_command("!browser") == "Browser opened."
    assert bridge.handle_command("!browser https://x.y") == "Browser opened."
    assert bridge.handle_command("!browser off") == "Browser closed."
    assert seen == ["", "https://x.y", "off"]
    assert bridge.handle_command("!unknown") is None


def test_setup_ui_apply_and_state(tmp_path, monkeypatch):
    from wowclaude import config, setup_ui
    monkeypatch.setattr(config, "HOME", tmp_path)
    monkeypatch.setattr(config, "CONFIG", tmp_path / "config.json")
    monkeypatch.setattr(config, "PERSONA", tmp_path / "persona.txt")
    monkeypatch.delenv("WOWCLAUDE_BACKEND", raising=False)
    out = setup_ui.apply({"backend": "openrouter", "model": "x/y", "api_key": "sk-test", "name": "Gorel", "persona": "Be brief."})
    assert out["ok"] and out["has_key"]
    cfg = config.load()
    assert cfg["backend"] == "openrouter" and cfg["model"] == "x/y" and cfg["api_key"] == "sk-test"
    assert cfg["name"] == "Gorel" and (tmp_path / "persona.txt").read_text(encoding="utf-8").strip() == "Be brief."
    st = setup_ui._state()
    assert st["name"] == "Gorel" and st["persona"] == "Be brief."
    assert st["backend"] == "openrouter" and st["has_key"] and "api_key" not in st
    assert setup_ui.apply({"backend": "nope"})["ok"] is False
    # empty key keeps the saved one, empty persona removes the file
    setup_ui.apply({"backend": "openrouter", "api_key": "", "persona": ""})
    assert config.load()["api_key"] == "sk-test" and not (tmp_path / "persona.txt").exists()


def test_setup_page_requires_token():
    import urllib.error
    import urllib.request
    from wowclaude import setup_ui
    url = setup_ui.start_background()
    base = url.split("?")[0]
    try:
        urllib.request.urlopen(base + "state", timeout=3)
        assert False, "must be forbidden without token"
    except urllib.error.HTTPError as exc:
        assert exc.code == 403
    assert b"AI setup" in urllib.request.urlopen(url, timeout=3).read()


def test_pin_does_not_touch_window_every_tick(monkeypatch):
    """Regression: re-applying style/region/position every 250 ms made the browser page blink."""
    from wowclaude import overlay
    calls = []

    class Fake:
        def __getattr__(self, name):
            def fn(*a, **k):
                calls.append(name)
                return 0
            fn.argtypes = None
            return fn

    fake = Fake()
    fake.SetWindowPos = type("F", (), {"argtypes": None, "__call__": lambda self, *a, **k: calls.append("SetWindowPos")})()
    monkeypatch.setattr(overlay, "user32", fake)
    monkeypatch.setattr(overlay.ctypes, "windll", type("W", (), {"gdi32": fake})(), raising=False)
    overlay._pinned.clear()
    overlay.pin(1, 10, 10, 400, 300, 100, False)
    first = calls.count("SetWindowPos")
    for _ in range(15):
        overlay.pin(1, 10, 10, 400, 300, 100, False)
    assert first == 1 and calls.count("SetWindowPos") == 1
    overlay.pin(1, 20, 10, 400, 300, 100, False)  # a real change is applied immediately
    assert calls.count("SetWindowPos") == 2


def test_window_geometry_follows_game_window():
    from wowclaude import overlay
    g = (100, 50, 1700, 950)  # game client 1600x900
    rel = overlay.to_rel(g, 500, 300, 640, 360)
    assert overlay.from_rel(g, rel) == (500, 300, 640, 360)
    g2 = (0, 0, 800, 450)  # game window shrunk to half and moved
    x, y, w, h = overlay.from_rel(g2, rel)
    assert (x, y) == (round(0 + rel[0] * 800), round(0 + rel[1] * 450)) and w == 320 and h == 180
    g3 = (0, 0, 300, 200)  # tiny game window: the browser never gets smaller than the minimum
    assert overlay.from_rel(g3, rel)[2:] == (overlay.MIN_W, overlay.MIN_H)


def test_shipped_textures_are_used_and_own_ones_win(tmp_path, monkeypatch):
    from wowclaude import overlay
    shipped = Path(overlay.__file__).parent / "art"
    assert (shipped / "UI-DialogBox-Border.png").is_file()
    monkeypatch.setattr(overlay.config, "HOME", tmp_path)
    overlay._art_cache.clear()
    assert overlay._art("UI-DialogBox-Border.png").size == __import__("PIL.Image", fromlist=["Image"]).open(shipped / "UI-DialogBox-Border.png").size
    overlay._art_cache.clear()


def test_frame_art_is_generated_without_game_files(tmp_path, monkeypatch):
    """No game textures ship with the package: every frame image can be drawn from code."""
    from wowclaude import frame_art, overlay
    monkeypatch.setattr(overlay.config, "HOME", tmp_path)
    monkeypatch.setattr(overlay, "PACKAGED_ART", tmp_path / "no-art")  # as if the textures were not shipped
    overlay._art_cache.clear()
    for name in frame_art.NAMES:
        im = overlay._art(name)
        assert im.mode == "RGBA" and im.size[0] > 0
    assert overlay.compose(500, 300, overlay.TOP).size == (500, 300)
    assert overlay.slot_sprite("hover").size == (64, 64)
    overlay._art_cache.clear()


def test_own_texture_overrides_generated(tmp_path, monkeypatch):
    from PIL import Image
    from wowclaude import overlay
    monkeypatch.setattr(overlay.config, "HOME", tmp_path)
    (tmp_path / "art").mkdir()
    Image.new("RGBA", (64, 64), (1, 2, 3, 255)).save(tmp_path / "art" / "INV_Misc_Map_01.png")
    overlay._art_cache.clear()
    assert overlay._art("INV_Misc_Map_01.png").getpixel((5, 5)) == (1, 2, 3, 255)
    overlay._art_cache.clear()


def _lua_addon():
    pytest = __import__("pytest")
    pytest.importorskip("lupa")
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    import lua_harness
    return lua_harness, lua_harness.run_addon(Path(installer.ADDON_SRC) / "KKMap.lua")


def test_lua_addon_strip_is_read_by_python_decoder():
    """Contract test: the REAL KKMap.lua (run in a fake WoW API) draws a strip that decode.py understands."""
    h, lua = _lua_addon()
    st = decode.decode(h.strip_image(lua))
    assert st is not None and st.addon_version == 25
    assert "Tester" in st.context and "Fehler" not in st.context


def test_lua_addon_sends_a_message_through_the_strip():
    h, lua = _lua_addon()
    lua.eval("function() SlashCmdList['KKCHAT']('Hello Welt, wie komme ich nach Undercity?') end")()
    st = decode.decode(h.strip_image(lua))
    assert st.message == "Hello Welt, wie komme ich nach Undercity?" and st.message_seq > 0


def test_lua_menu_commands_become_bang_messages():
    h, lua = _lua_addon()
    lua.eval("function() SlashCmdList['KKBROWSER']('https://example.org') end")()
    st = decode.decode(h.strip_image(lua))
    assert st.message == "!browser https://example.org"


def test_client_detection_accepts_classic_exe(tmp_path):
    from wowclaude import config
    (tmp_path / "Interface" / "AddOns").mkdir(parents=True)
    assert not config._is_client(tmp_path)
    (tmp_path / "WowClassic.exe").write_bytes(b"")
    assert config._is_client(tmp_path)


def test_session_timeout_is_reported_and_session_renewed(tmp_path, monkeypatch):
    import subprocess
    from wowclaude import config
    monkeypatch.setattr(config, "HOME", tmp_path)
    monkeypatch.setattr(config, "SESSION", tmp_path / "session.txt")
    monkeypatch.setattr(claude, "claude_path", lambda: "claude")
    from wowclaude import backends
    monkeypatch.setattr(backends, "name", lambda: "claude")

    def boom(*a, **k):
        raise claude.AskTimeout("Claude did not answer within 1 seconds.")

    monkeypatch.setattr(claude, "_exec", boom)
    s = claude.Session()
    first = s.id
    try:
        s.ask("hi")
        assert False, "should raise"
    except RuntimeError as exc:
        assert "did not answer" in str(exc)
    assert s.id != first  # the aborted run may have claimed the id: never reuse it


def test_window_on_unplugged_monitor_is_detected(monkeypatch):
    from wowclaude import overlay

    class U:
        def GetSystemMetrics(self, i):
            return {76: 0, 77: 0, 78: 2560, 79: 1440}[i]

    monkeypatch.setattr(overlay, "user32", U())
    assert overlay._on_screen(100, 100, 640, 520)
    assert not overlay._on_screen(4000, 100, 640, 520)  # was on a second monitor that is gone
    assert not overlay._on_screen(-3000, 50, 640, 520)


def test_play_reports_why_the_browser_did_not_open(monkeypatch, tmp_path):
    from wowclaude import bridge, overlay
    monkeypatch.setattr(overlay, "play", lambda url, size=None: "No Chrome/Edge/Brave found.")
    assert bridge.handle_command("!browser").startswith("Browser did not open: No Chrome")
    monkeypatch.setattr(overlay, "play", lambda url, size=None: "")
    assert bridge.handle_command("!browser") == "Browser opened."


def test_claude_gets_system_prompt_as_file(monkeypatch, tmp_path):
    """Multi-line system prompts must not travel as a command-line argument (.cmd wrappers cut at the first newline)."""
    from wowclaude import claude, config
    monkeypatch.setattr(config, "HOME", tmp_path)
    seen = {}

    def fake_run(cmd, prompt, timeout=None):
        seen["cmd"] = cmd
        return 0, "ok", ""
    monkeypatch.setattr(claude, "_exec", fake_run)
    s = claude.Session.__new__(claude.Session)
    s.history, s.id, s.started = [], "id-1", False
    assert s._run("claude", "hi", None) == "ok"
    cmd = seen["cmd"]
    assert "--append-system-prompt-file" in cmd and "--append-system-prompt" not in cmd
    assert (tmp_path / "system_prompt.txt").read_text(encoding="utf-8").count("\n") > 3


def test_timeout_is_not_retried(monkeypatch, tmp_path):
    import subprocess
    from wowclaude import backends, claude, config
    monkeypatch.setattr(config, "HOME", tmp_path)
    monkeypatch.setattr(config, "SESSION", tmp_path / "session.txt")
    monkeypatch.setattr(claude, "claude_path", lambda: "claude")
    monkeypatch.setattr(backends, "name", lambda: "claude")
    calls = []

    def boom(*a, **k):
        calls.append(1)
        raise claude.AskTimeout("Claude did not answer within 1 seconds.")
    monkeypatch.setattr(claude, "_exec", boom)
    try:
        claude.Session().ask("hi")
        assert False, "should raise"
    except claude.AskTimeout:
        pass
    assert len(calls) == 1 and claude.TIMEOUT < 120


def test_expired_login_gets_a_clear_message(monkeypatch, tmp_path):
    from wowclaude import backends, claude, config
    monkeypatch.setattr(config, "HOME", tmp_path)
    monkeypatch.setattr(config, "SESSION", tmp_path / "session.txt")
    monkeypatch.setattr(claude, "claude_path", lambda: "claude")
    monkeypatch.setattr(backends, "name", lambda: "claude")

    monkeypatch.setattr(claude, "_exec", lambda *a, **k: (1, "", "OAuth session expired"))
    try:
        claude.Session().ask("hi")
        assert False, "should raise"
    except RuntimeError as exc:
        assert "log in again" in str(exc)


def test_native_claude_exe_preferred(monkeypatch, tmp_path):
    import sys
    from wowclaude import claude, config
    if sys.platform != "win32":
        return
    exe = tmp_path / ".local" / "bin" / "claude.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("x")
    monkeypatch.delenv("WOWCLAUDE_CLAUDE", raising=False)
    monkeypatch.setattr(config, "load", lambda: {})
    monkeypatch.setattr(claude.Path, "home", classmethod(lambda cls: tmp_path))
    assert claude.claude_path() == str(exe)


def test_exec_kills_on_timeout(monkeypatch):
    import sys
    from wowclaude import claude
    monkeypatch.setattr(claude, "TIMEOUT", 1)
    import time
    t0 = time.time()
    try:
        claude._exec([sys.executable, "-c", "import time; time.sleep(30)"], "x")
        assert False, "should raise"
    except claude.AskTimeout:
        pass
    assert time.time() - t0 < 10


def test_failed_retry_never_keeps_a_burnt_session_id(monkeypatch):
    from wowclaude import backends, claude, config
    monkeypatch.setattr(claude, "claude_path", lambda: "claude")
    monkeypatch.setattr(backends, "name", lambda: "claude")
    calls = []

    def fake(cmd, prompt, timeout=None):
        calls.append(cmd)
        if len(calls) == 1:
            return 0, "fine", ""                       # first question works, session is started
        raise claude.AskTimeout("too slow")           # later: timeout
    monkeypatch.setattr(claude, "_exec", fake)
    s = claude.Session()
    assert s.ask("one") == "fine" and s.started
    monkeypatch.setattr(claude, "_exec", lambda *a, **k: (1, "", "No conversation found with session ID"))
    seen = []
    orig_new = s._new
    monkeypatch.setattr(s, "_new", lambda: (seen.append(1), orig_new())[1])
    try:
        s.ask("two")
        assert False, "should raise"
    except RuntimeError:
        pass
    assert seen and not s.started and s.id  # fresh id after a failed retry, never the burnt one


def test_lua_long_utf8_message_is_cut_on_a_character_boundary():
    h, lua = _lua_addon()
    lua.eval("function() SlashCmdList['KKCHAT']('" + "ä" * 200 + "') end")()
    st = decode.decode(h.strip_image(lua))
    assert st.message and len(st.message.encode("utf-8")) <= 230
    assert set(st.message) == {"ä"}  # no broken half characters


def test_check_login_uses_safe_exec(monkeypatch):
    from wowclaude import backends, claude
    monkeypatch.setattr(backends, "name", lambda: "claude")
    monkeypatch.setattr(claude, "claude_path", lambda: "claude")
    seen = {}

    def fake(cmd, prompt, timeout=None):
        seen["cmd"] = cmd
        return 0, "ok", ""
    monkeypatch.setattr(claude, "_exec", fake)
    assert claude.check_login()[0] is True
    assert "--no-session-persistence" in seen["cmd"] and "--strict-mcp-config" in seen["cmd"]
    monkeypatch.setattr(claude, "_exec", lambda *a, **k: (1, "", "OAuth session expired"))
    ok, msg = claude.check_login()
    assert ok is False and "log in once" in msg


def test_retry_only_for_stale_sessions_and_session_id_always_renewed(monkeypatch):
    from wowclaude import backends, claude
    monkeypatch.setattr(claude, "claude_path", lambda: "claude")
    monkeypatch.setattr(backends, "name", lambda: "claude")
    ids = []

    def run(err):
        def fake(cmd, prompt, timeout=None):
            ids.append(cmd[cmd.index("--session-id") + 1] if "--session-id" in cmd else cmd[cmd.index("--resume") + 1])
            if err is None:
                return 0, "fine", ""
            return 1, "", err
        return fake
    monkeypatch.setattr(claude, "_exec", run(None))
    s = claude.Session()
    assert s.ask("one") == "fine" and s.started

    monkeypatch.setattr(claude, "_exec", run("Session limit reached"))   # NOT a stale session: no retry, no data loss
    n = len(ids)
    s_id = s.id
    try:
        s.ask("two"); assert False
    except RuntimeError:
        pass
    assert len(ids) == n + 1 and s.id == s_id and s.started

    monkeypatch.setattr(claude, "_exec", run("No conversation found with session ID x"))  # stale: one retry
    n = len(ids)
    try:
        s.ask("three"); assert False
    except RuntimeError:
        pass
    assert len(ids) == n + 2
    burnt = ids[-1]
    assert not s.started and s.id != burnt  # the id of the failed retry is never reused


def test_only_one_bridge_can_run(monkeypatch):
    from wowclaude import bridge
    monkeypatch.setattr(bridge, "LOCK_PORT", 47999)
    first = bridge.acquire_lock()
    try:
        assert first is not None
        assert bridge.acquire_lock() is None
    finally:
        first.close()
    again = bridge.acquire_lock()  # freed again after the first one ends
    assert again is not None
    again.close()


def test_lua_cut_uses_whole_characters_for_3_and_4_byte_text():
    h, lua = _lua_addon()
    for ch in ("€", "😀"):
        lua.eval("function() DEFAULT_CHAT_FRAME.__log = nil; SlashCmdList['KKCHAT']('" + ch * 120 + "') end")()
        st = decode.decode(h.strip_image(lua))
        assert st.message and len(st.message.encode("utf-8")) <= 230
        assert set(st.message) == {ch}, f"half character left for {ch!r}"
        shown = " ".join(str(x) for x in lua.eval("rawget(DEFAULT_CHAT_FRAME, '__log') or {}").values())
        assert "shortened" in shown or "gekuerzt" in shown  # the player is told


def _deliver_env(monkeypatch, tmp_path, fresh_state):
    from wowclaude import bridge
    monkeypatch.setattr(bridge.time, "sleep", lambda s: None)
    ticks = iter(range(0, 100000))
    monkeypatch.setattr(bridge.time, "time", lambda: next(ticks))
    monkeypatch.setattr(bridge.slots, "publish", lambda *a, **k: None)
    silenced = []
    monkeypatch.setattr(bridge.slots, "reset_marker", lambda root, idx: silenced.append(idx))
    monkeypatch.setattr(bridge, "_safe_read_state", lambda: fresh_state)

    class St:
        def __init__(self, seq, ack):
            self.message_seq = seq
    return bridge, St, silenced


def test_backends_use_hard_limit_exec_and_short_api_timeout(monkeypatch, tmp_path):
    import sys
    from wowclaude import backends, claude, config
    config.save({"backend": "command", "command": [sys.executable, "-c", "print(1)"]})
    seen = []
    monkeypatch.setattr(claude, "_exec", lambda cmd, prompt, timeout=None: (seen.append(cmd) or (0, "answer", "")))
    assert backends.ask("sys", [], "q", None) == "answer" and seen
    monkeypatch.setattr(backends.shutil, "which", lambda n: "codex")
    config.save({"backend": "codex"})

    def fake(cmd, prompt, timeout=None):
        out = cmd[cmd.index("-o") + 1]
        Path(out).write_text("from codex", encoding="utf-8")
        seen.append(cmd)
        return 0, "", ""
    monkeypatch.setattr(claude, "_exec", fake)
    assert backends.ask("sys", [], "q", None) == "from codex" and len(seen) == 2
    src = Path(backends.__file__).read_text(encoding="utf-8")
    assert "timeout=180" not in src and "timeout=170" not in src and "subprocess.run" not in src


def test_retry_needs_enough_budget_and_each_stale_pattern_works(monkeypatch):
    from wowclaude import backends, claude
    monkeypatch.setattr(claude, "claude_path", lambda: "claude")
    monkeypatch.setattr(backends, "name", lambda: "claude")
    for text in ("No conversation found with session ID x", "Session ID abc is already in use",
                 "session not found", "invalid session", "unknown session"):
        calls = []

        def fake(cmd, prompt, timeout=None, text=text):
            calls.append(timeout)
            return (0, "fine", "") if len(calls) == 1 else (1, "", text)
        monkeypatch.setattr(claude, "_exec", fake)
        s = claude.Session()
        s.ask("one")
        calls.clear()
        monkeypatch.setattr(claude, "_exec", lambda c, p, timeout=None, text=text: (calls.append(timeout) or (1, "", text)))
        try:
            s.ask("two"); assert False
        except RuntimeError:
            pass
        assert len(calls) == 2, text
    monkeypatch.setattr(claude, "TIMEOUT", 10)  # budget below the 20 s guard: never retry
    calls.clear()
    s = claude.Session(); s.started = True
    try:
        s.ask("three"); assert False
    except RuntimeError:
        pass
    assert len(calls) == 1


def test_timeout_message_names_the_real_limit():
    import sys
    from wowclaude import claude
    try:
        claude._exec([sys.executable, "-c", "import time; time.sleep(30)"], "x", 2)
        assert False
    except claude.AskTimeout as exc:
        assert "2 seconds" in str(exc)


def test_exec_timeout_kills_grandchildren(tmp_path):
    import sys
    import time
    from wowclaude import claude
    if sys.platform != "win32":
        return
    pidfile = tmp_path / "pid.txt"
    code = ("import subprocess, sys, time; "
            f"p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
            f"open(r'{pidfile}', 'w').write(str(p.pid)); time.sleep(60)")
    try:
        claude._exec([sys.executable, "-c", code], "x", 3)
    except claude.AskTimeout:
        pass
    pid = int(pidfile.read_text())
    time.sleep(1)
    import subprocess
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True, encoding="utf-8", errors="replace").stdout or ""
    assert str(pid) not in out, "grandchild still running"


def test_check_login_empty_answer_is_not_ok(monkeypatch):
    from wowclaude import backends, claude
    monkeypatch.setattr(backends, "name", lambda: "claude")
    monkeypatch.setattr(claude, "claude_path", lambda: "claude")
    monkeypatch.setattr(claude, "_exec", lambda *a, **k: (0, "", ""))
    assert claude.check_login()[0] is False


def test_reply_is_limited_to_six_chunks():
    assert claude.MAX_CHUNKS == 6
    parts = claude.split_reply("wort " * 2000)
    assert len(parts) == 6 and all(len(p) <= claude.CHUNK for p in parts) and parts[-1].endswith("(...)")


def test_doctor_saves_a_strip_sample(monkeypatch, tmp_path, capsys):
    from wowclaude import __main__ as cli, config, screen
    h, lua = _lua_addon()
    img = h.strip_image(lua)
    monkeypatch.setattr(screen, "game_running", lambda: True)
    monkeypatch.setattr(screen, "grab_strip_area", lambda: img)
    monkeypatch.setattr(config, "client_root", lambda root=None: tmp_path)

    class A:
        root, deep = None, False
    cli.cmd_doctor(A())
    assert (config.HOME / "strip-sample.png").stat().st_size > 0
    assert "strip sample" in capsys.readouterr().out


def test_run_returns_immediately_when_another_bridge_holds_the_lock(monkeypatch, tmp_path, capsys):
    from wowclaude import bridge
    monkeypatch.setattr(bridge, "LOCK_PORT", 47998)
    held = bridge.acquire_lock()
    try:
        monkeypatch.setattr(bridge.claude, "Session", lambda: (_ for _ in ()).throw(AssertionError("second bridge started")))
        bridge.run(tmp_path)
    finally:
        held.close()
    assert "already running" in capsys.readouterr().out


def test_claude_runs_without_the_players_claude_md(monkeypatch):
    import sys
    from wowclaude import claude
    monkeypatch.delenv("CLAUDE_CODE_DISABLE_CLAUDE_MDS", raising=False)
    code, out, err = claude._exec([sys.executable, "-c",
                                   "import os; print(os.environ.get('CLAUDE_CODE_DISABLE_CLAUDE_MDS'), os.environ.get('CLAUDE_CODE_DISABLE_AUTO_MEMORY'))"], "")
    assert out.strip() == "1 1"


def test_claude_runs_isolated(monkeypatch):
    """No user settings, and not inside the user's profile folder (that would leak the Windows user name)."""
    seen = {}

    class P:
        returncode = 0
        def communicate(self, prompt, timeout=None): return "ok", ""

    def popen(cmd, **kw):
        seen["cmd"], seen["cwd"] = cmd, kw["cwd"]
        return P()
    monkeypatch.setattr(claude.subprocess, "Popen", popen)
    claude._exec(["claude", "-p", *claude.ISOLATION], "hi")
    assert "--setting-sources" in seen["cmd"] and seen["cmd"][seen["cmd"].index("--setting-sources") + 1] == ""
    assert str(claude.config.HOME) not in seen["cwd"] and "Users" not in seen["cwd"]


def test_lua_restricted_frame_does_not_break_the_scan():
    """Secure/protected frames raise on GetLeft ('Can't measure restricted regions'): the strip must still be written."""
    h, lua = _lua_addon()
    lua.execute("""
        local bad = CreateFrame("Button", "SecureThing")
        bad.GetLeft = function() error("Can't measure restricted regions") end
        bad.IsVisible = function() return true end
        function EnumerateFrames(f) if f == nil then return bad end return nil end
    """)
    lua.eval("function() SlashCmdList['KKCHAT']('was ist?') end")()   # a pending question turns the frame scan on
    st = decode.decode(h.strip_image(lua))
    assert st is not None and st.message == "was ist?"
    shown = [str(x) for x in lua.eval("rawget(DEFAULT_CHAT_FRAME, '__log') or {}").values()]
    assert not any("Fehler" in x or "restricted" in x for x in shown)


def test_every_helper_process_is_started_hidden():
    """No black console windows: each subprocess call in the package passes hidden() or an explicit creationflags."""
    pkg = Path(__file__).parent.parent / "wowclaude"
    for f in pkg.glob("*.py"):
        lines = f.read_text(encoding="utf-8").splitlines()
        for i, ln in enumerate(lines):
            if "subprocess.Popen(" in ln or "subprocess.run(" in ln:
                block = " ".join(lines[i:i + 8])
                assert "hidden()" in block or "creationflags" in block, f"{f.name}:{i + 1} starts a visible process"


def test_lua_secret_text_does_not_raise():
    """Secret string values (protected frames) make comparisons error out: the scan must skip them."""
    h, lua = _lua_addon()
    lua.execute("""
        function issecretvalue(v) return v == "SECRET" end
        local b = CreateFrame("Button", "SecretBtn")
        b.IsVisible = function() return true end
        b.GetText = function() return "SECRET" end
        function EnumerateFrames(f) if f == nil then return b end return nil end
    """)
    lua.eval("function() SlashCmdList['KKCHAT']('hi') end")()
    st = decode.decode(h.strip_image(lua))
    assert st is not None and st.message == "hi"
    shown = [str(x) for x in lua.eval("rawget(DEFAULT_CHAT_FRAME, '__log') or {}").values()]
    assert not any("Fehler" in x for x in shown)


def test_overlay_always_starts_solid_not_in_ghost_mode():
    """A saved ghost mode made a freshly opened browser look like it did not open at all (see-through, click-through)."""
    from wowclaude import overlay
    st = overlay.initial_state(10, 20, 300, 200, {"ghost": True, "x": 1})
    assert st["ghost"] is False and (st["x"], st["y"], st["w"], st["h"]) == (10, 20, 300, 200)


def test_page_is_put_above_the_game_when_it_hides_behind_it(monkeypatch):
    """z-order guard: walking up from the page we meet the game -> the game is pushed directly beneath the page."""
    from wowclaude import overlay
    PAGE, GAME, OTHER = 100, 200, 300
    calls = []

    class U:
        def __init__(self, above):
            self.above = above   # windows above the page, nearest first
        def GetWindow(self, h, cmd):
            h = int(getattr(h, "value", h))
            chain = [PAGE] + self.above
            i = chain.index(h)
            return chain[i + 1] if i + 1 < len(chain) else 0
        class _Set:
            argtypes = None
            def __call__(self, *a):
                calls.append(tuple(int(getattr(x, "value", x)) for x in a[:2]))
                return 1
        SetWindowPos = _Set()
    monkeypatch.setattr(overlay, "_game_hwnd", lambda: GAME)
    monkeypatch.setattr(overlay, "user32", U([OTHER, GAME]))          # game above the page: must be pushed down
    overlay.keep_page_above_game(PAGE)
    assert calls == [(GAME, PAGE)]
    calls.clear()
    monkeypatch.setattr(overlay, "user32", U([OTHER]))                # page already above the game: leave everything alone
    overlay.keep_page_above_game(PAGE)
    assert calls == []


def test_installer_copies_addon_removes_old_slots_and_keeps_the_name(tmp_path):
    root = tmp_path / "wow"
    addons = root / "Interface" / "AddOns"
    for i in (1, 2, 300):  # leftovers of the old reply-slot layout
        (addons / f"KKR{i:03d}").mkdir(parents=True)
    (addons / "KKMap" / "sig").mkdir(parents=True)
    lst = root / "WTF" / "Account" / "A" / "R" / "C" / "AddOns.txt"
    lst.parent.mkdir(parents=True)
    lst.write_text("KKMap: enabled\nKKR001: enabled\nKKR300: enabled\nOther: enabled\n", encoding="utf-8")
    res = installer.install(root, "WoW AI")
    assert res["old_slots_removed"] == 3
    assert not list(addons.glob("KKR*")) and not (addons / "KKMap" / "sig").exists()
    assert lst.read_text(encoding="utf-8").splitlines() == ["KKMap: enabled", "Other: enabled"]
    assert 'KKAiName = "WoW AI"' in (addons / "KKMap" / "Name.lua").read_text(encoding="utf-8")
    installer.install(root)  # again, without a name: the chosen name stays
    assert 'KKAiName = "WoW AI"' in (addons / "KKMap" / "Name.lua").read_text(encoding="utf-8")
    assert (addons / "KKMap" / "KKMap.lua").exists() and "Name.lua" in (addons / "KKMap" / "KKMap.toc").read_text(encoding="utf-8")


def test_uninstall_removes_the_addon_and_its_entries(tmp_path):
    root = tmp_path / "wow"
    installer.install(root) if False else None
    (root / "Interface" / "AddOns").mkdir(parents=True)
    installer.install(root)
    lst = root / "WTF" / "Account" / "A" / "R" / "C" / "AddOns.txt"
    lst.parent.mkdir(parents=True)
    lst.write_text("KKMap: enabled\nOther: enabled\n", encoding="utf-8")
    res = installer.uninstall(root)
    assert res["folders_removed"] >= 1 and not (root / "Interface" / "AddOns" / "KKMap").exists()
    assert lst.read_text(encoding="utf-8").splitlines() == ["Other: enabled"]


def test_deliver_posts_the_answer_with_macro_hint_and_overlay_lines(monkeypatch):
    from wowclaude import bridge
    posted = []
    monkeypatch.setattr(bridge, "_post", lambda kind, text: posted.append((kind, text)))
    monkeypatch.setattr(claude, "persona", lambda: ("WoW AI", ""))
    reply = "Hallo\n[[macro Test]]/cast Foo[[/macro]]\n[[overlay Titel]]\n|cff00ff00Zeile|r\n[[/overlay]]"
    bridge.deliver(decode.GameState() if hasattr(decode, "GameState") else None, reply)
    kind, text = posted[-1]
    assert kind == "ai" and text.startswith("WoW AI: Hallo")
    assert "/kkm Test~/cast Foo" in text and "Zeile" in text and "|c" not in text


def test_overlay_window_is_kept_off_the_colour_strip():
    from wowclaude import overlay
    game = (100, 50, 1900, 1100)
    assert overlay._off_strip(110, 60, game)[1] >= 50 + overlay.STRIP_H  # over the strip: moved below
    assert overlay._off_strip(900, 60, game) == (900, 60)               # elsewhere: untouched
    assert overlay._off_strip(110, 400, game) == (110, 400)
