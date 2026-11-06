"""Model popup (/model in the game chat): the models the loaded AI can use right now, read live; pick one and it is used from the
next question on."""
from __future__ import annotations

from . import backends, config, models


def choose(backend: str, model: str | None) -> None:
    """Save the model for this AI (None = the AI's own default)."""
    cfg = config.load()
    chosen = dict(cfg.get("models") or {})
    if model:
        chosen[backend] = model
    else:
        chosen.pop(backend, None)
    cfg["models"] = chosen
    config.save(cfg)


def run() -> None:
    import tkinter as tk
    from .wowframe import FramedWindow, WowScrollbar
    win = FramedWindow("Model", 640, 460, key="models")
    gold = "#ffd100"
    backend = backends.name()
    items, note = models.available(backend)
    current = config.model_for(backend)
    head = tk.Label(win.inner, text=f"AI: {backend}    current: {current or 'the AI default'}", bg="#15130e", fg=gold, anchor="w")
    head.pack(fill="x", padx=8, pady=(6, 0))
    tk.Label(win.inner, text=note, bg="#15130e", fg="#b9b093", anchor="w", wraplength=600, justify="left").pack(fill="x", padx=8)
    box = tk.Frame(win.inner, bg="#15130e")
    box.pack(fill="both", expand=True, padx=8, pady=6)
    lst = tk.Listbox(box, bg="#15130e", fg="#f0e6c8", selectbackground="#5c1a10", selectforeground=gold, font=("Consolas", 10),
                     activestyle="none", bd=1, relief="solid", exportselection=False)
    bar = WowScrollbar(box, lst.yview)
    lst.configure(yscrollcommand=bar.set)
    bar.pack(side="right", fill="y")
    lst.pack(side="left", fill="both", expand=True)
    for ident, label in items:
        lst.insert("end", ("> " if ident == current else "  ") + (f"{ident}   {label}" if label != ident else ident))
        if ident == current:
            lst.selection_set("end")
    msg = tk.Label(win.inner, text="", bg="#15130e", fg="#7fd17f", anchor="w")
    msg.pack(fill="x", padx=8, side="bottom")
    row = tk.Frame(win.inner, bg="#15130e")
    row.pack(fill="x", padx=6, pady=(2, 4), side="bottom")

    def use(_e=None) -> None:
        sel = lst.curselection()
        if not sel:
            return
        ident = items[sel[0]][0]
        choose(backend, ident)
        msg.config(text=f"Model: {ident}. Used from the next question on.")
        head.config(text=f"AI: {backend}    current: {ident}")

    def default() -> None:
        choose(backend, None)
        msg.config(text="Back to the AI's own default.")
        head.config(text=f"AI: {backend}    current: the AI default")

    lst.bind("<Double-Button-1>", use)
    for label, cmd in (("Use selected", use), ("AI default", default), ("Close", win.close)):
        tk.Button(row, text=label, command=cmd, bg="#5c1a10", fg=gold, activebackground="#7d2417", activeforeground=gold,
                  relief="solid", bd=1, padx=12).pack(side="left", padx=(0, 8))
    win.root.mainloop()
