"""Live check of the browser overlay in the running game (not part of the automated tests: needs WoW in windowed mode).
Usage: py -3 tools/live_check.py        -> starts the overlay like the bridge does, then stresses it:
the game takes the front, the game window is made smaller and bigger again, the overlay is started a second time.
After every step: page visible and ABOVE the game, frame and address bar present and over the page. Exit code 0 = all fine."""
import ctypes
import json
import sys
import time
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from wowclaude import config, overlay  # noqa: E402

u = ctypes.windll.user32
u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]


def windows():
    out = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(h, _l):
        if u.IsWindowVisible(h):
            cls = ctypes.create_unicode_buffer(80)
            u.GetClassNameW(h, cls, 80)
            r = wintypes.RECT()
            u.GetWindowRect(h, ctypes.byref(r))
            out.append((h, cls.value, (r.left, r.top, r.right, r.bottom)))
        return True
    u.EnumWindows(cb, 0)
    return out


def above(a, b):
    """Is window a above window b in the z-order?"""
    h, n = u.GetWindow(wintypes.HWND(b), 3), 0
    while h and n < 1000:
        if h == a:
            return True
        h, n = u.GetWindow(wintypes.HWND(h), 3), n + 1
    return False


def check(label):
    st = json.loads((config.HOME / "overlay.json").read_text(encoding="utf-8"))
    x, y, w, h = st["x"], st["y"], st["w"], st["h"]
    g = overlay.game_rect()
    if g and st.get("rel"):  # the overlay scales with the game window; the saved x/y/w/h are only updated when it is moved
        x, y, w, h = overlay.from_rel(g, st["rel"])
    game = overlay._game_hwnd()
    wins = windows()
    near = lambda r, ex, ey, ew, eh, tol=40: abs(r[0] - ex) < tol and abs(r[1] - ey) < tol and abs(r[2] - r[0] - ew) < tol and abs(r[3] - r[1] - eh) < tol  # noqa: E731
    page = [hw for hw, cls, r in wins if cls == "Chrome_WidgetWin_1" and near(r, x, y - overlay.CHROME_BAR, w, h + overlay.CHROME_BAR, 60)]
    frame = [hw for hw, cls, r in wins if cls.startswith("Tk") and near(r, x - overlay.EDGE, y - overlay.TOP, w + 2 * overlay.EDGE, h + overlay.TOP + overlay.EDGE)]
    bar = [hw for hw, cls, r in wins if cls.startswith("Tk") and r[3] - r[1] <= 24 and x - overlay.EDGE <= r[0] and r[2] <= x + w + overlay.EDGE and y - overlay.TOP <= r[1] <= y]
    problems = []
    if not page:
        problems.append("page window missing")
    elif game and above(game, page[0]):
        problems.append("page is BEHIND the game")
    if not frame:
        problems.append("frame missing")
    elif page and not above(frame[0], page[0]):
        problems.append("frame is behind the page")
    if not bar:
        problems.append("address bar missing")
    print(f"{label}: {'OK' if not problems else 'PROBLEM: ' + ', '.join(problems)}", flush=True)
    return not problems


def main() -> int:
    ok = True
    print("start:", repr(overlay.play("")))
    time.sleep(6)
    ok &= check("after start")
    game = overlay._game_hwnd()
    if game:
        u.SetForegroundWindow(game)
        u.BringWindowToTop(game)
        time.sleep(2)
        ok &= check("game in front")
        r = wintypes.RECT()
        u.GetWindowRect(game, ctypes.byref(r))
        for w, h in ((900, 560), (r.right - r.left, r.bottom - r.top)):
            u.SetWindowPos(game, 0, r.left, r.top, w, h, 0x14)
            time.sleep(3.5)
            ok &= check(f"game resized to {w}x{h}")
    print("start again:", repr(overlay.play("")))
    time.sleep(6)
    ok &= check("after second start")
    print("ALL OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
