"""Harness editor: its own small window over the game (not the browser, so a page you have open there stays).

Opens from the game menu (Harness, Edit harness text). The text is what the AI is told before every question.
Save writes ~/.wowclaude/harness.txt; a text equal to the built-in one (or empty) means "use the built-in".
"""
from __future__ import annotations

from . import claude, config


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
    root = tk.Tk()
    root.title("WoW AI - Harness")
    root.geometry("720x520+120+90")
    root.configure(bg="#15130e")
    root.attributes("-topmost", True)
    gold = "#ffd100"
    tk.Label(root, text="Harness - what your AI is told before every question", bg="#15130e", fg=gold,
             font=("Georgia", 12), anchor="w").pack(fill="x", padx=10, pady=(8, 2))
    box = tk.Frame(root, bg="#15130e")
    box.pack(fill="both", expand=True, padx=10, pady=4)
    text = tk.Text(box, bg="#0e0d09", fg="#f0e6c8", insertbackground=gold, font=("Consolas", 10), wrap="word", bd=1,
                   relief="solid", undo=True)
    bar = tk.Scrollbar(box, command=text.yview)
    text.configure(yscrollcommand=bar.set)
    bar.pack(side="right", fill="y")
    text.pack(side="left", fill="both", expand=True)
    msg = tk.Label(root, text="", bg="#15130e", fg="#7fd17f", anchor="w")
    row = tk.Frame(root, bg="#15130e")
    row.pack(fill="x", padx=10, pady=(2, 4))

    def load(custom_ok: bool = True) -> None:
        text.delete("1.0", "end")
        text.insert("1.0", (claude.custom_harness() if custom_ok else None) or claude.builtin_harness())

    def do_save() -> None:
        msg.config(text=save(text.get("1.0", "end")))

    def do_reset() -> None:
        config.HARNESS.unlink(missing_ok=True)
        load(False)
        msg.config(text="Back to the built-in harness.")

    for label, cmd in (("Save", do_save), ("Reset to built-in", do_reset), ("Close", root.destroy)):
        tk.Button(row, text=label, command=cmd, bg="#5c1a10", fg=gold, activebackground="#7d2417", activeforeground=gold,
                  relief="solid", bd=1, padx=12).pack(side="left", padx=(0, 8))
    msg.pack(fill="x", padx=10, pady=(0, 8))
    load()
    root.mainloop()
