from wowclaude import chat_fake as cf, chat_marks as cm


def test_events_roundtrip_and_half_line(tmp_path):
    p = tmp_path / "e.jsonl"
    cf.post("user", "hi", p)
    ev, off = cf.read_new(0, p)
    assert ev[0]["text"] == "hi"
    with open(p, "ab") as f:
        f.write(b'{"kind": "ai", "te')  # writer is mid-line
    ev2, off2 = cf.read_new(off, p)
    assert ev2 == [] and off2 == off


def test_answer_replaces_thinking():
    e = cf.apply_events([], [{"kind": "user", "text": "a"}, {"kind": "think", "text": "..."}])
    assert e[-1][0] == "think"
    e = cf.apply_events(e, [{"kind": "ai", "text": "b"}])
    assert [k for k, _ in e] == ["user", "ai"]


def test_ring_buffer():
    e = cf.apply_events([], [{"kind": "ai", "text": str(i)} for i in range(500)])
    assert len(e) == cf.MAX_ENTRIES and e[-1][1] == "499"


def test_paint_keeps_marks_visible():
    img = cf.paint([("ai", "x")], (300, 120))
    assert img.getpixel((2, 2))[3] == 0 and img.getpixel((297, 2))[3] == 0 and img.getpixel((2, 117))[3] == 0
    assert img.getpixel((150, 60))[3] > 0
