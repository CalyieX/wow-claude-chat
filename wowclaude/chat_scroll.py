"""Scrolling for the painted AI chat tab: mouse wheel over the tab, and the bar's arrows / track.

The painted tab is click-through (the real, empty tab lies under it), so the program only *watches* the mouse with a
read-only low-level hook on its own thread: it never moves, clicks or blocks anything.
"""
from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes

BAR_W = 16  # width of the scroll bar painted at the right edge of the tab
STEP = 3  # lines per wheel notch / arrow click

STATE: dict = {"scroll": 0, "frame": None, "rows": 0, "fit": 1, "dirty": False}

WM_MOUSEWHEEL, WM_LBUTTONDOWN = 0x020A, 0x0201


def clamp(scroll: int, rows: int, fit: int) -> int:
    return max(0, min(int(scroll), max(0, rows - fit)))


def bar_zone(frame, x: int, y: int) -> str:
    """Which part of the painted scroll bar the screen point (x, y) is on: up, down, page_up, page_down or ''."""
    if not frame:
        return ""
    l, t, r, b = frame
    w, h = r - l, b - t
    bx0 = w - BAR_W - 2
    if not (bx0 <= x - l <= bx0 + BAR_W):
        return ""
    ry = y - t
    top, bottom = BAR_W, BAR_W + (h - 2 * BAR_W)  # the image starts one bar width below the top
    if ry < top or ry > bottom:
        return ""
    if ry < top + BAR_W:
        return "up"
    if ry > bottom - BAR_W:
        return "down"
    return "page_up" if ry < (top + bottom) / 2 else "page_down"


def nudge(kind: str, x: int, y: int) -> bool:
    """Apply a wheel notch (kind 'wheel_up'/'wheel_down') or a left click at the screen point. True if it changed anything."""
    frame = STATE["frame"]
    if not frame or STATE["rows"] <= STATE["fit"]:
        return False
    l, t, r, b = frame
    inside = l <= x <= r and t <= y <= b
    delta = 0
    if kind == "wheel_up" and inside:
        delta = STEP
    elif kind == "wheel_down" and inside:
        delta = -STEP
    elif kind == "click":
        z = bar_zone(frame, x, y)
        delta = {"up": STEP, "down": -STEP, "page_up": STATE["fit"] - 1, "page_down": -(STATE["fit"] - 1)}.get(z, 0)
    if not delta:
        return False
    new = clamp(STATE["scroll"] + delta, STATE["rows"], STATE["fit"])
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
        try:
            if code == 0 and wparam in (WM_MOUSEWHEEL, WM_LBUTTONDOWN):
                info = ctypes.cast(lparam, ctypes.POINTER(_MSLLHOOK)).contents
                if wparam == WM_MOUSEWHEEL:
                    delta = ctypes.c_short((info.mouseData >> 16) & 0xFFFF).value
                    nudge("wheel_up" if delta > 0 else "wheel_down", info.pt.x, info.pt.y)
                else:
                    nudge("click", info.pt.x, info.pt.y)
        except Exception:  # noqa: BLE001 - never let a hook callback fail
            pass
        return u.CallNextHookEx(None, code, wparam, lparam)  # always pass the event on

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
