from PIL import Image

from wowclaude import chat_marks, chat_scroll

FRAME = (100, 200, 600, 400)  # screen rectangle of the tab: 500 x 200


def setup(rows=40, fit=8, scroll=0):
    chat_scroll.STATE.update(frame=FRAME, rows=rows, fit=fit, scroll=scroll, dirty=False)


def test_wheel_over_the_tab_scrolls_and_clamps():
    setup()
    assert chat_scroll.nudge("wheel_up", 300, 300)
    assert chat_scroll.STATE["scroll"] == chat_scroll.STEP and chat_scroll.STATE["dirty"]
    assert chat_scroll.nudge("wheel_down", 300, 300) and chat_scroll.STATE["scroll"] == 0
    assert not chat_scroll.nudge("wheel_down", 300, 300)  # already at the bottom
    setup(scroll=31)
    chat_scroll.nudge("wheel_up", 300, 300)
    assert chat_scroll.STATE["scroll"] == 32  # rows - fit: never past the oldest line


def test_wheel_outside_the_tab_is_ignored():
    setup()
    assert not chat_scroll.nudge("wheel_up", 50, 50)


def test_nothing_to_scroll_when_all_text_fits():
    setup(rows=5, fit=8)
    assert not chat_scroll.nudge("wheel_up", 300, 300)


def test_bar_zones_and_clicks():
    setup()
    l, t, r, b = FRAME
    x = r + chat_scroll.BAR_X + chat_scroll.BAR_W // 2
    assert chat_scroll.bar_zone(FRAME, x, t + 5) == "up"
    assert chat_scroll.bar_zone(FRAME, x, b - 5) == "bottom"
    assert chat_scroll.bar_zone(FRAME, x, b - chat_scroll.BTN - 5) == "down"
    assert chat_scroll.bar_zone(FRAME, x, t + 50) == "page_up"
    assert chat_scroll.bar_zone(FRAME, x, b - 50) == "page_down"
    assert chat_scroll.bar_zone(FRAME, l + 10, t + 80) == ""  # on the text
    assert chat_scroll.nudge("click", x, t + 5)  # up arrow
    assert chat_scroll.STATE["scroll"] == chat_scroll.STEP
    assert chat_scroll.nudge("click", x, b - 5)  # to the newest line
    assert chat_scroll.STATE["scroll"] == 0


def test_bar_image_has_the_size_asked_for():
    img = chat_scroll.bar_image(200, 0.2, 0.6, True)
    assert img.size == (chat_scroll.BAR_W, 200) and img.getbbox() is not None


def test_scrolled_render_shows_older_lines():
    entries = [("ai", f"line {i}") for i in range(30)]
    size = (400, 160)
    bottom = chat_marks.render(entries, size, bg=(0, 0, 0, 255), scroll=0)
    older = chat_marks.render(entries, size, bg=(0, 0, 0, 255), scroll=10)
    assert bottom.tobytes() != older.tobytes()


def test_dragging_the_thumb_scrolls():
    setup()
    l, t, r, b = FRAME
    x = r + chat_scroll.BAR_X + chat_scroll.BAR_W // 2
    sp = chat_scroll.thumb_span(FRAME)
    chat_scroll.nudge("click", x, sp[0] + 3)
    assert chat_scroll.DRAG["on"]
    assert chat_scroll.drag_to(sp[0] + 3 - 40)  # up = older lines
    assert chat_scroll.STATE["scroll"] > 0
    chat_scroll.DRAG["on"] = False


def test_game_bar_image_builds_from_pictures(tmp_path):
    from PIL import Image
    sizes = {"arrow-top": (17, 11), "arrow-bottom": (17, 11), "arrow-returntobottom": (17, 15), "track-top": (8, 8),
             "track-bottom": (8, 8), "track-middle": (8, 1), "small-thumb-top": (8, 8), "small-thumb-middle": (8, 40),
             "small-thumb-bottom": (8, 8), "small-thumb-top-down": (8, 8), "small-thumb-middle-down": (8, 40),
             "small-thumb-bottom-down": (8, 8)}
    for name, size in sizes.items():
        Image.new("RGBA", size, (200, 120, 60, 255)).save(tmp_path / f"minimal-scrollbar-{name}.png")
    old = chat_scroll.ASSETS
    chat_scroll.ASSETS = tmp_path
    try:
        for kw in ({}, {"w": 16, "btn": 16, "jump": False}):
            im = chat_scroll.game_bar_image(300, 0.2, 0.5, True, False, **kw)
            assert im is not None and im.size[1] == 300 and im.getbbox() is not None
        assert chat_scroll.bar_image(300, 0.2, 0.5, True, True).getbbox() is not None
    finally:
        chat_scroll.ASSETS = old


def test_thumb_shrinks_with_more_text_and_reaches_both_ends():
    sizes = []
    for rows in (30, 100, 1000):
        top = chat_scroll.thumb_extent(400, 0, 21 / rows)
        bottom = chat_scroll.thumb_extent(400, (rows - 21) / rows, 1)
        assert top[0] == 0 and bottom[1] == 400  # reaches both ends
        sizes.append(top[1] - top[0])
    assert sizes[0] > sizes[1] > sizes[2] >= chat_scroll.MIN_THUMB


def test_arrows_track_and_thumb_share_one_axis(tmp_path):
    from PIL import Image
    def part(name, size, box):  # a picture whose visible pixels do not start at 0 (like the game's arrows)
        im = Image.new("RGBA", size, (0, 0, 0, 0))
        im.paste((200, 120, 60, 255), box)
        im.save(tmp_path / f"minimal-scrollbar-{name}.png")
    for n in ("arrow-top", "arrow-bottom"):
        part(n, (17, 11), (1, 1, 17, 11))
    part("arrow-returntobottom", (17, 15), (1, 0, 17, 15))
    part("track-top", (8, 8), (1, 1, 7, 8)); part("track-bottom", (8, 8), (1, 0, 7, 7)); part("track-middle", (8, 1), (1, 0, 7, 1))
    for n in ("top", "bottom"):
        part("small-thumb-" + n, (8, 8), (0, 0, 8, 8))
    part("small-thumb-middle", (8, 40), (0, 0, 8, 40))
    old = chat_scroll.ASSETS
    chat_scroll.ASSETS = tmp_path
    try:
        im = chat_scroll.game_bar_image(400, 0.3, 0.6, True)
    finally:
        chat_scroll.ASSETS = old
    alpha = im.getchannel("A").point(lambda v: 255 if v > 40 else 0)
    for y0, y1 in ((0, 18), (30, 60), (364, 382), (382, 400)):
        box = alpha.crop((0, y0, im.width, y1)).getbbox()
        assert (box[0] + box[2]) / 2 == im.width / 2, (y0, box)
