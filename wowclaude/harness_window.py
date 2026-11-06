"""Harness editor: its own small window over the game (not the browser, so a page you have open there stays).

Opens from the game menu (Harness, Edit harness text). The text is what the AI is told before every question.
Save writes ~/.wowclaude/harness.txt; a text equal to the built-in one (or empty) means "use the built-in".
"""
from __future__ import annotations

from . import claude, config, harness_import


def save(text: str) -> str:
    text = text.strip()
    if not text or text == claude.builtin_harness().strip():
        config.HARNESS.unlink(missing_ok=True)
        return "Using the built-in harness."
    config.HOME.mkdir(parents=True, exist_ok=True)
    config.HARNESS.write_text(text + "\n", encoding="utf-8")
    return "Saved. Used from the next question on."


def run() -> None:
    import tkinter as tk
    from .wowframe import FramedWindow, WowScrollbar
    win = FramedWindow("Harness", 760, 560, key="harness")
    root = win.root
    gold = "#ffd100"
    box = tk.Frame(win.inner, bg="#15130e")
    box.pack(fill="both", expand=True, padx=4, pady=(4, 2))
    text = tk.Text(box, bg="#15130e", fg="#f0e6c8", insertbackground=gold, font=("Consolas", 10), wrap="word", bd=1,
                   relief="solid", undo=True)
    bar = WowScrollbar(box, text.yview)
    text.configure(yscrollcommand=bar.set)
    bar.pack(side="right", fill="y")
    text.pack(side="left", fill="both", expand=True)
    text.bind("<Button-1>", lambda e: (win.focus(), text.focus_set()))
    msg = tk.Label(win.inner, text="", bg="#15130e", fg="#7fd17f", anchor="w")
    row = tk.Frame(win.inner, bg="#15130e")
    row.pack(fill="x", padx=6, pady=(2, 4), side="bottom")

    def load(custom_ok: bool = True) -> None:
        text.delete("1.0", "end")
        text.insert("1.0", (claude.custom_harness() if custom_ok else None) or claude.builtin_harness())

    def do_save() -> None:
        msg.config(text=save(text.get("1.0", "end")))

    def do_import(src) -> None:
        text.delete("1.0", "end")
        text.insert("1.0", harness_import.render(src, claude.builtin_harness()))
        msg.config(text="Imported - " + harness_import.summary(src) + ". Click Save to use it.")

    def do_reset() -> None:
        config.HARNESS.unlink(missing_ok=True)
        load(False)
        msg.config(text="Back to the built-in harness.")

    buttons = [("Save", do_save)]
    found = harness_import.sources()
    buttons += [(f"Import {s.label}", (lambda s=s: do_import(s))) for s in found]
    if not found:
        buttons.append(("Import (nothing found)", lambda: msg.config(text="No Claude Code or Codex setup found in the normal folders.")))
    buttons += [("Reset to built-in", do_reset), ("Close", win.close)]
    for label, cmd in buttons:
        tk.Button(row, text=label, command=cmd, bg="#5c1a10", fg=gold, activebackground="#7d2417", activeforeground=gold,
                  relief="solid", bd=1, padx=12).pack(side="left", padx=(0, 8))
    msg.pack(fill="x", padx=6, side="bottom")
    load()
    root.mainloop()
