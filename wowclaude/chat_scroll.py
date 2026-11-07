"""Scrolling for the painted AI chat tab: mouse wheel over the tab, and the bar's arrows / track.

The painted tab is click-through (the real, empty tab lies under it), so the program only *watches* the mouse with a
read-only low-level hook on its own thread: it never moves, clicks or blocks anything.
"""
from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes

# Measures of the game's own chat scroll bar (MinimalScrollBar in a chat frame, read from the client's UI files):
# the bar is 8 px wide and starts right at the chat frame's right edge; the arrows are 17 x 11 px and stick out to both sides;
# the track runs from 19 px below the top to 19 px above the bottom; the thumb is never shorter than 23 px; the
# "to the newest line" button (17 x 15) sits below the bar and only exists while the chat is scrolled up.
BAR_X = 0  # gap between the text area and the bar (the game: none)
BAR_W = 18  # width of the picture the bar is painted into (8 px bar + the arrows' overhang)
OVERHANG = 5  # the picture starts this far left of the bar (arrows are wider than the bar)
EXTRA = BAR_X + BAR_W + 4  # how much wider than the text area the painted window is
STEP = 3  # lines per wheel notch / arrow click
CELL = 19  # the bar's track starts this far below the top and ends this far above the bottom
ARROW_H = 11
JUMP_H = 15  # height of the "to the newest line" button
BTN = CELL  # (the drawn fallback look uses the same cells)
FADE_IN = 0.6  # the game shows the bar at 60 % while the mouse is over the chat ...
FADE_OUT = 2.0  # ... and fades it out over two seconds after the mouse left

STATE: dict = {"thumb": None, "scroll": 0, "frame": None, "rows": 0, "fit": 1, "dirty": False}
ASSETS = None  # folder with the game's own scroll bar pictures (cut from the player's own client, never shipped); None = drawn look
LOG = None  # path of a small diagnostic log (set by the overlay): what the hook saw

WM_MOUSEWHEEL, WM_LBUTTONDOWN, WM_MOUSEMOVE, WM_LBUTTONUP = 0x020A, 0x0201, 0x0200, 0x0202
DRAG: dict = {"on": False, "off": 0}


def _log(text: str) -> None:
    if LOG is None:
        return
    try:
        import time
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(time.strftime("%H:%M:%S ") + text + "\n")
    except OSError:
        pass


def clamp(scroll: int, rows: int, fit: int) -> int:
    return max(0, min(int(scroll), max(0, rows - fit)))


def layout(h: int, jump_shown: bool) -> tuple[int, int, int]:
    """(height of the bar, top of the track, bottom of the track) in a picture ``h`` px high. While the "to the newest
    line" button is there the bar ends 2 px above it (the game anchors it so)."""
    bar_h = h - (JUMP_H + 2) if jump_shown else h
    return bar_h, CELL, bar_h - CELL


def is_scrolled() -> bool:
    return STATE["scroll"] > 0 or STATE["thumb"] is not None


def bar_zone(frame, x: int, y: int) -> str:
    """Which part of the bar (it stands right of the text area) the screen point (x, y) is on:
    up, down, bottom (jump to the newest line), page_up, page_down, or ''."""
    if not frame:
        return ""
    l, t, r, b = frame
    h = b - t
    left = (r - l) + BAR_X - OVERHANG
    if not (left <= x - l <= left + BAR_W):
        return ""
    ry = y - t
    if ry < 0 or ry > h:
        return ""
    scrolled = is_scrolled()
    bar_h, t0, t1 = layout(h, scrolled)
    if scrolled and ry >= h - JUMP_H:
        return "bottom"
    if ry >= bar_h:
        return ""
    if ry < t0:
        return "up"
    if ry > t1:
        return "down"
    sp = thumb_span(frame)
    if sp is None:
        return ""
    return "page_up" if y < sp[0] else "page_down"


def _part(name: str):
    from PIL import Image
    try:
        return Image.open(ASSETS / (name + ".png")).convert("RGBA")
    except (OSError, TypeError):
        return None


def _bbox(part):
    """Where the visible pixels of a picture are (the pictures carry empty margins: centre on what is seen)."""
    box = part.getchannel("A").point(lambda v: 255 if v > 40 else 0).getbbox()
    return box or (0, 0, part.width, part.height)


