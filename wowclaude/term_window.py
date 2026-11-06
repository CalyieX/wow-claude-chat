"""A real window for CLI mode: scroll with the mouse wheel, select + copy, paste, type directly.

The command line tool itself runs inside the game's AI program (cli_mode.py). This window only shows its screen
(cli_screen.json, with the scrollback) and sends what you type back (cli_in.jsonl). It opens with /term (or the menu
button "CLI window") and has no console window. Click into it to type; click the game to play on.
"""
from __future__ import annotations

import json
import time

from . import config

SCREEN = config.HOME / "cli_screen.json"
INPUT = config.HOME / "cli_in.jsonl"
SIZE = config.HOME / "termsize.json"
BEAT = config.HOME / "term.alive"

KEYS = {"Return": "\r", "BackSpace": "\x7f", "Tab": "\t", "Escape": "\x1b", "Up": "\x1b[A", "Down": "\x1b[B",
        "Right": "\x1b[C", "Left": "\x1b[D", "Home": "\x1b[H", "End": "\x1b[F", "Prior": "\x1b[5~", "Next": "\x1b[6~",
        "Delete": "\x1b[3~", "ISO_Left_Tab": "\x1b[Z"}


def alive(max_age: float = 3.0) -> bool:
    try:
        return time.time() - float(BEAT.read_text()) < max_age
    except (OSError, ValueError):
        return False


def send(raw: str) -> None:
    try:
        with open(INPUT, "a", encoding="utf-8") as f:
            f.write(json.dumps({"raw": raw}) + "\n")
    except OSError:
        pass


def run() -> None:
    import tkinter as tk
    import tkinter.font as tkfont
    if alive():
        return  # one window is enough
    from .wowframe import FramedWindow

    def cleanup() -> None:
        BEAT.unlink(missing_ok=True)
        SIZE.unlink(missing_ok=True)

    win = FramedWindow("WoW AI - CLI", 900, 540, on_close=cleanup)
    root = win.root
    font = tkfont.Font(family="Consolas", size=11)
    text = tk.Text(win.inner, bg="#101418", fg="#e6e6e6", insertbackground="#e6e6e6", font=font, wrap="none", bd=0,
                   highlightthickness=0, selectbackground="#3a5a8c", cursor="xterm")
    bar = tk.Scrollbar(win.inner, command=text.yview)
    text.configure(yscrollcommand=bar.set)
    bar.pack(side="right", fill="y")
    text.pack(side="left", fill="both", expand=True)
    text.configure(state="disabled")
    cw, ch = font.measure("0"), font.metrics("linespace")
    state = {"seen": None, "size": None}

    def copy(_e=None):
        try:
            sel = text.get("sel.first", "sel.last")
        except tk.TclError:
            return None  # nothing selected: Ctrl+C goes to the tool as an interrupt
        root.clipboard_clear()
        root.clipboard_append(sel)
        return "break"

    def paste(_e=None):
        try:
            data = root.clipboard_get()
        except tk.TclError:
            return "break"
        send(data.replace("\r\n", "\n").replace("\n", "\r"))
        return "break"

    def on_key(e):
        ctrl = bool(e.state & 0x4)
        if ctrl and e.keysym.lower() == "c":
            return copy() or send("\x03") or "break"
        if ctrl and e.keysym.lower() == "v":
            return paste()
        if ctrl and len(e.keysym) == 1 and e.keysym.isalpha():
            send(chr(ord(e.keysym.lower()) - 96))
            return "break"
        if e.keysym in KEYS:
            send(KEYS[e.keysym])
        elif e.char and e.char.isprintable():
            send(e.char)
        return "break"

    text.bind("<Key>", on_key)
    text.bind("<Control-Shift-C>", lambda e: copy() or "break")
    text.bind("<Button-1>", lambda e: (win.focus(), text.focus_set()))
    text.bind("<Button-3>", lambda e: paste())  # right click pastes, like most terminals
    text.focus_set()

    def tick():
        try:
            BEAT.write_text(str(time.time()))
            cols = max(20, min(200, (text.winfo_width() - 4) // cw))
            rows = max(5, min(60, text.winfo_height() // ch))
            if state["size"] != (cols, rows) or int(time.time()) % 2 == 0:
                state["size"] = (cols, rows)
                SIZE.write_text(json.dumps({"cols": cols, "rows": rows, "time": time.time()}))
            raw = SCREEN.read_text(encoding="utf-8")
            if raw != state["seen"]:
                state["seen"] = raw
                body = json.loads(raw).get("text", "")
                at_end = text.yview()[1] >= 0.999
                top = text.yview()[0]
                text.configure(state="normal")
                text.delete("1.0", "end")
                text.insert("1.0", body)
                text.configure(state="disabled")
                if at_end:
                    text.see("end")
                else:
                    text.yview_moveto(top)
        except (OSError, ValueError):
            pass
        root.after(150, tick)

    root.bind("<Destroy>", lambda e: cleanup() if e.widget is root else None)
    tick()
    root.mainloop()
