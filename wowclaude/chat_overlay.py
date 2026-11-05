"""A fake chat window over the game: it looks like the WoW chat tab and talks to the AI directly.

No addon, no reply slots, no reload: the window is an always-on-top Tk window that follows the game window (like the
browser overlay). What you type goes straight to the AI, the answer is printed in the window. Hotkey Ctrl+Shift+Space
puts the cursor into the input line from inside the game, Esc or Enter gives the keyboard back to the game.

``WOWCLAUDE_CHAT_ASK=module:function`` replaces the AI call (the function gets the question, returns the answer).
"""
from __future__ import annotations

import ctypes
import importlib
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from ctypes import wintypes

from . import claude, config, overlay
from .winproc import hidden

STATE = config.HOME / "chat.json"
HISTORY = config.HOME / "chat_history.json"
FOCUS_FLAG = config.HOME / "chat.focus"
PID_FILE = config.HOME / "chat.pid"
MIN_W, MIN_H = 280, 150
DEFAULT_REL = [0.012, 0.60, 0.30, 0.30]  # fractions of the game window: lower left, where the real chat sits
HOTKEY = (0x0002 | 0x0004, 0x20)  # Ctrl+Shift+Space (MOD_CONTROL | MOD_SHIFT, VK_SPACE)
COLOR = {"user": "#ffff99", "ai": "#99d9ff", "sys": "#9a9a9a", "bad": "#ff6b6b", "think": "#7f7f7f"}

_CODES = re.compile(r"\|c[0-9a-fA-F]{8}|\|r")


# ---- pure helpers (tested without a window) -------------------------------------------------------------------

def render_answer(name: str, text: str) -> tuple[list[str], str | None]:
    """The AI's raw reply -> lines for the window, and an optional https page to open ([[play URL]])."""
    text, macros = claude.extract_macros(text)
    text, ov = claude.extract_overlay(text)
    text, play = claude.extract_play(text)
    lines = [f"{name}: {' '.join(text.split())}"] if text.strip() else []
    if ov:
        lines += ["   " + _CODES.sub("", ln) for ln in [ov["title"]] + list(ov["lines"])]
    for m in macros:
        lines.append(f"   Macro {m['name']}: " + _CODES.sub("", m["body"]).replace("\n", " / "))
    return lines or [f"{name}: ..."], play


def default_ask(question: str) -> str:
    spec = os.environ.get("WOWCLAUDE_CHAT_ASK", "")
    if ":" in spec:
        mod, _, fn = spec.partition(":")
        return str(getattr(importlib.import_module(mod), fn)(question))
    if not hasattr(default_ask, "session"):
        default_ask.session = claude.Session()  # type: ignore[attr-defined]
    return default_ask.session.ask(question)  # type: ignore[attr-defined]


def alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = wintypes.DWORD()
        ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h)
        return code.value == 259  # STILL_ACTIVE
    except (OSError, AttributeError):
        return False


def start() -> str:
    """Open the chat window in its own process, or put the cursor into the running one. Returns a short status."""
    config.HOME.mkdir(parents=True, exist_ok=True)
    try:
        pid = int(PID_FILE.read_text().strip())
    except (OSError, ValueError):
        pid = 0
    if alive(pid):
        FOCUS_FLAG.write_text("1")
        return "Chat window is already open (Ctrl+Shift+Space types into it)."
    log = open(config.HOME / "chat.log", "a", encoding="utf-8")
    subprocess.Popen([sys.executable, "-m", "wowclaude", "chat"], stdout=log, stderr=log, **hidden())
    return "Chat window opened (Ctrl+Shift+Space types into it)."


# ---- the window -----------------------------------------------------------------------------------------------

