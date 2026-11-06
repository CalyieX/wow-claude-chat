"""Panel: a small window over the game where the AI shows lists, builds and plans ([[overlay Title]]...[[/overlay]]).

Not a browser: no address bar, no page. It is always on top, can be dragged, closed with the X and is replaced
by the next panel the AI sends. The bridge writes ~/.wowclaude/panel.json and starts this window when needed.
Lines may carry WoW colour codes (|cffRRGGBB text |r) and bars ("[bar 0.6 00ff00] label").
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

from . import config

FILE = config.HOME / "panel.json"
BEAT = config.HOME / "panel.alive"
COLOR = re.compile(r"\|c[0-9a-fA-F]{2}([0-9a-fA-F]{6})(.*?)(?:\|r|$)", re.S)
BAR = re.compile(r"^\[bar\s+([0-9.]+)\s+([0-9a-fA-F]{6})\]\s*(.*)$")


def parse_line(line: str) -> tuple[str, object]:
    """("bar", (fraction, rrggbb, label)) or ("text", [(text, rrggbb or None), ...])."""
    m = BAR.match(line.strip())
    if m:
        try:
            frac = max(0.0, min(1.0, float(m.group(1))))
        except ValueError:
            frac = 0.0
        return "bar", (frac, m.group(2).lower(), m.group(3))
    parts, pos = [], 0
    for c in COLOR.finditer(line):
        if c.start() > pos:
            parts.append((line[pos:c.start()], None))
        parts.append((c.group(2), c.group(1).lower()))
        pos = c.end()
    if pos < len(line):
        parts.append((line[pos:], None))
    return "text", parts or [("", None)]


def alive(max_age: float = 3.0) -> bool:
    try:
        return time.time() - float(BEAT.read_text()) < max_age
    except (OSError, ValueError):
        return False


def show(title: str, lines: list[str]) -> None:
    """Called by the bridge: write the content and start the window if it is not open."""
    config.HOME.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps({"title": title, "lines": [str(x) for x in lines if not str(x).startswith("[img")],
                                "time": time.time()}), encoding="utf-8")
    if not alive():
        exe = Path(sys.executable).with_name("pythonw.exe")
        subprocess.Popen([str(exe if exe.exists() else sys.executable), "-m", "wowclaude", "panel"], creationflags=0x08000000)


def run() -> None:
    import tkinter as tk
    if alive():
        return
    gold, bg = "#ffd100", "#15130e"
    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.96)
    root.configure(bg="#c9a227")  # thin gold frame
    inner = tk.Frame(root, bg=bg)
    inner.pack(fill="both", expand=True, padx=2, pady=2)
    head = tk.Frame(inner, bg="#2a1a10")
    head.pack(fill="x")
    title = tk.Label(head, text="", bg="#2a1a10", fg=gold, font=("Georgia", 12), anchor="w")
    title.pack(side="left", padx=8, pady=3, fill="x", expand=True)
    tk.Button(head, text="X", command=root.destroy, bg="#5c1a10", fg=gold, bd=0, padx=8, activebackground="#7d2417",
              activeforeground=gold).pack(side="right")
    body = tk.Text(inner, bg=bg, fg="#f0e6c8", font=("Segoe UI", 11), wrap="word", bd=0, highlightthickness=0, width=52,
                   height=16, padx=10, pady=8, cursor="arrow", spacing1=2)
    body.pack(fill="both", expand=True)
    body.configure(state="disabled")
    drag = {}

    def start(e):
        drag["x"], drag["y"] = e.x_root - root.winfo_x(), e.y_root - root.winfo_y()

    def move(e):
        root.geometry(f"+{e.x_root - drag['x']}+{e.y_root - drag['y']}")

    for w in (head, title):
        w.bind("<Button-1>", start)
        w.bind("<B1-Motion>", move)
    seen = {"t": 0.0, "placed": False}

    def render(data: dict) -> None:
        title.config(text=str(data.get("title", "")))
        body.configure(state="normal")
        body.delete("1.0", "end")
        for line in data.get("lines", []):
            kind, val = parse_line(str(line))
            if kind == "bar":
                frac, col, label = val  # type: ignore[misc]
                cv = tk.Canvas(body, width=180, height=14, bg="#000000", highlightthickness=1, highlightbackground="#5c5c5c")
                cv.create_rectangle(0, 0, int(180 * frac), 14, fill="#" + col, width=0)
                body.window_create("end", window=cv)
                body.insert("end", "  " + label + "\n")
            else:
                for text, col in val:  # type: ignore[union-attr]
                    tag = "c" + (col or "none")
                    if col:
                        body.tag_configure(tag, foreground="#" + col)
                    body.insert("end", text, tag if col else ())
                body.insert("end", "\n")
        body.configure(state="disabled")
        if not seen["placed"]:
            seen["placed"] = True
            root.update_idletasks()
            x, y = 80, 80
            try:
                from . import overlay
                g = overlay.game_rect()
                if g:
                    x, y = g[2] - root.winfo_reqwidth() - 30, g[1] + 80
            except Exception:  # noqa: BLE001 - placement is a convenience
                pass
            root.geometry(f"+{max(0, x)}+{max(0, y)}")

    def tick() -> None:
        try:
            BEAT.write_text(str(time.time()))
            data = json.loads(FILE.read_text(encoding="utf-8"))
            if data.get("time", 0) != seen["t"]:
                seen["t"] = data.get("time", 0)
                render(data)
        except (OSError, ValueError):
            pass
        root.after(300, tick)

    def close() -> None:
        try:
            BEAT.unlink()
        except OSError:
            pass
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close)
    root.bind("<Destroy>", lambda e: BEAT.unlink(missing_ok=True) if e.widget is root else None)
    tick()
    root.mainloop()
