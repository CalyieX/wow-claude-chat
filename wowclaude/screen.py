"""Grab the game window's client area (Windows only). The window must be visible, not covered, not minimised."""
from __future__ import annotations

import ctypes
from ctypes import wintypes

TITLES = ("World of Warcraft",)


class _Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def find_window() -> int:
    u = ctypes.windll.user32
    for title in TITLES:
        hwnd = u.FindWindowW(None, title)
        if hwnd:
            return hwnd
    return 0


def client_rect(hwnd: int):
    """(left, top, right, bottom) of the client area in screen pixels, or None."""
    u = ctypes.windll.user32
    if not hwnd or u.IsIconic(hwnd):
        return None
    rc = wintypes.RECT()
    if not u.GetClientRect(hwnd, ctypes.byref(rc)):
        return None
    pt = _Point(0, 0)
    u.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y, pt.x + rc.right, pt.y + rc.bottom


def grab_strip_area():
    """Screenshot of the top-left part of the game window (enough for the strip), or None."""
    from PIL import ImageGrab
    rect = client_rect(find_window())
    if rect is None:
        return None
    left, top, right, bottom = rect
    box = (left, top, min(right, left + 700), min(bottom, top + 200))
    try:
        return ImageGrab.grab(bbox=box, all_screens=True)
    except OSError:
        return None


def game_running() -> bool:
    return find_window() != 0