def _load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def run(ask=None) -> int:
    if os.name != "nt":
        print("The chat window is Windows only.")
        return 2
    import tkinter as tk

    ask = ask or default_ask
    config.HOME.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))
    name = claude.persona()[0]
    saved = _load(STATE, {})
    rel = saved.get("rel") or DEFAULT_REL
    S = {"g": None, "x": 0, "y": 0, "w": 400, "h": 220, "rel": rel}
    user32 = ctypes.windll.user32
    events: queue.Queue = queue.Queue()

    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.86)
    root.configure(bg="#0b0a08")
    outer = tk.Frame(root, bg="#0b0a08", highlightthickness=1, highlightbackground="#5c4a1a")
    outer.pack(fill="both", expand=True)

    head = tk.Frame(outer, bg="#2a2417", height=18)
    head.pack(fill="x")
    title = tk.Label(head, text=name, bg="#2a2417", fg="#ffd100", font=("Arial", 9, "bold"), anchor="w")
    title.pack(side="left", padx=6)
    close = tk.Label(head, text="X", bg="#701610", fg="#f2c230", font=("Arial", 8, "bold"), width=3, cursor="hand2")
    close.pack(side="right", padx=2, pady=1)

    log = tk.Text(outer, bg="#0b0a08", fg=COLOR["ai"], font=("Arial", 11), wrap="word", relief="flat", bd=0,
                  highlightthickness=0, padx=6, pady=4, state="disabled", cursor="arrow", takefocus=0)
    for tag, col in COLOR.items():
        log.tag_configure(tag, foreground=col)
    foot = tk.Frame(outer, bg="#0b0a08")
    foot.pack(side="bottom", fill="x")
    prompt = tk.Label(foot, text=name + ":", bg="#0b0a08", fg=COLOR["ai"], font=("Arial", 11))
    prompt.pack(side="left", padx=(6, 2))
    var = tk.StringVar()
    entry = tk.Entry(foot, textvariable=var, bg="#15130e", fg="#ffffff", insertbackground="#ffd100", relief="flat",
                     font=("Arial", 11), highlightthickness=1, highlightbackground="#3c3a35", highlightcolor="#b4b4b4")
    entry.pack(side="left", fill="x", expand=True, padx=(0, 4), pady=4)
    grip = tk.Label(foot, text="◢", bg="#0b0a08", fg="#7d6a2a", font=("Arial", 10), cursor="size_nw_se")
    grip.pack(side="right", padx=(0, 2))
    log.pack(fill="both", expand=True)

    def add(text: str, tag: str = "ai") -> None:
        log.configure(state="normal")
        log.insert("end", text + "\n", tag)
        log.configure(state="disabled")
        log.see("end")

    def remember() -> None:
        lines = [ln for ln in log.get("1.0", "end").splitlines() if ln.strip() and not ln.startswith("...")]
        try:
            HISTORY.write_text(json.dumps(lines[-100:]), encoding="utf-8")
        except OSError:
            pass

    for ln in _load(HISTORY, [])[-40:]:
        add(ln, "user" if ln.startswith(("Du: ", "You: ")) else "ai")
    add(f"{name}: " + ("Hi! Click here or press Ctrl+Shift+Space and write."), "sys")

    # ---- placement: follows the game window like the browser overlay ----
    def geometry() -> None:
        g = overlay.game_rect()
        if g is None:
            return
        x, y, w, h = overlay.from_rel(g, S["rel"])
        w, h = max(MIN_W, w), max(MIN_H, h)
        S.update(g=g, x=x, y=y, w=w, h=h)
        root.geometry(f"{w}x{h}+{x}+{y}")

    def save_rel() -> None:
        g = overlay.game_rect()
        if g:
            S["rel"] = overlay.to_rel(g, root.winfo_x(), root.winfo_y(), root.winfo_width(), root.winfo_height())
            try:
                STATE.write_text(json.dumps({"rel": S["rel"]}), encoding="utf-8")
            except OSError:
                pass

    # ---- keyboard: hand it to the chat / back to the game ----
    def focus_chat(_e=None) -> None:
        root.deiconify()
        root.lift()
        root.focus_force()
        entry.focus_force()
        entry.icursor("end")

    def to_game(_e=None) -> None:
        hw = overlay._game_hwnd()
        if hw:
            user32.SetForegroundWindow(wintypes.HWND(hw))

    def hotkey_thread() -> None:
        if not user32.RegisterHotKey(None, 1, HOTKEY[0], HOTKEY[1]):
            return  # taken by another program: the click still works
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == 0x0312:  # WM_HOTKEY
                events.put(("focus", None))
    threading.Thread(target=hotkey_thread, daemon=True).start()

    # ---- asking ----
    def worker(question: str) -> None:
        try:
            events.put(("answer", ask(question)))
        except Exception as exc:  # noqa: BLE001 - shown in the window, the window keeps running
            events.put(("error", str(exc)[:200]))

    busy = {"on": False}

    def send(_e=None):
        text = var.get().strip()
        if not text:
            to_game()
            return "break"
        if busy["on"]:
            add(f"{name}: " + "(still answering, one moment)", "sys")
            return "break"
        var.set("")
        add("Du: " + text, "user")
        add("...", "think")
        busy["on"] = True
        threading.Thread(target=worker, args=(text,), daemon=True).start()
        to_game()
        return "break"

    def finish() -> None:
        busy["on"] = False
        log.configure(state="normal")
        idx = log.search("...\n", "end", backwards=True, stopindex="1.0")
        if idx:
            log.delete(idx, f"{idx} +4c")
        log.configure(state="disabled")

    def pump() -> None:
        try:
            while True:
                kind, payload = events.get_nowait()
                if kind == "focus":
                    focus_chat()
                elif kind == "answer":
                    finish()
                    lines, play = render_answer(name, payload)
                    for ln in lines:
                        add(ln, "ai")
                    if play:
                        try:
                            overlay.play(play)
                        except Exception as exc:  # noqa: BLE001
                            add(f"({exc})", "bad")
                    remember()
                elif kind == "error":
                    finish()
                    add(f"{name}: {payload}", "bad")
        except queue.Empty:
            pass
        if FOCUS_FLAG.exists():
            try:
                FOCUS_FLAG.unlink()
            except OSError:
                pass
            focus_chat()
        root.after(120, pump)

    # ---- dragging, resizing, closing ----
    drag: dict = {}
    head.bind("<Button-1>", lambda e: drag.update(mode="move", x=e.x_root - root.winfo_x(), y=e.y_root - root.winfo_y()))
    title.bind("<Button-1>", lambda e: drag.update(mode="move", x=e.x_root - root.winfo_x(), y=e.y_root - root.winfo_y()))
    grip.bind("<Button-1>", lambda e: drag.update(mode="size", x=e.x_root, y=e.y_root, w=root.winfo_width(), h=root.winfo_height()))

    def motion(e) -> None:
        if drag.get("mode") == "move":
            root.geometry(f"+{e.x_root - drag['x']}+{e.y_root - drag['y']}")
        elif drag.get("mode") == "size":
            root.geometry(f"{max(MIN_W, drag['w'] + e.x_root - drag['x'])}x{max(MIN_H, drag['h'] + e.y_root - drag['y'])}")

    def release(_e) -> None:
        if drag.get("mode"):
            drag.clear()
            save_rel()
            S["g"] = overlay.game_rect()

    for w_ in (head, title, grip):
        w_.bind("<B1-Motion>", motion)
        w_.bind("<ButtonRelease-1>", release)

    def quit_(_e=None) -> None:
        save_rel()
        remember()
        root.destroy()

    close.bind("<Button-1>", quit_)
    entry.bind("<Return>", send)
    entry.bind("<Escape>", lambda e: (to_game(), "break")[1])
    log.bind("<Button-1>", lambda e: focus_chat())

    # ---- keep it in place ----
    def tick() -> None:
        try:
            g = overlay.game_rect()
            if g is None:  # game minimized or closed
                root.withdraw()
            else:
                if root.state() == "withdrawn":
                    root.deiconify()
                if g != S["g"] and not drag:
                    geometry()
                root.attributes("-topmost", True)
        except tk.TclError:
            return
        except Exception as exc:  # noqa: BLE001
            print(f"tick error: {exc!r}", flush=True)
        root.after(300, tick)

    geometry()
    tick()
    pump()
    print("Chat window running.", flush=True)
    try:
        root.mainloop()
    finally:
        try:
            PID_FILE.unlink()
        except OSError:
            pass
    return 0
