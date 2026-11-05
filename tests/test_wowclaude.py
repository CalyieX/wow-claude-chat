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
    bad = re.compile(r"(C:\\\\Users|C:\\Users|\.claude[/\\]|@gmail|@proton)", re.I)
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
    assert im.getpixel((150, 3))[3] > 0             # border is drawn
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
