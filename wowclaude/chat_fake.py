"""The real WoW chat tab stays as an empty frame; this click-through overlay paints the conversation over it.

The addon puts a magenta square on the tab's top-left and a cyan one on its top-right and a yellow one on its bottom-left corner (see chat_marks).
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


def type_into_game(text: str) -> None:
    """Real keyboard input (SendInput) for the game: Enter, the text, Enter. The dock never takes the focus, so the game
    still has it. Messages posted to the window are ignored by the game's chat box, real input is not."""
    import ctypes
    from ctypes import wintypes

    class KI(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.c_size_t)]

    class MI(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class IU(ctypes.Union):
        _fields_ = [("ki", KI), ("mi", MI)]

    class IN(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", IU)]

    def send(vk: int = 0, ch: str = "") -> None:
        for up in (0, 2):
            if ch:
                ki = KI(0, ord(ch), 0x4 | up, 0, 0)  # KEYEVENTF_UNICODE
            else:
                ki = KI(vk, 0x1C if vk == 0x0D else 0, up, 0, 0)
            ctypes.windll.user32.SendInput(1, ctypes.byref(IN(1, IU(ki=ki))), ctypes.sizeof(IN))
            time.sleep(0.03)

    u = ctypes.windll.user32
    u.GetForegroundWindow.restype = ctypes.c_void_p
    game = u.FindWindowW("GxWindowClass", None)
    if not game or u.GetForegroundWindow() != game:  # never type into another program: the game must have the focus
        return
    send(vk=0x0D)
    time.sleep(0.15)
    for c in text:
        send(ch=c)
    time.sleep(0.1)
    send(vk=0x0D)


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
        for s in self.sprites.values():
            self.add_gear(s)
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
        self.win.bind("<Leave>", lambda e: self._draw("") if not self.drag else None)
        self.win.update()  # mapped from the start: a layered window that was withdrawn first refuses UpdateLayeredWindow
        self._layered()
        self._park()

    GEAR = 14  # the gear inside the button (top left of the dark slot) opens the addon menu
    OFF = 10  # 4 px of the gear stick out over the corner of the dark slot (which starts at 14)

    @staticmethod
    def add_gear(img) -> None:
        """A small gear (top left): 4x supersampled, gold with a dark outline."""
        import math
        from PIL import Image, ImageDraw
        k = 4
        g = Image.new("RGBA", (Dock.GEAR * k, Dock.GEAR * k), (0, 0, 0, 0))
        d = ImageDraw.Draw(g)
        c, r = Dock.GEAR * k / 2, Dock.GEAR * k / 2 - 2
        pts = []
        for i in range(16):  # 8 teeth
            ang = i * math.pi / 8
            rad = r if i % 2 == 0 else r * 0.72
            for a2 in (ang - math.pi / 16, ang + math.pi / 16):
                pts.append((c + rad * math.cos(a2), c + rad * math.sin(a2)))
        d.polygon(pts, fill=(255, 210, 40, 255), outline=(30, 20, 0, 255))
        d.ellipse((c - r * 0.3, c - r * 0.3, c + r * 0.3, c + r * 0.3), fill=(40, 26, 0, 255))
        img.alpha_composite(g.resize((Dock.GEAR, Dock.GEAR), Image.LANCZOS), (Dock.OFF, Dock.OFF))

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

    def _draw(self, state: str = "") -> None:
        self._layered()  # a Tk window that was moved or re-mapped may have lost the layered style: ask again every time
        overlay.update_layered(self.h, self.sprites[state], *self.pos)

    def _spot(self, g) -> tuple[int, int]:
        st = overlay.load_state()
        if g and st.get("brel"):
            return round(g[0] + st["brel"][0] * (g[2] - g[0])), round(g[1] + st["brel"][1] * (g[3] - g[1]))
        return int(st.get("bx", g[2] - 150)), int(st.get("by", g[1] + 80))

    def update(self) -> None:
        g = overlay.game_rect()
        want = bool(g) and not overlay.game_minimized() and not overlay.overlay_alive()
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
        elif not moved and self.OFF <= self.drag_start[0] < self.OFF + self.GEAR and self.OFF <= self.drag_start[1] < self.OFF + self.GEAR:  # the gear: open the addon menu
            import threading
            threading.Thread(target=lambda: type_into_game("/wac"), daemon=True).start()
        elif not moved and time.time() - self.busy > 45:  # the browser needs a while to start: no second click starts a second one
            self.busy = time.time()
            import threading
            threading.Thread(target=lambda: overlay.play(""), daemon=True).start()
            self._draw("")


def run(poll: float = 0.25, find_every: float = 0.5) -> None:
    root, hwnd = _make_window()
    root.update()
    dock = Dock(root) if hasattr(overlay, "slot_sprite") else None
    u = ctypes.windll.user32
    u.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
    u.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                               ctypes.c_int, ctypes.c_uint]
    park = lambda: overlay.update_layered(hwnd, Image.new('RGBA', (1, 1), (0, 0, 0, 0)), -100, -100)
    misses = 0
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
        if dock:
            try:
                dock.update()
            except Exception as exc:  # noqa: BLE001 - the button is a convenience, never stop the chat overlay
                _log(f'dock failed: {exc!r}')
        events, offset = read_new(offset)
        if events:
            entries = apply_events(entries, events)
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
            else:
                misses += 1
                if misses >= 3:  # one hidden marker (a tooltip over it) must not make the overlay blink away
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
            report_tab_size((w, h), fs)
            print(f'paint {frame} entries={len(entries)}', flush=True)
            overlay.update_layered(hwnd, paint(entries, (w, h), fsize=fs), frame[0], frame[1])
            visible = True
            u.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x1 | 0x2 | 0x10)  # topmost: NOSIZE|NOMOVE|NOACTIVATE
        time.sleep(poll)
