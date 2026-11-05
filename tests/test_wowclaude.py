import tempfile
from pathlib import Path

from PIL import Image

from wowclaude import claude, decode, slots


def make_strip(text: str) -> Image.Image:
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
        x, y = (i % decode.COLS) * decode.CELL, (i // decode.COLS) * decode.CELL
        for dx in range(decode.CELL):
            for dy in range(decode.CELL):
                img.putpixel((x + 30 + dx, y + 10 + dy), rgb)  # strip not at the corner: must still be found
    return img


def test_decode_message_and_state():
    text = "#ver|25\n#msg|123|7|Hello | pipe\n#ack|120\n#edit|1\n#ctx|Name|Level 5\n#img|3\n#slot|42"
    st = decode.decode(make_strip(text))
    assert st.addon_version == 25
    assert (st.message_seq, st.message_idx, st.message) == (123, 7, "Hello | pipe")
    assert st.ack_seq == 120 and st.edit_active and st.image_next == 3 and st.slot_next == 42
    assert "Level 5" in st.context


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


def test_no_private_details_in_sources():
    import re
    bad = re.compile(r"(C:\\\\Users|C:\\Users|\.claude[/\\]|@gmail|@proton)", re.I)
    for f in Path(__file__).parent.parent.rglob("*"):
        if f.suffix in (".py", ".lua", ".toc", ".md", ".bat", ".toml") and f.name != "test_wowclaude.py":
            hit = bad.search(f.read_text(encoding="utf-8", errors="replace"))
            assert not hit, f"{f}: {hit.group(0)}"
