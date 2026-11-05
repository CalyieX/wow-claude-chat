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
