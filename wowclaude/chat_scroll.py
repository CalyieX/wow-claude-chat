"""Scrolling for the painted AI chat tab: mouse wheel over the tab, and the bar's arrows / track.

The painted tab is click-through (the real, empty tab lies under it), so the program only *watches* the mouse with a
read-only low-level hook on its own thread: it never moves, clicks or blocks anything.
"""
from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes

BAR_X = 6  # gap between the text area and the bar
BAR_W = 18  # width of the bar (up / down arrows, thumb)
EXTRA = BAR_X + BAR_W + 4  # how much wider than the text area the painted window is
STEP = 3  # lines per wheel notch / arrow click
BTN = 18  # height of an arrow button

STATE: dict = {"thumb": None, "scroll": 0, "frame": None, "rows": 0, "fit": 1, "dirty": False}
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


def bar_zone(frame, x: int, y: int) -> str:
    """Which part of the bar (it stands right of the text area) the screen point (x, y) is on:
    up, down, bottom (jump to the newest line), page_up, page_down, or ''."""
    if not frame:
        return ""
    l, t, r, b = frame
    h = b - t
    bx0 = (r - l) + BAR_X
    if not (bx0 <= x - l <= bx0 + BAR_W):
        return ""
    ry = y - t
    if ry < 0 or ry > h:
        return ""
    if ry < BTN:
        return "up"
    if ry > h - BTN:
        return "bottom"
    if ry > h - 2 * BTN:
        return "down"
    return "page_up" if ry < (BTN + h - 2 * BTN) / 2 else "page_down"


def bar_image(h: int, first: float, last: float, scrolled: bool):
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


def thumb_span(frame):
    """(top, bottom) of the thumb in screen y, or None."""
    rows, fit, sc = STATE["rows"], STATE["fit"], STATE["scroll"]
    if not frame or rows <= fit:
        return None
    t = frame[1]
    h = frame[3] - frame[1]
    t0, t1 = BTN, h - 2 * BTN
    y0 = t0 + int((rows - sc - fit) / rows * (t1 - t0))
    y1 = max(y0 + 10, t0 + int((rows - sc) / rows * (t1 - t0)))
    return t + y0, t + min(y1, t1)


def drag_to(y: int) -> bool:
    frame = STATE["frame"]
    rows, fit = STATE["rows"], STATE["fit"]
    if not frame or rows <= fit:
        return False
    h = frame[3] - frame[1]
    t0, t1 = BTN, h - 2 * BTN
    first = (y - DRAG["off"] - frame[1] - t0) / max(1, t1 - t0)
    first = max(0.0, min(first, (rows - fit) / rows))  # the thumb follows the mouse exactly, not line by line
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
