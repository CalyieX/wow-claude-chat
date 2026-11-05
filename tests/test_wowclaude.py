import tempfile
from pathlib import Path

from PIL import Image

from wowclaude import claude, decode, slots


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
    text = "#ver|25\n#msg|123|7|Hello | pipe\n#ack|120\n#edit|1\n#ctx|Name|Level 5\n#img|3\n#slot|42"
    st = decode.decode(make_strip(text))
    assert st.addon_version == 25
    assert (st.message_seq, st.message_idx, st.message) == (123, 7, "Hello | pipe")
    assert st.ack_seq == 120 and st.edit_active and st.image_next == 3 and st.slot_next == 42
    assert "Level 5" in st.context


def test_decode_every_cell_size():
    import pytest
    text = "#ver|26\n#msg|55|2|tiny strip | works\n#ack|50\n#ctx|A|B|C"
    for cell in (1, 2, 3, 4):
        st = decode.decode(make_strip(text, cell))
        assert st is not None, cell
        assert (st.message_seq, st.message_idx, st.message, st.ack_seq) == (55, 2, "tiny strip | works", 50)


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


def test_reply_lua_escapes():
    lua = slots.reply_lua(5, ['say "hi" \\ done'])
    assert 'seq = 5' in lua and '\\"hi\\"' in lua and "\\\\" in lua


def test_install_and_publish():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "Interface" / "AddOns").mkdir(parents=True)
        res = slots.install(root)
        assert res["slots_created"] == slots.SLOTS
        assert (root / "Interface" / "AddOns" / "KKMap" / "KKMap.lua").exists()
        slots.publish(root, 99, 3, ["Claude: hi"])
        reply = (root / "Interface" / "AddOns" / "KKR200" / "Reply.lua").read_text(encoding="utf-8")
        assert "seq = 99" in reply
        assert (root / "Interface" / "AddOns" / "KKMap" / "sig" / "003.wav").stat().st_size > 0
        assert (root / "Interface" / "AddOns" / "KKMap" / "sig" / "004.wav").stat().st_size == 0
        slots.reset_marker(root, 3)
        assert (root / "Interface" / "AddOns" / "KKMap" / "sig" / "003.wav").stat().st_size == 0


def test_macro_blocks_end_up_in_lua():
    text, macros = claude.extract_macros("Here you go.\n[[macro Pull]]\n#showtooltip Shadow Bolt\n/cast Shadow Bolt\n[[/macro]]")
    assert text == "Here you go." and macros == [{"name": "Pull", "body": "#showtooltip Shadow Bolt\n/cast Shadow Bolt"}]
    lua = slots.reply_lua(1, ["x"], None, macros)
    assert 'name = "Pull"' in lua and "#showtooltip Shadow Bolt\\\\n/cast Shadow Bolt" in lua
    assert "MACROS" in claude.persona()[1]


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
    bad = re.compile(r"(C:\\\\Users|C:\\Users|\.claude[/\\]|qo-virtual|@gmail|@proton)", re.I)
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
    out = setup_ui.apply({"backend": "openrouter", "model": "x/y", "api_key": "sk-test", "persona": "Gorel\nBe brief."})
    assert out["ok"] and out["has_key"]
    cfg = config.load()
    assert cfg["backend"] == "openrouter" and cfg["model"] == "x/y" and cfg["api_key"] == "sk-test"
    assert (tmp_path / "persona.txt").read_text(encoding="utf-8").startswith("Gorel")
    st = setup_ui._state()
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


def test_publish_writes_only_the_next_slots():
    assert slots.target_slots(None) == list(range(1, slots.SLOTS + 1))
    t = slots.target_slots(50)
    assert {50, 51, 52, 53} <= set(t) and {1, 2, 3} <= set(t) and len(t) < 12
    assert max(slots.target_slots(slots.SLOTS)) == slots.SLOTS  # never beyond the last slot
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "Interface" / "AddOns").mkdir(parents=True)
        slots.install(root)
        slots.publish(root, 7, 1, ["Claude: x"], slot_next=10)
        add = root / "Interface" / "AddOns"
        assert "seq = 7" in (add / "KKR010" / "Reply.lua").read_text(encoding="utf-8")
        assert "seq = 7" in (add / "KKR001" / "Reply.lua").read_text(encoding="utf-8")
        assert "seq = 7" not in (add / "KKR100" / "Reply.lua").read_text(encoding="utf-8")


