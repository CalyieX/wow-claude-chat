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
    from .wowframe import FramedWindow
    bg = "#15130e"

    def cleanup() -> None:
        BEAT.unlink(missing_ok=True)

    win = FramedWindow("WoW AI", 560, 420, on_close=cleanup)
    root = win.root
    body = tk.Text(win.inner, bg=bg, fg="#f0e6c8", font=("Segoe UI", 11), wrap="word", bd=0, highlightthickness=0,
                   padx=10, pady=8, cursor="arrow", spacing1=2)
    sb = tk.Scrollbar(win.inner, command=body.yview)
    body.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")
    body.pack(side="left", fill="both", expand=True)
    body.configure(state="disabled")
    seen = {"t": 0.0, "placed": False}

    def render(data: dict) -> None:
        win.set_title(str(data.get("title", "")) or "WoW AI")
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
            x, y = 80, 80
            try:
                from . import overlay
                g = overlay.game_rect()
                if g:
                    x, y = g[2] - 560 - 30, g[1] + 80
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

    root.bind("<Destroy>", lambda e: cleanup() if e.widget is root else None)
    tick()
    root.mainloop()


def open_empty() -> None:
    """/ol: open the panel (shows the last content, or a short hint when the AI has not shown anything yet)."""
    if alive():
        return
    if not FILE.exists():
        show("WoW AI", ["This is the overlay window.", "The AI shows lists, builds and plans here.",
                        "Ask it, for example: show me a leveling plan."])
    else:
        show_existing()


def show_existing() -> None:
    exe = Path(sys.executable).with_name("pythonw.exe")
    subprocess.Popen([str(exe if exe.exists() else sys.executable), "-m", "wowclaude", "panel"], creationflags=0x08000000)
