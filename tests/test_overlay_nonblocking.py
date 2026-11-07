"""The in-game browser window must never wait on DevTools on its UI thread."""
import time

from wowclaude import overlay


def test_poller_caches_page_without_blocking(monkeypatch):
    monkeypatch.setattr(overlay, "_page_ws", lambda port: (time.sleep(0.3), ("ws://x", "https://a.b/"))[1])
    overlay.PAGE["found"] = None
    t0 = time.time()
    overlay.start_poller(1, every=0.05)
    assert time.time() - t0 < 0.1  # starting costs nothing
    for _ in range(40):
        if overlay.PAGE["found"]:
            break
        time.sleep(0.05)
    assert overlay.PAGE["found"] == ("ws://x", "https://a.b/")


def test_in_background_returns_at_once():
    done = []
    t0 = time.time()
    overlay.in_background(lambda: (time.sleep(0.4), done.append(1)))
    assert time.time() - t0 < 0.1
    time.sleep(0.6)
    assert done


def test_ui_code_reads_cache_only():
    src = open(overlay.__file__, encoding="utf-8").read()
    ui = src[src.index("def frame_loop"):src.index("def play(")]
    assert "_page_ws(" not in ui and "navigate(port" not in ui.replace("in_background(navigate, port", "")


def test_bookmarks(tmp_path, monkeypatch):
    monkeypatch.setattr(overlay, "STATE_FILE", tmp_path / "overlay.json")
    assert overlay.bookmarks() == []
    assert overlay.add_bookmark("https://www.wowhead.com/classic")
    assert not overlay.add_bookmark("https://www.wowhead.com/classic")  # once per address
    assert not overlay.add_bookmark("chrome-error://x")
    assert overlay.bookmarks()[0]["title"] == "wowhead.com"
    overlay.remove_bookmark("https://www.wowhead.com/classic")
    assert overlay.bookmarks() == []


def test_reload_sends_page_reload(monkeypatch):
    sent = []
    monkeypatch.setattr(overlay, "_cdp", lambda port, m, p: sent.append((port, m)) or True)
    assert overlay.reload_page(9)
    assert sent == [(9, "Page.reload")]


def test_game_in_front_logic(monkeypatch):
    import os
    monkeypatch.setattr(overlay, "_game_hwnd", lambda: 100)
    pids = {100: 11, 200: os.getpid(), 300: 33, 400: 44}
    monkeypatch.setattr(overlay, "_pid_of", lambda h: pids[h])
    fg = {"h": 100}
    monkeypatch.setattr(overlay.user32, "GetForegroundWindow", lambda: fg["h"])
    assert overlay.game_in_front()          # the game
    fg["h"] = 200
    assert overlay.game_in_front()          # this program
    fg["h"] = 300
    assert not overlay.game_in_front()      # another program
    assert overlay.game_in_front({33})      # ... unless it is the browser we own
    fg["h"] = 0
    assert overlay.game_in_front()          # nothing in front: no flicker


def test_game_window_found_by_class_not_title(monkeypatch):
    overlay._GAME["h"] = 0
    monkeypatch.setattr(overlay.user32, "FindWindowW", lambda c, t: 555 if c == "GxWindowClass" else 0)
    assert overlay._game_hwnd() == 555
    # the handle is remembered; it stays valid while the window exists with a game class (even if the title changed)
    monkeypatch.setattr(overlay.user32, "IsWindow", lambda h: True)
    monkeypatch.setattr(overlay, "_class_of", lambda h: "GxWindowClassD3d")
    monkeypatch.setattr(overlay.user32, "FindWindowW", lambda c, t: 0)
    assert overlay._game_hwnd() == 555
    monkeypatch.setattr(overlay, "_class_of", lambda h: "Other")
    assert overlay._game_hwnd() == 0
    overlay._GAME["h"] = 0