def test_deliver_retries_when_files_are_locked(monkeypatch):
    from wowclaude import bridge, decode
    calls = []

    def fake_publish(root, seq, idx, parts, overlay=None, macros=None, slot_next=None):
        calls.append(slot_next)
        if len(calls) == 1:
            raise PermissionError("locked")

    st = decode.GameState(message="hi", message_seq=5, message_idx=1, slot_next=9)
    monkeypatch.setattr(bridge.slots, "publish", fake_publish)
    monkeypatch.setattr(bridge, "read_state", lambda: decode.GameState(ack_seq=5, slot_next=9))
    monkeypatch.setattr(bridge.time, "sleep", lambda s: None)
    assert bridge.deliver(Path("."), st, "hello") is True and len(calls) == 2


def test_frame_art_is_generated_without_game_files(tmp_path, monkeypatch):
    """No game textures ship with the package: every frame image can be drawn from code."""
    from wowclaude import frame_art, overlay
    monkeypatch.setattr(overlay.config, "HOME", tmp_path)
    overlay._art_cache.clear()
    for name in frame_art.NAMES:
        im = overlay._art(name)
        assert im.mode == "RGBA" and im.size[0] > 0
    assert overlay.compose(500, 300, overlay.TOP).size == (500, 300)
    assert overlay.slot_sprite("hover").size == (64, 64)
    assert not (Path(overlay.__file__).parent / "art").exists()
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
    return lua_harness, lua_harness.run_addon(Path(slots.ADDON_SRC) / "KKMap.lua")


def test_lua_addon_strip_is_read_by_python_decoder():
    """Contract test: the REAL KKMap.lua (run in a fake WoW API) draws a strip that decode.py understands."""
    h, lua = _lua_addon()
    st = decode.decode(h.strip_image(lua))
    assert st is not None and st.addon_version == 25 and st.slot_next == 1
    assert "Tester" in st.context and "Fehler" not in st.context


def test_lua_addon_sends_a_message_through_the_strip():
    h, lua = _lua_addon()
    lua.eval("function() SlashCmdList['KKCHAT']('Hello Welt, wie komme ich nach Undercity?') end")()
    st = decode.decode(h.strip_image(lua))
    assert st.message == "Hello Welt, wie komme ich nach Undercity?" and st.message_seq > 0 and st.message_idx == 1


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


def test_uninstall_removes_addon_slots_and_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(slots, "SLOTS", 10)  # same logic, 20x faster
    root = tmp_path
    (root / "Interface" / "AddOns").mkdir(parents=True)
    wtf = root / "WTF" / "Account" / "A" / "R" / "C"
    wtf.mkdir(parents=True)
    (wtf / "AddOns.txt").write_text("Blizzard_Foo: enabled\n", encoding="utf-8")
    slots.install(root)
    assert "KKR001: enabled" in (wtf / "AddOns.txt").read_text(encoding="utf-8")
    res = slots.uninstall(root)
    assert res["folders_removed"] == slots.SLOTS + 1
    assert not (root / "Interface" / "AddOns" / "KKMap").exists()
    assert (wtf / "AddOns.txt").read_text(encoding="utf-8").strip() == "Blizzard_Foo: enabled"


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


def test_lua_string_with_newline_is_valid_lua():
    lupa = __import__("pytest").importorskip("lupa")
    lua = lupa.LuaRuntime()
    text = 'line one' + chr(10) + 'line "two" ' + chr(92) + ' end'
    assert lua.execute("return " + slots.lua_string(text)) == text