def _put_centered(im, part, axis: float, top: int, cell: int = 0) -> None:
    """Paste ``part`` so that its visible pixels sit exactly on the vertical ``axis`` (and, with ``cell``, in the middle of
    a cell of that height starting at ``top``)."""
    x0, y0, x1, y1 = _bbox(part)
    x = round(axis - (x0 + x1) / 2)
    y = top + (round((cell - (y1 - y0)) / 2) - y0 if cell else 0)
    im.alpha_composite(part, (x, y))


def game_bar_image(h: int, first: float, last: float, scrolled: bool, dragging: bool = False, w: int = 0,
                   jump: bool = True, alpha: float = 1.0):
    """The bar from the game's own pictures, laid out like the game does it (see the measures at the top), or None when
    the pictures are not there."""
    from PIL import Image
    if ASSETS is None or not (ASSETS / "minimal-scrollbar-arrow-top.png").exists():
        return None
    P = lambda n: _part("minimal-scrollbar-" + n)  # noqa: E731
    w = w or BAR_W
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    axis = w / 2  # one axis for everything: arrows, track and thumb are centred on what is visible, not on the picture
    bar_h, t0, t1 = layout(h, scrolled and jump)
    x = round(axis - 4)
    top, bot, mid = P("track-top"), P("track-bottom"), P("track-middle")
    if mid is not None and top is not None and bot is not None and t1 - t0 > 16:
        im.alpha_composite(top, (x, t0))
        im.alpha_composite(mid.resize((8, t1 - t0 - 16), Image.NEAREST), (x, t0 + 8))
        im.alpha_composite(bot, (x, t1 - 8))
    a_up, a_dn = P("arrow-top"), P("arrow-bottom")
    if a_up is not None:
        _put_centered(im, a_up, axis, 0)
    if a_dn is not None:
        _put_centered(im, a_dn, axis, bar_h - ARROW_H)
    if scrolled and jump:
        rb = P("arrow-returntobottom")
        if rb is not None:
            _put_centered(im, rb, axis, h - JUMP_H)
    if t1 - t0 > 24 and last - first < 0.999:  # nothing to scroll: no thumb (a full-length thumb looks like a rod)
        kind = "-down" if dragging else ""
        y0, y1 = thumb_extent(t1 - t0, first, last)
        y0, y1 = t0 + y0, t0 + y1
        tt, tm, tb = P("small-thumb-top" + kind), P("small-thumb-middle" + kind), P("small-thumb-bottom" + kind)
        if tt is not None and tm is not None and tb is not None and y1 - y0 >= 16:
            im.alpha_composite(tt, (x, y0))
            im.alpha_composite(tm.resize((8, y1 - y0 - 16), Image.NEAREST), (x, y0 + 8))
            im.alpha_composite(tb, (x, y1 - 8))
    if alpha < 0.999:
        im.putalpha(im.getchannel("A").point(lambda v: int(v * max(0.0, alpha))))
    return im


def bar_image(h: int, first: float, last: float, scrolled: bool, dragging: bool = False, alpha: float = 1.0):
    real = game_bar_image(h, first, last, scrolled, dragging, alpha=alpha)
    if real is not None:
        return real
    return _drawn_bar_image(h, first, last, scrolled)


