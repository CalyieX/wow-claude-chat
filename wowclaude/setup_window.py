"""AI setup as a framed window over the game (same look as the Harness editor), not a browser page.

Uses the logic of setup_ui (_state / apply / _check), so both always write the same config.json.
"""
from __future__ import annotations

import os
import shutil
import threading
from pathlib import Path

from . import backends, claude, config, setup_ui

EXTRA_PORTS = ((8080, "llama.cpp server"), (1337, "Jan"), (4891, "GPT4All"), (5000, "local OpenAI-style server"),
               (8000, "local OpenAI-style server (vLLM etc.)"), (11435, "local OpenAI-style server"))


def _speaks_openai(port: int) -> bool:
    """An open port is not enough (it may be any other server): it must answer the OpenAI-style model list."""
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/models", timeout=2) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def deep_search() -> list[dict]:
    """detect() plus a broader scan: programs that are installed but not on PATH, and more local server ports.
    Each entry: {backend, label, base_url?, command?}."""
    found = list(backends.detect())
    have = {f["backend"] for f in found}
    home = Path.home()
    appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
    if "claude" not in have and claude.claude_path():
        found.append({"backend": "claude", "label": "Claude Code (" + str(claude.claude_path()) + ")"})
    if "codex" not in have:
        for c in (appdata / "npm" / "codex.cmd", local / "Programs" / "codex" / "codex.exe", home / ".local" / "bin" / "codex",
                  home / ".local" / "bin" / "codex.exe", Path("/usr/local/bin/codex")):
            if c.exists():
                found.append({"backend": "codex", "label": f"Codex ({c})", "codex_path": str(c)})
                break
    for port, label in EXTRA_PORTS:
        if backends._port_open(port) and _speaks_openai(port):
            found.append({"backend": "openai-compatible", "label": f"{label} (port {port})", "base_url": f"http://127.0.0.1:{port}/v1"})
    for exe, label in (("gemini", "Gemini CLI"), ("aider", "Aider"), ("ollama", "Ollama (installed, not running: start it)")):
        if shutil.which(exe) and not (exe == "ollama" and "ollama" in have):
            found.append({"backend": "command", "label": label + " (command)", "command": exe if exe != "ollama" else "ollama run llama3.1"})
    return found


def current_ai() -> str:
    """The AI that is loaded right now, as one line (empty when none was chosen yet or it was unloaded)."""
    from . import harness_import
    cfg = config.load()
    backend = cfg.get("backend")
    if not backend or cfg.get("ai_off"):
        return ""
    return f"{backend}, model {harness_import.model_of(backend, cfg)}"


def describe_last(rec: dict, now: float) -> str:
    """The last real answer of the AI, as one line for the live panel."""
    if not rec:
        return "Last answer: none yet (press Test now, or ask something in the game)."
    ago = max(0, int(now - float(rec.get("t", now))))
    when = f"{ago} s ago" if ago < 120 else f"{ago // 60} min ago"
    who = f"{rec.get('backend', '?')}, {rec.get('model', '?')}"
    if rec.get("ok"):
        return f"Last answer: {when}, ok, {rec.get('seconds', 0)} s ({who})"
    return f"Last answer: {when}, FAILED ({who}): {rec.get('error', '')}"