def test_deliver_stops_waiting_when_next_message_arrived(monkeypatch, tmp_path):
    from wowclaude import bridge, decode
    monkeypatch.setattr(bridge.time, "sleep", lambda s: None)
    monkeypatch.setattr(bridge.slots, "publish", lambda *a, **k: None)

    class St:
        def __init__(self, seq, ack):
            self.message_seq, self.ack_seq, self.message_idx, self.slot_next = seq, ack, 1, 5
    monkeypatch.setattr(bridge, "_safe_read_state", lambda: St(8, 6))  # player already wrote message 8
    assert bridge.deliver(tmp_path, St(7, 6), "hi") is True
    monkeypatch.setattr(bridge, "_safe_read_state", lambda: St(0, 0))  # /reload resets the counter: NOT delivered
    monkeypatch.setattr(bridge.time, "time", iter(range(0, 10000, 20)).__next__)
    assert bridge.deliver(tmp_path, St(7, 6), "hi") is False


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


def test_marker_silenced_after_ack(monkeypatch, tmp_path):
    from wowclaude import bridge
    monkeypatch.setattr(bridge.time, "sleep", lambda s: None)
    monkeypatch.setattr(bridge.slots, "publish", lambda *a, **k: None)
    silenced = []
    monkeypatch.setattr(bridge.slots, "reset_marker", lambda root, idx: silenced.append(idx))

    class St:
        def __init__(self, seq, ack):
            self.message_seq, self.ack_seq, self.message_idx, self.slot_next = seq, ack, 3, 5
    monkeypatch.setattr(bridge, "_safe_read_state", lambda: St(7, 7))
    assert bridge.deliver(tmp_path, St(7, 6), "hi") is True
    assert silenced == [3]


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


def test_lua_reply_round_trip_through_slots(tmp_path):
    """Full loop: question via strip -> Python publishes -> marker plays -> addon loads the slot, shows it, acks."""
    h, lua = _lua_addon()
    root = tmp_path
    addons = root / "Interface" / "AddOns"
    (addons / "KKMap" / "sig").mkdir(parents=True)
    for i in range(1, 8):
        (addons / f"KKR{i:03d}").mkdir()
    lua.eval("function() SlashCmdList['KKCHAT']('Hallo wie gehts?') end")()
    st = decode.decode(h.strip_image(lua))
    assert st.message == "Hallo wie gehts?" and st.slot_next == 1
    marker = addons / "KKMap" / "sig" / f"{st.message_idx:03d}.wav"

    def play(path):  # the real game plays a file only if it contains sound
        return marker.exists() and marker.stat().st_size > 0 and str(path).endswith(marker.name)

    def load(name):
        f = addons / name / "Reply.lua"
        if not f.exists():
            return False
        lua.execute(f.read_text(encoding="utf-8"))
        return True
    lua.globals().__play, lua.globals().__load = play, load

    lua.eval("function() __update(1.0) end")()           # nothing published yet: addon keeps waiting
    assert decode.decode(h.strip_image(lua)).ack_seq != st.message_seq
    slots.reset_marker(root, st.message_idx)             # what the bridge does before it asks the AI
    assert not play(marker.name)
    slots.publish(root, st.message_seq, st.message_idx, ["Claude: Gut, danke!"], None, None, 1)  # the real publisher
    lua.eval("function() __update(1.0) end")()
    shown = [str(x) for x in lua.eval("DEFAULT_CHAT_FRAME.__log").values()]
    assert "Claude: Gut, danke!" in shown
    after = decode.decode(h.strip_image(lua))
    assert after.ack_seq == st.message_seq and after.slot_next == 2


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
        shown = " ".join(str(x) for x in lua.eval("DEFAULT_CHAT_FRAME.__log").values())
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
            self.message_seq, self.ack_seq, self.message_idx, self.slot_next = seq, ack, 4, 5
    return bridge, St, silenced


def test_marker_silenced_when_next_message_arrives(monkeypatch, tmp_path):
    bridge, St, silenced = _deliver_env(monkeypatch, tmp_path, None)
    monkeypatch.setattr(bridge, "_safe_read_state", lambda: St(9, 6))
    assert bridge.deliver(tmp_path, St(7, 6), "hi") is True
    assert silenced == [4]


def test_marker_silenced_when_never_confirmed(monkeypatch, tmp_path):
    bridge, St, silenced = _deliver_env(monkeypatch, tmp_path, None)
    monkeypatch.setattr(bridge, "_safe_read_state", lambda: St(7, 6))
    assert bridge.deliver(tmp_path, St(7, 6), "hi") is False
    assert silenced == [4]


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
