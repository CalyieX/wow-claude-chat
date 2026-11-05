import time
from PIL import Image, ImageDraw

from wowclaude import chat_marks as cm


def scene(tl=(100, 80), br=(500, 300), size=(800, 500), mark=6, noise=True):
    img = Image.new("RGB", size, (30, 60, 20))
    d = ImageDraw.Draw(img)
    if noise:
        d.rectangle((600, 400, 700, 450), fill=(200, 10, 10))
    if tl:
        d.rectangle((tl[0], tl[1], tl[0] + mark - 1, tl[1] + mark - 1), fill=cm.TOP_LEFT)
    if br:
        d.rectangle((br[0] - mark, br[1] - mark, br[0] - 1, br[1] - 1), fill=cm.BOTTOM_RIGHT)
    return img


def test_finds_frame():
    assert cm.find_frame(scene()) == (100, 80, 500, 300)


def test_missing_mark_is_none():
    assert cm.find_frame(scene(br=None)) is None
    assert cm.find_frame(scene(tl=None)) is None


def test_big_magenta_area_is_ignored():
    img = scene()
    ImageDraw.Draw(img).rectangle((0, 0, 200, 200), fill=cm.TOP_LEFT)
    assert cm.find_frame(img) is None


def test_tiny_frame_rejected():
    assert cm.find_frame(scene(tl=(100, 80), br=(120, 90))) is None


def test_render_size_wrap_and_speed():
    entries = [("user", "Du: hallo"), ("ai", "WoW AI: " + "wort " * 80)]
    cm.default_font()
    t = time.perf_counter()
    img = cm.render(entries, (400, 220))
    assert (time.perf_counter() - t) < 0.02
    assert img.size == (400, 220)
    assert img.getbbox() and img.getpixel((0, 0)) == (12, 12, 16)


def test_scroll_changes_picture():
    entries = [("ai", "zeile %d" % i) for i in range(60)]
    assert cm.render(entries, (300, 150)).tobytes() != cm.render(entries, (300, 150), scroll=10).tobytes()
