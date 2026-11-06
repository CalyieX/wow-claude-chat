"""The WoW frame of the browser overlay (same textures, same title strip, red X) around a plain Tk window.

Used by the panel, the harness editor and the CLI window, so every window over the game looks alike.
Drag the title strip to move it, the corner to resize it, X closes it. Put your widgets into ``win.inner``.
"""
from __future__ import annotations

from typing import Callable

DARK = "#0e0d09"
MIN_W, MIN_H = 320, 200


class FramedWindow:
    def __init__(self, title: str, w: int = 760, h: int = 520, x: int = 120, y: int = 90,
                 on_close: Callable[[], None] | None = None) -> None:
        import tkinter as tk
        self.title, self.w, self.h, self.on_close = title, w, h, on_close
        self.root = tk.Tk()
        r = self.root
        r.overrideredirect(True)
        r.attributes("-topmost", True)
        r.configure(bg=DARK)
        r.geometry(f"{w}x{h}+{x}+{y}")
        self.canvas = tk.Canvas(r, width=w, height=h, bg=DARK, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=DARK)
        self._win = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self._item = None
        self._photo = None
        self._pending = None
        self._drag: dict = {}
        self.canvas.bind("<Configure>", self._configure)
        self.canvas.bind("<Button-1>", self._down)
        self.canvas.bind("<B1-Motion>", self._move)
        r.after(50, self.focus)

    def focus(self) -> None:
        try:
            self.root.focus_force()
        except Exception:  # noqa: BLE001
            pass

    def set_title(self, title: str) -> None:
        if title != self.title:
            self.title = title
            self._draw()

    def close(self) -> None:
        if self.on_close:
            try:
                self.on_close()
            except Exception:  # noqa: BLE001
                pass
        self.root.destroy()

    # -- drawing -------------------------------------------------------------------------------------------------
    def _configure(self, e) -> None:
        self.w, self.h = e.width, e.height
        if self._pending:
            self.root.after_cancel(self._pending)
        self._pending = self.root.after(40, self._draw)  # one redraw after a resize, not one per pixel

    def _draw(self) -> None:
        from PIL import Image, ImageTk
        from . import overlay
        self._pending = None
        frame = overlay.compose(self.w, self.h, overlay.TOP, names=("close",), label=self.title)
        base = Image.new("RGBA", (self.w, self.h), (14, 13, 9, 255))
        base.alpha_composite(frame)
        self._photo = ImageTk.PhotoImage(base.convert("RGB"))
        if self._item is None:
            self._item = self.canvas.create_image(0, 0, image=self._photo, anchor="nw")
            self.canvas.tag_lower(self._item)
        else:
            self.canvas.itemconfigure(self._item, image=self._photo)
        inset = overlay.INSET + 4
        self.canvas.coords(self._win, inset, overlay.TOP)
        self.canvas.itemconfigure(self._win, width=max(10, self.w - 2 * inset), height=max(10, self.h - overlay.TOP - inset))

    # -- mouse ---------------------------------------------------------------------------------------------------
    def _down(self, e) -> None:
        from . import overlay
        bx, by, bw, bh = overlay.buttons(self.w)["close"]
        if bx <= e.x <= bx + bw and by <= e.y <= by + bh:
            self.close()
        elif e.x > self.w - 28 and e.y > self.h - 28:
            self._drag = {"mode": "size", "x": e.x_root, "y": e.y_root, "w": self.w, "h": self.h}
        elif e.y < overlay.TOP:
            self._drag = {"mode": "move", "x": e.x_root - self.root.winfo_x(), "y": e.y_root - self.root.winfo_y()}
        else:
            self._drag = {}
        self.focus()

    def _move(self, e) -> None:
        d = self._drag
        if d.get("mode") == "move":
            self.root.geometry(f"+{e.x_root - d['x']}+{e.y_root - d['y']}")
        elif d.get("mode") == "size":
            nw, nh = max(MIN_W, d["w"] + e.x_root - d["x"]), max(MIN_H, d["h"] + e.y_root - d["y"])
            self.root.geometry(f"{nw}x{nh}")
