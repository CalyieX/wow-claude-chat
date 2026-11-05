"""The real WoW chat tab stays as an empty frame; this click-through overlay paints the conversation over it.

The addon puts a magenta square on the tab's top-left and a cyan one on its bottom-right corner (see chat_marks).
A screenshot of the game tells where the tab is right now, wherever the player moved or resized it. The bridge
posts events (question / thinking / answer) into a small file; the overlay draws them. No reload, no reply slots.
"""
from __future__ import annotations

import ctypes
import json
import time
from ctypes import wintypes

from PIL import Image, ImageDraw

from . import chat_marks, config, overlay

EVENTS = config.HOME / "chat_events.jsonl"
MAX_ENTRIES = 300
MARK_HOLE = 10  # px left transparent at both corners so the next screenshot still sees the marks


def post(kind: str, text: str, path=None) -> None:
    """Called by the bridge: kind is user | think | ai | sys. A ``think`` entry is replaced by the next answer."""
    p = path or EVENTS
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps({"t": time.time(), "kind": kind, "text": text}, ensure_ascii=False) + "\n")


def read_new(offset: int, path=None) -> tuple[list[dict], int]:
    p = path or EVENTS
    try:
        data = p.read_bytes()
    except OSError:
        return [], offset
    if offset > len(data):  # the file was reset
        offset = 0
    out = []
    end = offset
    for raw in data[offset:].splitlines(keepends=True):
        if not raw.endswith(b"\n"):
            break  # half-written line: wait for the rest
        end += len(raw)
        try:
            out.append(json.loads(raw))
        except ValueError:
            pass
    return out, end


def apply_events(entries: list[tuple[str, str]], events: list[dict]) -> list[tuple[str, str]]:
    entries = list(entries)
    for ev in events:
        kind, text = ev.get("kind", "sys"), str(ev.get("text", ""))
        if kind != "think" and entries and entries[-1][0] == "think":
            entries.pop()  # the answer replaces "thinking ..."
        entries.append((kind, text))
    return entries[-MAX_ENTRIES:]


def paint(entries: list[tuple[str, str]], size: tuple[int, int], scroll: int = 0) -> Image.Image:
    img = chat_marks.render(entries, size, scroll=scroll).convert("RGBA")
    img.putalpha(235)
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, MARK_HOLE - 1, MARK_HOLE - 1), fill=(0, 0, 0, 0))
    d.rectangle((size[0] - MARK_HOLE, size[1] - MARK_HOLE, size[0] - 1, size[1] - 1), fill=(0, 0, 0, 0))
    return img


def find_in_game() -> tuple[int, int, int, int] | None:
    """Screen rectangle of the chat tab, or None (tab hidden, game minimised, marks missing)."""
    g = overlay.game_rect()
    if g is None:
        return None
    from PIL import ImageGrab
    shot = ImageGrab.grab(bbox=g, all_screens=True)
    f = chat_marks.find_frame(shot)
    if f is None:
        return None
    return g[0] + f[0], g[1] + f[1], g[0] + f[2], g[1] + f[3]


def _make_window():
    import tkinter as tk
    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.geometry("10x10+-100+-100")
    root.update()
    u = ctypes.windll.user32
    hwnd = u.GetParent(root.winfo_id()) or root.winfo_id()
    ex = u.GetWindowLongW(hwnd, -20) | 0x80000 | 0x20 | 0x08000000 | 0x80  # LAYERED|TRANSPARENT|NOACTIVATE|TOOLWINDOW
    u.SetWindowLongW(hwnd, -20, ex)
    return root, hwnd


def run(poll: float = 0.25, find_every: float = 0.5) -> None:
    root, hwnd = _make_window()
    root.withdraw()
    entries: list[tuple[str, str]] = []
    offset = EVENTS.stat().st_size if EVENTS.exists() else 0
    frame, last_find, shown_key, visible = None, 0.0, None, False
    u = ctypes.windll.user32
    while True:
        try:
            root.update()
        except Exception:  # noqa: BLE001 - window closed
            return
        events, offset = read_new(offset)
        if events:
            entries = apply_events(entries, events)
            shown_key = None
        now = time.time()
        if now - last_find >= find_every:
            last_find = now
            try:
                frame = find_in_game()
            except Exception:  # noqa: BLE001 - a failed screenshot must not end the overlay
                frame = None
        if frame is None:
            if visible:
                root.withdraw()
                visible = False
            time.sleep(poll)
            continue
        key = (frame, len(entries), entries[-1] if entries else None)
        if key != shown_key or not visible:
            shown_key = key
            w, h = frame[2] - frame[0], frame[3] - frame[1]
            if not visible:
                root.deiconify()
                visible = True
            overlay.update_layered(hwnd, paint(entries, (w, h)), frame[0], frame[1])
            u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int, wintypes.UINT]
            u.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(-1), frame[0], frame[1], w, h, 0x10 | 0x40)
        time.sleep(poll)
