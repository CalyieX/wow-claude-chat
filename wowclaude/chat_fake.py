"""The real WoW chat tab stays as an empty frame; this click-through overlay paints the conversation over it.

The addon puts a magenta square on the tab's top-left and a cyan one on its top-right and a yellow one on its bottom-left corner (see chat_marks).
A screenshot of the game tells where the tab is right now, wherever the player moved or resized it. The bridge
posts events (question / thinking / answer) into a small file; the overlay draws them. No reload, no reply slots.
"""
from __future__ import annotations

import ctypes
import json
import os
import time
from ctypes import wintypes

from PIL import Image, ImageDraw

from . import chat_marks, chat_scroll, config, overlay

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


_MUTEX = []  # keeps the handle of the single-instance lock alive as long as this process runs


def single_instance(name: str = "Local\\wowclaude-chat-overlay") -> bool:
    """True for the first overlay program only. The bridge starts a new one whenever the heartbeat is older than 4 seconds
    (a busy PC is enough), and without this lock the old one kept running too: two programs painting the same chat."""
    import ctypes
    if os.name != "nt":
        return True
    k32 = ctypes.windll.kernel32
    k32.CreateMutexW.restype = ctypes.c_void_p
    handle = k32.CreateMutexW(None, False, name)
    if not handle:
        return True  # cannot tell: better two overlays than none
    if k32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        k32.CloseHandle(ctypes.c_void_p(handle))
        return False
    _MUTEX.append(handle)
    return True


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
        if kind == "cli":  # the screen of the command line tool: one entry that is replaced on every update
            entries = [e for e in entries if e[0] != "cli"]
            if text:
                entries.append(("cli", text))
            continue
        if kind != "think" and entries and entries[-1][0] == "think":
            entries.pop()  # the answer replaces "thinking ..."
        entries.append((kind, text))
    return entries[-MAX_ENTRIES:]


def mono_font(fsize: int):
    from PIL import ImageFont
    for path in (r"C:\Windows\Fonts\consola.ttf", r"C:\Windows\Fonts\cour.ttf"):
        try:
            return ImageFont.truetype(path, max(9, fsize - 4))
        except OSError:
            continue
    return ImageFont.load_default(size=max(9, fsize - 4))


def cell_size(fsize: int) -> tuple[int, int]:
    font = mono_font(fsize)
    return max(1, int(font.getlength("M"))), int(font.size * 1.25)


