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
HEART = config.HOME / "fake.alive"
MARK_HOLE = 10  # px left transparent at both corners so the next screenshot still sees the marks


def alive(max_age: float = 4.0) -> bool:
    """True while the overlay program runs (it touches a heartbeat file every second)."""
    try:
        return time.time() - HEART.stat().st_mtime <= max_age
    except OSError:
        return False


def start() -> None:
    """Start the overlay in the background unless it already runs."""
    if alive():
        return
    import subprocess
    import sys
    from .winproc import hidden
    subprocess.Popen([sys.executable, "-m", "wowclaude", "fake"], **hidden())


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


def paint(entries: list[tuple[str, str]], size: tuple[int, int], scroll: int = 0, fsize: int = 17) -> Image.Image:
    # no background of its own: the real tab's see-through background shows, like a normal chat tab
    img = chat_marks.render(entries, size, scroll=scroll, bg=(0, 0, 0, 0), shadow=True, font_size=fsize)
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, MARK_HOLE - 1, MARK_HOLE - 1), fill=(0, 0, 0, 0))
    d.rectangle((size[0] - MARK_HOLE, 0, size[0] - 1, MARK_HOLE - 1), fill=(0, 0, 0, 0))
    d.rectangle((0, size[1] - MARK_HOLE, fsize + MARK_HOLE, size[1] - 1), fill=(0, 0, 0, 0))  # yellow mark sits fsize px in
    return img


def find_in_game() -> tuple[tuple[int, int, int, int], int] | None:
    """(screen rectangle of the chat tab, its text size in px), or None (tab hidden, game minimised, marks missing)."""
    g = overlay.game_rect()
    if g is None:
        return None
    from PIL import ImageGrab
    shot = ImageGrab.grab(bbox=g, all_screens=True)
    found = chat_marks.find_marks(shot)
    if found is None:
        return None
    f, font = found
    return (g[0] + f[0], g[1] + f[1], g[0] + f[2], g[1] + f[3]), font


def _make_window():
    import tkinter as tk
    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.geometry("10x10+-100+-100")
    root.update()
    u = ctypes.windll.user32
    u.GetParent.restype = ctypes.c_void_p
    u.GetParent.argtypes = [ctypes.c_void_p]
    hwnd = u.GetParent(root.winfo_id()) or root.winfo_id()
    u.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
    u.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
    ex = u.GetWindowLongW(hwnd, -20) | 0x80000 | 0x20 | 0x08000000 | 0x80  # LAYERED|TRANSPARENT|NOACTIVATE|TOOLWINDOW
    u.SetWindowLongW(hwnd, -20, ex)
    return root, hwnd


def run(poll: float = 0.25, find_every: float = 0.5) -> None:
    root, hwnd = _make_window()
    root.update()
    u = ctypes.windll.user32
    u.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
    u.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                               ctypes.c_int, ctypes.c_uint]
    park = lambda: overlay.update_layered(hwnd, Image.new('RGBA', (1, 1), (0, 0, 0, 0)), -100, -100)
    park()  # invisible until the tab is found (hiding the window itself made Tk lose it)
    entries: list[tuple[str, str]] = []
    offset = EVENTS.stat().st_size if EVENTS.exists() else 0
    frame, fs, last_find, shown_key, visible = None, 17, 0.0, None, False
    while True:
        try:
            root.update()
        except Exception as exc:  # noqa: BLE001 - window closed
            print(f'tk update failed: {exc}', flush=True)
            return
        try:
            HEART.parent.mkdir(parents=True, exist_ok=True)
            HEART.write_text(str(time.time()))
        except OSError:
            pass
        events, offset = read_new(offset)
        if events:
            entries = apply_events(entries, events)
            shown_key = None
        now = time.time()
        if now - last_find >= find_every:
            last_find = now
            try:
                found = find_in_game()
                frame, fs = found if found else (None, fs)
            except Exception as exc:  # noqa: BLE001 - a failed screenshot must not end the overlay
                print(f'find failed: {exc}', flush=True)
                frame = None
        if frame is None:
            if visible:
                park()
                visible = False
                shown_key = None
            time.sleep(poll)
            continue
        key = (frame, len(entries), entries[-1] if entries else None, fs)
        if key != shown_key or not visible:
            shown_key = key
            w, h = frame[2] - frame[0], frame[3] - frame[1]
            print(f'paint {frame} entries={len(entries)}', flush=True)
            overlay.update_layered(hwnd, paint(entries, (w, h), fsize=fs), frame[0], frame[1])
            visible = True
            u.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x1 | 0x2 | 0x10)  # topmost: NOSIZE|NOMOVE|NOACTIVATE
        time.sleep(poll)