def _drawn_bar_image(h: int, first: float, last: float, scrolled: bool):
    """The bar in the look of the game's own chat scroll bar: arrows up / down, a thin track with a tan thumb and the
    'to the newest line' button (drawn big, scaled down)."""
    from PIL import Image, ImageDraw
    S = 4
    w = BAR_W
    im = Image.new("RGBA", (w * S, h * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    tan, dim = (222, 196, 140, 255), (150, 132, 96, 255)
    col = tan if scrolled else dim

    def chevron(cy, up):
        cx, half, dy = w * S // 2, 5 * S, 3 * S
        a, b = (cy + dy, cy - dy) if up else (cy - dy, cy + dy)
        d.line([(cx - half, a), (cx, b), (cx + half, a)], fill=col, width=int(1.8 * S), joint="curve")

    chevron(BTN * S // 2, True)
    chevron(h * S - BTN * S - BTN * S // 2, False)
    cy = h * S - BTN * S // 2  # jump to the newest line: a double chevron
    chevron(cy - 3 * S, False)
    chevron(cy + 2 * S, False)
    t0, t1 = BTN * S, h * S - 2 * BTN * S
    cx = w * S // 2
    d.rounded_rectangle((cx - S, t0, cx + S, t1), radius=S, fill=(0, 0, 0, 120))  # track
    if t1 - t0 > 8 * S:
        y0 = t0 + int(first * (t1 - t0))
        y1 = max(y0 + 10 * S, t0 + int(last * (t1 - t0)))
        d.rounded_rectangle((cx - 3 * S, y0, cx + 3 * S, min(y1, t1)), radius=3 * S, fill=(200, 176, 120, 235),
                            outline=(90, 70, 30, 255), width=1)
    return im.resize((w, h), Image.LANCZOS)


MIN_THUMB = 23  # the game's MinimalScrollBar: minThumbExtent


def thumb_extent(track: int, first: float, last: float) -> tuple[int, int]:
    """(top, bottom) of the thumb inside a track of ``track`` px, the way the game's scroll bar does it: the thumb is as
    long as the part of the text that is visible (but never shorter than MIN_THUMB), and it travels the track minus its
    own length - so it shrinks as the text grows and still reaches both ends."""
    visible = max(1e-6, min(1.0, last - first))
    length = min(track, max(MIN_THUMB, round(visible * track)))
    pct = 0.0 if visible >= 1 else max(0.0, min(1.0, first / (1 - visible)))
    top = round(pct * (track - length))
    return top, top + length


def thumb_span(frame):
    """(top, bottom) of the thumb in screen y, or None."""
    rows, fit, sc = STATE["rows"], STATE["fit"], STATE["scroll"]
    if not frame or rows <= fit:
        return None
    t = frame[1]
    h = frame[3] - frame[1]
    _bar_h, t0, t1 = layout(h, is_scrolled())
    y0, y1 = thumb_extent(t1 - t0, (rows - sc - fit) / rows, (rows - sc) / rows)
    return t + t0 + y0, t + t0 + y1


def drag_to(y: int) -> bool:
    frame = STATE["frame"]
    rows, fit = STATE["rows"], STATE["fit"]
    if not frame or rows <= fit:
        return False
    h = frame[3] - frame[1]
    _bar_h, t0, t1 = layout(h, True)
    visible = fit / rows
    length = min(t1 - t0, max(MIN_THUMB, round(visible * (t1 - t0))))
    pct = max(0.0, min(1.0, (y - DRAG["off"] - frame[1] - t0) / max(1, (t1 - t0) - length)))
    first = pct * (1 - visible)  # the thumb follows the mouse exactly, not line by line
    new = clamp(round(rows - fit - first * rows), rows, fit)
    if STATE["thumb"] == first:
        return False
    STATE["thumb"], STATE["dirty"] = first, True
    if new != STATE["scroll"]:
        _log(f"drag to {y}: scroll {STATE['scroll']} -> {new}")
        STATE["scroll"] = new
    return True


def nudge(kind: str, x: int, y: int) -> bool:
    """Apply a wheel notch (kind 'wheel_up'/'wheel_down') or a left click at the screen point. True if it changed anything."""
    frame = STATE["frame"]
    if not frame or STATE["rows"] <= STATE["fit"]:
        _log(f"{kind} at {x},{y}: nothing to scroll (frame={frame}, rows={STATE['rows']}, fit={STATE['fit']})")
        return False
    l, t, r, b = frame
    inside = l <= x <= r + BAR_X + BAR_W and t <= y <= b
    delta = 0
    if kind == "wheel_up" and inside:
        delta = STEP
    elif kind == "wheel_down" and inside:
        delta = -STEP
    elif kind == "click":
        z = bar_zone(frame, x, y)
        sp = thumb_span(frame)
        if z in ("page_up", "page_down") and sp and sp[0] <= y <= sp[1]:
            DRAG["on"], DRAG["off"] = True, y - sp[0]
            _log(f"drag start at {x},{y}")
            return False
        delta = {"up": STEP, "down": -STEP, "page_up": STATE["fit"] - 1, "page_down": -(STATE["fit"] - 1)}.get(z, 0)
        if z == "bottom":
            delta = -STATE["scroll"]
    if not delta:
        if kind != "click":
            _log(f"{kind} at {x},{y}: outside (frame={frame})")
        return False
    new = clamp(STATE["scroll"] + delta, STATE["rows"], STATE["fit"])
    STATE["thumb"] = None
    _log(f"{kind} at {x},{y}: scroll {STATE['scroll']} -> {new}")
    if new == STATE["scroll"]:
        return False
    STATE["scroll"], STATE["dirty"] = new, True
    return True


def cursor_over(frame) -> bool:
    """Is the mouse pointer over the chat tab or its bar? (only reads the pointer position)"""
    if not frame:
        return False
    pt = wintypes.POINT()
    if not ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
        return False
    l, t, r, b = frame
    return l - 4 <= pt.x <= r + BAR_X + BAR_W and t <= pt.y <= b


def fade_level(now: float, over: bool) -> float:
    """How visible the bar is: FADE_IN while the mouse is over the chat (or the thumb is held), then it fades out over
    FADE_OUT seconds - the way the game's own chat does it. Quantised, so a repaint only happens when it visibly changes."""
    if over or DRAG["on"]:
        STATE["hover_t"] = now
        return FADE_IN
    gone = now - STATE.get("hover_t", -1e9)
    return round(max(0.0, FADE_IN * (1 - gone / FADE_OUT)) / 0.05) * 0.05


class _MSLLHOOK(ctypes.Structure):
    _fields_ = [("pt", wintypes.POINT), ("mouseData", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("extra", ctypes.c_size_t)]


def start_hook() -> threading.Thread | None:
    """Watch the mouse on a thread of its own. Returns the thread (None when the hook could not be installed)."""
    u = ctypes.windll.user32
    k = ctypes.windll.kernel32
    PROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
    u.CallNextHookEx.restype = ctypes.c_ssize_t
    u.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
    u.SetWindowsHookExW.restype = wintypes.HHOOK
    u.SetWindowsHookExW.argtypes = [ctypes.c_int, PROC, wintypes.HINSTANCE, wintypes.DWORD]
    k.GetModuleHandleW.restype = wintypes.HMODULE
    ready = threading.Event()
    box: dict = {}

    def proc(code, wparam, lparam):
        block = False
        try:
            if code == 0 and wparam in (WM_MOUSEWHEEL, WM_LBUTTONDOWN, WM_MOUSEMOVE, WM_LBUTTONUP):
                info = ctypes.cast(lparam, ctypes.POINTER(_MSLLHOOK)).contents
                x, y = info.pt.x, info.pt.y
                frame = STATE["frame"]
                scrollable = bool(frame) and STATE["rows"] > STATE["fit"]
                if wparam == WM_MOUSEWHEEL:
                    delta = ctypes.c_short((info.mouseData >> 16) & 0xFFFF).value
                    nudge("wheel_up" if delta > 0 else "wheel_down", x, y)
                    block = scrollable and frame[0] <= x <= frame[2] + BAR_X + BAR_W and frame[1] <= y <= frame[3]  # no camera zoom
                elif wparam == WM_LBUTTONDOWN:
                    nudge("click", x, y)
                    block = scrollable and bool(bar_zone(frame, x, y))  # the click belongs to the bar, not the camera
                    DRAG["swallow_up"] = block
                elif wparam == WM_MOUSEMOVE:
                    if DRAG["on"]:
                        drag_to(y)
                else:
                    DRAG["on"] = False
                    STATE["thumb"], STATE["dirty"] = None, True
                    block = bool(DRAG.pop("swallow_up", False))
        except Exception as exc:  # noqa: BLE001 - never let a hook callback fail
            _log(f"hook error: {exc!r}")
        if block:
            return 1  # swallowed: the game never sees it
        return u.CallNextHookEx(None, code, wparam, lparam)

    keep = PROC(proc)

    def loop() -> None:
        hook = u.SetWindowsHookExW(14, keep, k.GetModuleHandleW(None), 0)  # WH_MOUSE_LL
        box["ok"] = bool(hook)
        ready.set()
        if not hook:
            return
        msg = wintypes.MSG()
        while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            u.TranslateMessage(ctypes.byref(msg))
            u.DispatchMessageW(ctypes.byref(msg))

    t = threading.Thread(target=loop, daemon=True, name="chat-scroll-hook")
    t._keep = keep  # type: ignore[attr-defined]
    t.start()
    ready.wait(2)
    return t if box.get("ok") else None