def run() -> None:
    import tkinter as tk
    from .wowframe import FramedWindow, WowScrollbar
    win = FramedWindow("AI setup", 760, 680, key="aisetup")
    gold, bg, fg = "#ffd100", "#15130e", "#f0e6c8"
    st = setup_ui._state()
    found: list[dict] = []  # starts empty like on a fresh PC: the Search button fills it

    def btn(parent, text, cmd, **kw):
        b = tk.Button(parent, text=text, command=cmd, bg="#5c1a10", fg=gold, activebackground="#7d2417", activeforeground=gold,
                      relief="solid", bd=1, padx=10, **kw)
        return b

    def lab(parent, text, color=gold):
        return tk.Label(parent, text=text, bg=bg, fg=color, anchor="w", justify="left", wraplength=700)

    def entry(parent, var, show=""):
        e = tk.Entry(parent, textvariable=var, show=show, bg="#1d1a12", fg=fg, insertbackground=gold, relief="solid", bd=1)
        e.bind("<Button-1>", lambda ev: (win.focus(), e.focus_set()))
        return e

    msg = tk.Label(win.inner, text="", bg=bg, fg="#7fd17f", anchor="w", wraplength=720, justify="left")
    msg.pack(side="bottom", fill="x", padx=8)
    bottom = tk.Frame(win.inner, bg=bg)
    bottom.pack(side="bottom", fill="x", padx=6, pady=(2, 4))
    outer = tk.Frame(win.inner, bg=bg)
    outer.pack(side="top", fill="both", expand=True, padx=8, pady=6)

    live = tk.Frame(outer, bg=bg)
    live.pack(fill="x")
    now_lab = tk.Label(live, text="", bg=bg, fg=gold, anchor="w", justify="left", wraplength=560)
    now_lab.pack(side="left", fill="x", expand=True)
    last_lab = tk.Label(outer, text="", bg=bg, fg="#b9b093", anchor="w", justify="left", wraplength=700)
    last_lab.pack(fill="x", pady=(0, 6))
    lab(outer, "Found on this PC (press Search) - click one to load it:").pack(fill="x")
    foundf = tk.Frame(outer, bg=bg)
    foundf.pack(fill="x", pady=(0, 6))
    backend_var = tk.StringVar(value=st["backend_set"])  # empty until an AI was really chosen: no default dressed up as a choice
    model_var = tk.StringVar(value=st["model"] or "")
    base_var = tk.StringVar(value=st["base_url"] or "")
    key_var = tk.StringVar()
    tok_var = tk.StringVar()
    cmd_var = tk.StringVar(value=st["command"] or "")
    access_var = tk.BooleanVar(value=bool(st["computer_access"]))
    input_var = tk.BooleanVar(value=bool(st["input_control"]))

    def use_found(f: dict) -> None:
        backend_var.set(f["backend"])
        if f.get("base_url"):
            base_var.set(f["base_url"])
        if f.get("command"):
            cmd_var.set(f["command"])
        save()

    def draw_found() -> None:
        for w in foundf.winfo_children():
            w.destroy()
        if not found:
            lab(foundf, "Press Search to look for the AIs on this PC (or enter an API key below).", "#b9b093").pack(fill="x")
        for i, f in enumerate(found):
            b = btn(foundf, ("* " if i == 0 else "") + f["label"], lambda f=f: use_found(f))
            b.pack(fill="x", pady=2)

    def do_search() -> None:
        msg.config(text="Searching this PC for AIs ...", fg=gold)

        def work() -> None:
            got = deep_search()
            try:
                win.root.after(0, lambda: done(got))
            except Exception:  # noqa: BLE001 - window closed
                pass
        threading.Thread(target=work, daemon=True).start()

    def done(got: list[dict]) -> None:
        found[:] = got
        draw_found()
        draw_others()
        msg.config(text=f"Search done: {len(got)} AI(s) found.", fg="#7fd17f")

    lab(outer, "Other AIs (you need an account or key there):").pack(fill="x")
    others = tk.Frame(outer, bg=bg)
    others.pack(fill="x", pady=(0, 6))
    def draw_others() -> None:  # the providers that were not found on this PC (they need an account or key)
        for w in others.winfo_children():
            w.destroy()
        have = {f["backend"] for f in found}
        for i, b in enumerate(x for x in st["backends"] if x != "command" and x not in have):
            tk.Button(others, text=b, command=lambda b=b: (backend_var.set(b), key_e.focus_set()), bg="#2a2418", fg=gold,
                      activebackground="#5c1a10", activeforeground=gold, relief="solid", bd=1, padx=6).grid(row=i // 6, column=i % 6, padx=2, pady=2, sticky="w")
    draw_others()

    grid = tk.Frame(outer, bg=bg)
    grid.pack(fill="x")
    rows = (("AI (backend)", backend_var, ""), ("Model (empty = default)", model_var, ""), ("API address (OpenAI-compatible)", base_var, ""),
            ("API key" + (" (saved)" if st["has_key"] else ""), key_var, "*"),
            ("Year login token" + (" (saved)" if st["has_token"] else ""), tok_var, "*"), ("Command (reads the prompt on stdin)", cmd_var, ""))
    key_e = None
    for i, (t, var, sh) in enumerate(rows):
        lab(grid, t).grid(row=i, column=0, sticky="w", pady=2)
        e = entry(grid, var, sh)
        e.grid(row=i, column=1, sticky="ew", padx=6, pady=2)
        if t.startswith("API key"):
            key_e = e
    grid.columnconfigure(1, weight=1)
    lab(outer, "Extra instructions (optional, e.g. how it should talk):").pack(fill="x", pady=(6, 0))
    pbox = tk.Frame(outer, bg=bg)
    pbox.pack(fill="x")
    pbox.pack_propagate(False)
    pbox.configure(height=64)
    persona = tk.Text(pbox, bg=bg, fg=fg, insertbackground=gold, font=("Consolas", 10), wrap="word", bd=1, relief="solid", height=3)
    pbar = WowScrollbar(pbox, persona.yview)
    persona.configure(yscrollcommand=pbar.set)
    pbar.pack(side="right", fill="y")
    persona.pack(side="left", fill="both", expand=True)
    persona.insert("1.0", st["persona"] or "")
    persona.bind("<Button-1>", lambda e: (win.focus(), persona.focus_set()))
    persona.bind("<Tab>", lambda e: (persona.tk_focusNext().focus_set(), "break")[1])  # Tab leaves the text box (keyboard and automation users would be stuck otherwise)
    persona.bind("<Shift-Tab>", lambda e: (persona.tk_focusPrev().focus_set(), "break")[1])
    for var, text in ((access_var, "Let the AI use this computer (files, commands; Claude Code / Codex only)"),
                      (input_var, "Allow the AI to use mouse and keyboard in the game")):
        tk.Checkbutton(outer, text=text, variable=var, bg=bg, fg=fg, selectcolor="#2a2418", activebackground=bg, activeforeground=gold,
                       anchor="w").pack(fill="x")

    def save() -> None:
        msg.config(text="Saving ...", fg=gold)
        data = {"backend": backend_var.get(), "model": model_var.get(), "base_url": base_var.get(), "api_key": key_var.get(),
                "claude_token": tok_var.get(), "command": cmd_var.get(), "persona": persona.get("1.0", "end"),
                "input_control": input_var.get(), "computer_access": access_var.get()}
        r = setup_ui.apply(data)
        key_var.set("")
        tok_var.set("")
        msg.config(text=r["status"] + "  Checking the AI ...", fg="#7fd17f" if r["ok"] else "#ff8a80")

        def work() -> None:
            c = setup_ui._check()
            def show() -> None:
                msg.config(text=c["status"], fg="#7fd17f" if c["ok"] else "#ff8a80")
                draw_found()
                if c["ok"]:
                    load_btn.pack_forget()
                elif not load_btn.winfo_ismapped():  # the AI did not load: offer to try again without restarting anything
                    load_btn.pack(side="left", padx=(0, 8), before=close_btn)
            try:
                win.root.after(0, show)
            except Exception:  # noqa: BLE001
                pass
        threading.Thread(target=work, daemon=True).start()

    def copy_prompt() -> None:
        win.root.clipboard_clear()
        win.root.clipboard_append(setup_ui.ai_prompt())
        msg.config(text="Copied: paste it into an AI that can edit files (Claude Code, Codex ...) and it sets this up for you.", fg="#7fd17f")

    for label, cmd in (("Save and test", save), ("Search", do_search), ("Let my own AI set this up (copy text)", copy_prompt)):
        btn(bottom, label, cmd).pack(side="left", padx=(0, 8))
    close_btn = btn(bottom, "Close", win.close)
    close_btn.pack(side="left", padx=(0, 8))
    load_btn = btn(bottom, "Load AI again", save)  # only shown when the last check failed
    def refresh_live() -> None:
        """Real data, read again every 2 seconds: what is loaded and how the last answer went."""
        import time
        now = current_ai()
        if now:
            now_lab.config(text="Loaded now: " + now, fg="#7fd17f")
            if not unload_btn.winfo_ismapped():
                unload_btn.pack(side="right")
        else:
            off = setup_ui.is_off()
            now_lab.config(text=("AI is off: nothing answers until you load one." if off else "No AI loaded yet."), fg="#ff8a80" if off else gold)
            unload_btn.pack_forget()
        last_lab.config(text=describe_last(config.last_answer(), time.time()))
        try:
            win.root.after(2000, refresh_live)
        except Exception:  # noqa: BLE001 - window closed
            pass

    def do_unload() -> None:
        msg.config(text=setup_ui.unload()["status"], fg=gold)
        refresh_live()

    def test_now() -> None:
        msg.config(text="Asking the AI a real question ...", fg=gold)

        def work() -> None:
            r = setup_ui.probe()
            try:
                win.root.after(0, lambda: (msg.config(text=r["status"], fg="#7fd17f" if r["ok"] else "#ff8a80"), refresh_live()))
            except Exception:  # noqa: BLE001
                pass
        threading.Thread(target=work, daemon=True).start()

    unload_btn = btn(live, "Unload", do_unload)
    btn(bottom, "Test now", test_now).pack(side="left", padx=(0, 8), before=close_btn)
    draw_found()
    refresh_live()
    win.root.mainloop()
