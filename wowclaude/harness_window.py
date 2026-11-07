"""Harness editor: its own small window over the game (not the browser, so a page you have open there stays).

Opens from the game menu (Harness, Edit harness text). The text is what the AI is told before every question.
Save writes ~/.wowclaude/harness.txt; a text equal to the built-in one (or empty) means "use the built-in".
"""
from __future__ import annotations

from . import backends, claude, config, harness_import


def save(text: str) -> str:
    text = text.strip()
    if not text or text == claude.builtin_harness().strip():
        config.HARNESS.unlink(missing_ok=True)
        return "Using the built-in harness."
    config.HOME.mkdir(parents=True, exist_ok=True)
    config.HARNESS.write_text(text + "\n", encoding="utf-8")
    return "Saved. Used from the next question on."


def run(tab: str = "wow") -> None:
    import tkinter as tk
    from .wowframe import FramedWindow, WowScrollbar
    win = FramedWindow("Harness", 760, 560, key="harness")
    root = win.root
    gold = "#ffd100"
    tabs = tk.Frame(win.inner, bg="#15130e")
    tabs.pack(fill="x", padx=4, pady=(4, 0))
    box = tk.Frame(win.inner, bg="#15130e")
    own = tk.Frame(win.inner, bg="#15130e")
    text = tk.Text(box, bg="#15130e", fg="#f0e6c8", insertbackground=gold, font=("Consolas", 10), wrap="word", bd=1,
                   relief="solid", undo=True)
    bar = WowScrollbar(box, text.yview)
    text.configure(yscrollcommand=bar.set)
    bar.pack(side="right", fill="y")
    text.pack(side="left", fill="both", expand=True)
    text.bind("<Button-1>", lambda e: (win.focus(), text.focus_set()))
    tk.Label(own, text="Which AI answers (WoW chat and CLI):", bg="#15130e", fg=gold, anchor="w").pack(side="top", fill="x")
    choice = tk.Frame(own, bg="#15130e")
    choice.pack(side="top", fill="x", pady=(0, 6))
    pick_var = tk.StringVar(value=str(config.load().get("backend") or ""))
    dir_var = tk.StringVar(value=str(config.load().get("own_config_dir") or ""))
    dirs = tk.Frame(own, bg="#15130e")
    mrow = tk.Frame(own, bg="#15130e")
    model_var = tk.StringVar()
    tk.Label(mrow, text="Model for the WoW chat (empty = the AI's own default; a small one is enough):", bg="#15130e",
             fg=gold).pack(side="left")
    tk.Entry(mrow, textvariable=model_var, width=22, bg="#1d1a12", fg="#f0e6c8", insertbackground=gold, relief="solid",
             bd=1).pack(side="left", padx=6)
    tk.Button(mrow, text="Set", command=lambda: set_model(), bg="#5c1a10", fg=gold, activebackground="#7d2417", activeforeground=gold,
              relief="solid", bd=1, padx=10).pack(side="left")
    info = tk.Text(own, bg="#15130e", fg="#f0e6c8", font=("Consolas", 10), wrap="word", bd=1, relief="solid")
    ibar = WowScrollbar(own, info.yview)
    info.configure(yscrollcommand=ibar.set)
    ibar.pack(side="right", fill="y")
    info.pack(side="left", fill="both", expand=True)
    shown = {"tab": "wow"}

    def show(tab: str) -> None:
        shown["tab"] = tab
        box.pack_forget()
        own.pack_forget()
        (box if tab == "wow" else own).pack(fill="both", expand=True, padx=4, pady=(2, 2))
        for name, b in tab_buttons.items():
            b.config(fg=gold if name == tab else "#8a8470")
        rebuild_row()

    tab_buttons = {n: tk.Button(tabs, text=t, command=lambda n=n: show(n), bg="#2a2418", activebackground="#3a3222",
                                relief="solid", bd=1, padx=14) for n, t in (("wow", "WoW AI"), ("own", "Own AI"))}
    for b in tab_buttons.values():
        b.pack(side="left", padx=(0, 4))
    msg = tk.Label(win.inner, text="", bg="#15130e", fg="#7fd17f", anchor="w")
    row = tk.Frame(win.inner, bg="#15130e")
    row.pack(fill="x", padx=6, pady=(2, 4), side="bottom")

    def load(custom_ok: bool = True) -> None:
        text.delete("1.0", "end")
        text.insert("1.0", (claude.custom_harness() if custom_ok else None) or claude.builtin_harness())

    def do_save() -> None:
        msg.config(text=save(text.get("1.0", "end")))

    def do_reset() -> None:
        config.HARNESS.unlink(missing_ok=True)
        load(False)
        msg.config(text="Back to the built-in harness.")

    found = harness_import.sources()

    def pick() -> None:
        from tkinter import filedialog
        folder = filedialog.askdirectory(title="Folder of your AI setup (e.g. .claude, .codex)", parent=root)
        if not folder:
            return
        src = harness_import.from_folder(folder)
        if not src.found():
            msg.config(text="Nothing usable in that folder (looked for CLAUDE.md / AGENTS.md, MEMORY.md, skills).", fg="#e0a060")
            return
        if src not in found:
            found.append(src)
        refresh()
        show("own")

    def do_search() -> None:
        found[:] = harness_import.search([s.memory_dir or s.instructions_file.parent for s in found if s.kind == "folder"])
        refresh()
        msg.config(text=f"Search done: {len(found)} setup(s) found.", fg="#7fd17f")

    def choose() -> None:
        cfg = config.load()
        cfg["backend"] = pick_var.get()
        config.save(cfg)
        refresh()
        msg.config(text=f"AI: {pick_var.get()}. Used from the next question on.", fg="#7fd17f")

    def set_model() -> None:
        cfg = config.load()
        models = dict(cfg.get("models") or {})
        value = model_var.get().strip()
        if value:
            models[cfg.get("backend") or ""] = value
        else:
            models.pop(cfg.get("backend") or "", None)
        cfg["models"] = models
        config.save(cfg)
        refresh()
        msg.config(text="Model: " + (value or "the AI's own default") + ". Used from the next question on.", fg="#7fd17f")

    def choose_dir() -> None:
        cfg = config.load()
        if dir_var.get():
            cfg["own_config_dir"] = dir_var.get()
        else:
            cfg.pop("own_config_dir", None)
        config.save(cfg)
        msg.config(text="Claude folder: " + (dir_var.get() or "default") + ". Used from the next question on.", fg="#7fd17f")

    def refresh() -> None:
        for w in dirs.winfo_children():
            w.destroy()
        claude_dirs = [s for s in found if s.kind == "claude" or s.label.startswith("Claude Code")]
        if len(claude_dirs) > 1:
            tk.Label(dirs, text="Which Claude folder (several found):", bg="#15130e", fg=gold, anchor="w").pack(side="top", fill="x")
            for s in claude_dirs:
                tk.Radiobutton(dirs, text=f"{s.label}  -  {s.folder}", value=str(s.folder), variable=dir_var, command=choose_dir,
                               anchor="w", bg="#15130e", fg="#f0e6c8", selectcolor="#3a2a10", activebackground="#15130e",
                               activeforeground=gold).pack(side="top", fill="x")
            dirs.pack(side="top", fill="x", pady=(0, 6), after=choice)
        else:
            dirs.pack_forget()
        for w in choice.winfo_children():
            w.destroy()
        for b in backends.detect():
            on = b["backend"] == pick_var.get()
            line = tk.Frame(choice, bg="#15130e")
            line.pack(side="top", fill="x", pady=1)
            tk.Button(line, text="Loaded" if on else "Load", width=8, state="disabled" if on else "normal",
                      command=lambda v=b["backend"]: (pick_var.set(v), choose()), bg="#5c1a10", fg=gold, activebackground="#7d2417",
                      activeforeground=gold, disabledforeground="#7fd17f", relief="solid", bd=1).pack(side="left", padx=(0, 8))
            tk.Label(line, text=b["label"], bg="#15130e", fg=gold if on else "#f0e6c8", anchor="w").pack(side="left", fill="x")
        info.config(state="normal")
        info.delete("1.0", "end")
        cfg = config.load()
        active = cfg.get("backend")
        if not active:
            body = "Nothing loaded yet. Click Load next to the AI you want (or Search first)."
        else:
            label = next((x["label"] for x in backends.detect() if x["backend"] == active), active)
            body = f"LOADED: {label}\nModel: {harness_import.model_of(active, cfg)}\n"
            src = next((s for s in found if s.kind == active), None)
            if src:
                body += ("Live access: this AI runs with its own folder, login, memory and skills - nothing is copied.\n"
                         "Set the switch in the Harness menu to Own to talk to it in the game.\n\n" + harness_import.overview(src))
            else:
                text = harness_import.api_system(cfg) if active not in ("codex", "command") else ""
                if text:  # an API model has no folder of its own: Own mode sends the player's instructions as text
                    body += (f"Own mode sends your instructions, memory index and skill list as text with every question ({len(text) // 1000 + 1} KB).\n"
                             "The memory files and skills themselves are not copied.\n")
                else:
                    body += "No folder with instructions, memory or skills found - it answers as the bare model.\n"
                body += "Model, API address and keys: AI Setup (game menu)."
        if active:
            modes = {k: ("Own" if cfg.get("own_harness_" + k) else "WoW AI") for k in ("wow", "cli", "win")}
            body += f"\n\nHarness now:  WoW chat = {modes['wow']}   |   CLI chat = {modes['cli']}   |   CLI window = {modes['win']}"
        if active:
            model_var.set((cfg.get("models") or {}).get(active) or cfg.get("model") or "")
            mrow.pack(side="top", fill="x", pady=(0, 4), before=info)
        else:
            mrow.pack_forget()
        info.insert("1.0", body)
        info.config(state="disabled")
        rebuild_row()

    def rebuild_row() -> None:
        for w in row.winfo_children():
            w.destroy()
        if shown["tab"] == "wow":
            buttons = [("Save", do_save), ("Reset to built-in", do_reset), ("Close", win.close)]
        else:
            buttons = [("Search", do_search), ("Pick folder...", pick), ("Close", win.close)]
        for label, cmd in buttons:
            tk.Button(row, text=label, command=cmd, bg="#5c1a10", fg=gold, activebackground="#7d2417", activeforeground=gold,
                      relief="solid", bd=1, padx=12).pack(side="left", padx=(0, 8))

    refresh()
    msg.pack(fill="x", padx=6, side="bottom")
    load()
    show(tab)
    root.mainloop()