def report_tab_size(size: tuple[int, int], fsize: int) -> None:
    """Columns and rows that fit into the tab: CLI mode starts the command line tool with exactly this size."""
    cw, ch = cell_size(fsize)
    data = {"cols": max(20, (size[0] - 12) // cw), "rows": max(5, (size[1] - 8) // ch)}
    try:
        (config.HOME / "tabsize.json").write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass


def paint_cli(text: str, size: tuple[int, int], fsize: int) -> Image.Image:
    font = mono_font(fsize)
    cw, ch = cell_size(fsize)
    img = Image.new("RGBA", size, (0, 0, 0, 120))  # a darker, see-through background: the tool draws a lot of text
    d = ImageDraw.Draw(img)
    for i, line in enumerate(text.split("\n")[: max(1, (size[1] - 8) // ch)]):
        d.text((7, 5 + i * ch), line, fill=(0, 0, 0, 255), font=font)
        d.text((6, 4 + i * ch), line, fill=(235, 235, 235, 255), font=font)
    return img


def paint(entries: list[tuple[str, str]], size: tuple[int, int], scroll: int = 0, fsize: int = 17) -> Image.Image:
    if entries and entries[-1][0] == "cli":
        img = paint_cli(entries[-1][1], size, fsize)
        d = ImageDraw.Draw(img)
        d.rectangle((0, 0, MARK_HOLE - 1, MARK_HOLE - 1), fill=(0, 0, 0, 0))
        d.rectangle((size[0] - MARK_HOLE, 0, size[0] - 1, MARK_HOLE - 1), fill=(0, 0, 0, 0))
        d.rectangle((0, size[1] - MARK_HOLE, fsize + MARK_HOLE, size[1] - 1), fill=(0, 0, 0, 0))
        return img
    # no background of its own: the real tab's see-through background shows, like a normal chat tab
    img = chat_marks.render(entries, size, scroll=scroll, bg=(0, 0, 0, 0), shadow=True, font_size=fsize)
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, MARK_HOLE - 1, MARK_HOLE - 1), fill=(0, 0, 0, 0))
    d.rectangle((size[0] - MARK_HOLE, 0, size[0] - 1, MARK_HOLE - 1), fill=(0, 0, 0, 0))
    d.rectangle((0, size[1] - MARK_HOLE, fsize + MARK_HOLE, size[1] - 1), fill=(0, 0, 0, 0))  # yellow mark sits fsize px in
    return img


_last_frame: list = [None]  # last tab rectangle relative to the game window: searched first (a small crop is much faster)


EXTERNAL_BUTTON = False  # the WAC button is an addon element now (KKWacButton); the old window above the game stays off


def find_in_game() -> tuple[tuple[int, int, int, int], int] | None:
    """(screen rectangle of the chat tab, its text size in px), or None (tab hidden, game minimised, marks missing)."""
    g = overlay.game_rect()
    if g is None:
        return None
    from PIL import ImageGrab
    w, h = g[2] - g[0], g[3] - g[1]
    last = _last_frame[0]
    if last:  # near the old place first; the tab rarely moves
        pad = 120
        l, t = max(0, last[0] - pad), max(0, last[1] - pad)
        r, b = min(w, last[2] + pad), min(h, last[3] + pad)
        found = chat_marks.find_marks(ImageGrab.grab(bbox=(g[0] + l, g[1] + t, g[0] + r, g[1] + b), all_screens=True))
        if found:
            f, font = found
            f = (f[0] + l, f[1] + t, f[2] + l, f[3] + t)
            _last_frame[0] = f
            return (g[0] + f[0], g[1] + f[1], g[0] + f[2], g[1] + f[3]), font
    found = chat_marks.find_marks(ImageGrab.grab(bbox=g, all_screens=True))
    if found is None:
        _last_frame[0] = None
        return None
    f, font = found
    _last_frame[0] = f
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


def _log(text: str) -> None:
    try:
        with open(config.HOME / 'dock.log', 'a', encoding='utf-8') as f:
            f.write(text + chr(10))
    except OSError:
        pass


def click_screen(x: int, y: int) -> None:
    """A real left click at a screen position, then the mouse pointer goes back. (The game takes the click position from the
    real pointer, not from posted window messages.)"""
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    old = wintypes.POINT()
    u.GetCursorPos(ctypes.byref(old))
    u.SetCursorPos(x, y)
    time.sleep(0.12)
    u.mouse_event(0x0002, 0, 0, 0, 0)  # left down
    time.sleep(0.06)
    u.mouse_event(0x0004, 0, 0, 0, 0)  # left up
    time.sleep(0.08)
    u.SetCursorPos(old.x, old.y)


class Dock:
    """The always-on WAC button: shown whenever the browser window is not running, click opens it, drag moves it.
    (While the browser window runs it draws its own frame / minimized button, using the same remembered spot.)"""

    def __init__(self, root) -> None:
        import tkinter as tk
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.geometry("64x64+-200+-200")
        self.h = 0
        self._layered()
        self.sprites = {s: overlay.slot_sprite(s) for s in ("", "hover", "down")}
        self.sprites["gear"] = overlay.slot_sprite("hover")  # pointer on the gear: the badge turns light blue
        for name, s in self.sprites.items():
            self.add_gear(s, hot=name == "gear")
        self.on_gear = False
        self.cur = ""
        self.pos = (-200, -200)
        self.shown = False
        self.drag: dict = {}
        self.drag_start = (99, 99)
        self.busy = 0.0
        self.n = 0
        self.win.bind("<Button-1>", self._down)
        self.win.bind("<B1-Motion>", self._move)
        self.win.bind("<ButtonRelease-1>", self._up)
        self.win.bind("<Enter>", lambda e: self._draw("hover") if not self.drag else None)
        self.win.bind("<Motion>", self._hover)
        self.win.bind("<Leave>", lambda e: (setattr(self, 'on_gear', False), self._draw("")) if not self.drag else None)
        self.win.update()  # mapped from the start: a layered window that was withdrawn first refuses UpdateLayeredWindow
        self._layered()
        self._park()

    GEAR = 14  # diameter of the round gear badge on the button (top left) that opens the addon menu
    OFF = 9  # 5 px of the gear stick out over the corner of the dark slot (which starts at 14)

    @staticmethod
    def add_gear(img, hot: bool = False) -> None:
        """The gear badge (top left): a round dark blue button with a grey ring like the button frame and a small gold gear, light blue while the
        pointer is on it. 4x supersampled."""
        import math
        from PIL import Image, ImageDraw
        k, n = 4, Dock.GEAR
        g = Image.new("RGBA", (n * k, n * k), (0, 0, 0, 0))
        d = ImageDraw.Draw(g)
        fill = (70, 150, 235, 255) if hot else (16, 34, 92, 255)
        d.ellipse((1, 1, n * k - 2, n * k - 2), fill=fill, outline=(16, 12, 8, 255), width=k)  # dark outer edge ...
        d.ellipse((1 + k, 1 + k, n * k - 2 - k, n * k - 2 - k), outline=(105, 103, 105, 255), width=k)  # ... grey ring like the button frame
        c, r = n * k / 2, n * k / 2 - 5 * k / 2
        pts = []
        for i in range(16):  # 8 teeth
            ang = i * math.pi / 8
            rad = r if i % 2 == 0 else r * 0.72
            for a2 in (ang - math.pi / 16, ang + math.pi / 16):
                pts.append((c + rad * math.cos(a2), c + rad * math.sin(a2)))
        d.polygon(pts, fill=(255, 210, 40, 255))
        d.ellipse((c - r * 0.3, c - r * 0.3, c + r * 0.3, c + r * 0.3), fill=fill)
        img.alpha_composite(g.resize((n, n), Image.LANCZOS), (Dock.OFF, Dock.OFF))

    def _over_gear(self, e) -> bool:
        c = self.OFF + self.GEAR / 2
        return (e.x - c) ** 2 + (e.y - c) ** 2 <= (self.GEAR / 2) ** 2

    def _hover(self, e) -> None:
        if self.drag:
            return
        on = self._over_gear(e)
        if on != self.on_gear:
            self.on_gear = on
            self._draw("gear" if on else "hover")

    def _park(self) -> None:
        from PIL import Image
        overlay.update_layered(self.h, Image.new("RGBA", (1, 1), (0, 0, 0, 0)), -200, -200)

    def _layered(self) -> None:
        """(Re)apply the layered style: Tk may create a new native window when it is shown again."""
        self.win.update_idletasks()
        u = overlay.user32  # same calls as the browser overlay's own minimized button, which is known to draw
        u.GetAncestor.restype = ctypes.c_void_p  # GetParent would return the owner (our own root window) for an owned popup
        u.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        u.GetWindowLongW.restype = ctypes.c_long
        self.h = u.GetAncestor(self.win.winfo_id(), 2) or self.win.winfo_id()  # GA_ROOT
        u.SetWindowLongW(ctypes.c_void_p(self.h), overlay.GWL_EXSTYLE,
                         u.GetWindowLongW(ctypes.c_void_p(self.h), overlay.GWL_EXSTYLE) | overlay.WS_EX_LAYERED | overlay.WS_EX_TOOLWINDOW | 0x08000000)  # NOACTIVATE: a click never takes the keyboard from the game

    def _draw(self, state: str | None = None) -> None:
        if state is None:  # the periodic repaint keeps the current look (hover, gear glow) instead of resetting it
            state = self.cur
        self.cur = state
        self._layered()  # a Tk window that was moved or re-mapped may have lost the layered style: ask again every time
        overlay.update_layered(self.h, self.sprites[state], *self.pos)

    def _spot(self, g) -> tuple[int, int]:
        st = overlay.load_state()
        if g and st.get("brel"):
            return round(g[0] + st["brel"][0] * (g[2] - g[0])), round(g[1] + st["brel"][1] * (g[3] - g[1]))
        return int(st.get("bx", g[2] - 150)), int(st.get("by", g[1] + 80))

    def update(self, ui_ok: bool = True) -> None:
        """ui_ok: the addon's marks are on screen. Without them the game shows no interface (loading screen, /reload): the button
        belongs to that interface, so it goes with it - like an addon inside the game."""
        g = overlay.game_rect()
        want = EXTERNAL_BUTTON and bool(g) and ui_ok and not overlay.game_minimized() and not overlay.overlay_alive()
        if want != getattr(self, '_want', None):
            self._want = want
            _log(f'dock want={want} game={g}')
        if self.drag:
            return
        if not want:
            if self.shown:
                self._park()
                self.shown = False
            return
        x, y = self._spot(g)
        if not (g[0] - 20 <= x <= g[2] - 44 and g[1] - 20 <= y <= g[3] - 44):
            x, y = g[2] - 150, g[1] + 80
        if not self.shown or (x, y) != self.pos:
            self.pos = (x, y)
            self.shown = True
            self._draw()
        ctypes.windll.user32.SetWindowPos(ctypes.c_void_p(self.h), ctypes.c_void_p(-1), 0, 0, 0, 0, 0x53)
        self.n += 1
        if self.n % 8 == 0 and not self.drag:  # Tk may paint its plain background over the picture after (re)mapping: repaint
            self._draw()

    def _down(self, e) -> None:
        self.drag_start = (e.x, e.y)
        self.drag = {"dx": e.x_root - self.pos[0], "dy": e.y_root - self.pos[1], "sx": e.x_root, "sy": e.y_root, "moved": False}
        self._draw("down")

    def _move(self, e) -> None:
        d = self.drag
        if not d:
            return
        if abs(e.x_root - d["sx"]) + abs(e.y_root - d["sy"]) > 4:
            d["moved"] = True
        if d["moved"]:
            self.pos = (e.x_root - d["dx"], e.y_root - d["dy"])
            self._draw("down")

    def _up(self, _e) -> None:
        moved = self.drag.get("moved")
        self.drag = {}
        g = overlay.game_rect()
        if moved and g:
            overlay.save_state(bx=self.pos[0], by=self.pos[1], brel=overlay.to_rel(g, self.pos[0], self.pos[1], 64, 64)[:2])
            self._draw()
        elif not moved and (self.drag_start[0] - self.OFF - self.GEAR / 2) ** 2 + (self.drag_start[1] - self.OFF - self.GEAR / 2) ** 2 <= (self.GEAR / 2) ** 2:  # the gear: open the addon menu
            g = overlay.game_rect()
            if g:  # a click into the addon's invisible field in the bottom left corner of the game opens the menu
                import threading
                threading.Thread(target=lambda: click_screen(g[0] + 8, g[3] - 8), daemon=True).start()
        elif not moved and time.time() - self.busy > 45:  # the browser needs a while to start: no second click starts a second one
            self.busy = time.time()
            import threading
            threading.Thread(target=lambda: overlay.play(""), daemon=True).start()
            self._draw("")


def run(poll: float = 0.25, find_every: float = 0.5) -> None:
    if not single_instance():
        return  # another overlay program already paints the chat
    root, hwnd = _make_window()
    root.update()
    dock = Dock(root) if hasattr(overlay, "slot_sprite") else None
    u = ctypes.windll.user32
    u.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
    u.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                               ctypes.c_int, ctypes.c_uint]
    park = lambda: overlay.update_layered(hwnd, Image.new('RGBA', (1, 1), (0, 0, 0, 0)), -100, -100)
    misses = 0
    chat_scroll.LOG = config.HOME / "scroll.log"
    try:
        chat_scroll.start_hook()  # mouse wheel and scroll bar over the painted tab (read-only watching)
    except Exception as exc:  # noqa: BLE001 - scrolling is a convenience
        _log(f'scroll hook failed: {exc!r}')
    park()  # invisible until the tab is found (hiding the window itself made Tk lose it)
    entries: list[tuple[str, str]] = []
    offset = 0  # replay the recent history, so a restart does not empty the tab
    if EVENTS.exists():
        size = EVENTS.stat().st_size
        offset = max(0, size - 40000)
        if offset:
            raw = EVENTS.read_bytes()
            nxt = raw.find(b"\n", offset)
            offset = size if nxt < 0 else nxt + 1
    frame, fs, last_find, shown_key, visible = None, 17, 0.0, None, False
    ui_ok = True  # False while the addon's marks stay away (loading screen)
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
        if dock:
            try:
                dock.update(ui_ok)
            except Exception as exc:  # noqa: BLE001 - the button is a convenience, never stop the chat overlay
                _log(f'dock failed: {exc!r}')
        events, offset = read_new(offset)
        if events:
            entries = apply_events(entries, events)
            chat_scroll.STATE["scroll"] = 0  # a new line: back to the bottom, like the game's own chat
            shown_key = None
        now = time.time()
        if now - last_find >= find_every:
            last_find = now
            try:
                found = find_in_game()
            except Exception as exc:  # noqa: BLE001 - a failed screenshot must not end the overlay
                print(f'find failed: {exc}', flush=True)
                found = None
            if found:
                frame, fs = found
                misses = 0
                ui_ok = True
            else:
                misses += 1
                if misses >= 2:
                    ui_ok = False
                if misses >= 3:  # one hidden marker (a tooltip over it) must not make the overlay blink away
                    frame = None
        if frame is None:
            if visible:
                park()
                visible = False
                shown_key = None
            time.sleep(poll)
            continue
        w, h = frame[2] - frame[0], frame[3] - frame[1]
        if not (entries and entries[-1][0] == "cli"):
            rows, fit = chat_marks.row_metrics(entries, (w, h), fs)
            chat_scroll.STATE.update(frame=frame, rows=rows, fit=fit)
            chat_scroll.STATE["scroll"] = chat_scroll.clamp(chat_scroll.STATE["scroll"], rows, fit)
        else:
            chat_scroll.STATE.update(frame=None, rows=0, fit=1, scroll=0)
        chat_scroll.STATE["dirty"] = False
        key = (frame, len(entries), entries[-1] if entries else None, fs, chat_scroll.STATE["scroll"])
        if key != shown_key or not visible:
            shown_key = key
            report_tab_size((w, h), fs)
            print(f'paint {frame} entries={len(entries)} scroll={chat_scroll.STATE["scroll"]}', flush=True)
            img = paint(entries, (w, h), scroll=chat_scroll.STATE["scroll"], fsize=fs)
            if chat_scroll.STATE["rows"] > chat_scroll.STATE["fit"] and not (entries and entries[-1][0] == "cli"):
                wide = Image.new("RGBA", (w + chat_scroll.EXTRA, h), (0, 0, 0, 0))
                wide.paste(img, (0, 0))
                rows, fit, sc = chat_scroll.STATE["rows"], chat_scroll.STATE["fit"], chat_scroll.STATE["scroll"]
                end = rows - sc
                bar = chat_scroll.bar_image(h, max(0, end - fit) / rows, end / rows, sc > 0)
                wide.alpha_composite(bar, (w + chat_scroll.BAR_X, 0))
                img = wide
            overlay.update_layered(hwnd, img, frame[0], frame[1])
            visible = True
            u.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x1 | 0x2 | 0x10)  # topmost: NOSIZE|NOMOVE|NOACTIVATE
        for _ in range(max(1, int(poll / 0.02))):  # short naps: a wheel notch is shown within ~20 ms
            if chat_scroll.STATE["dirty"]:
                break
            time.sleep(0.02)
