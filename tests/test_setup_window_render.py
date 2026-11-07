"""The AI setup window is built for real (hidden, no flash) and every text the player would read is compared with the config.

Earlier tests only checked config.json and the keyboard flow; the window itself said "no AI loaded" while one answered,
showed 'claude' in the AI field with nothing chosen and left the model field empty next to "model sonnet".
"""
import tkinter as tk

import pytest

from wowclaude import config, setup_window, wowframe


def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HOME", tmp_path)
    monkeypatch.setattr(config, "CONFIG", tmp_path / "config.json")
    monkeypatch.setattr(config, "PERSONA", tmp_path / "persona.txt")


def _render(monkeypatch):
    """Build the window, return (labels, entry values in field order, buttons)."""
    seen = []
    orig = wowframe.FramedWindow.__init__

    def init(self, *a, **k):
        orig(self, *a, **k)
        self.root.withdraw()
        seen.append(self)

    out = {}

    def fake_mainloop(self, n=0):
        root = seen[0].root
        root.update()
        labels, entries, buttons = [], [], []

        def walk(w):
            for c in w.winfo_children():
                if isinstance(c, tk.Entry):
                    entries.append(c.get())
                elif isinstance(c, tk.Button):
                    buttons.append(c.cget("text"))
                elif isinstance(c, tk.Label):
                    labels.append(c.cget("text"))
                walk(c)
        walk(root)
        out.update(labels=labels, entries=entries, buttons=buttons)
        root.destroy()

    monkeypatch.setattr(wowframe.FramedWindow, "__init__", init)
    monkeypatch.setattr(tk.Misc, "mainloop", fake_mainloop)
    try:
        setup_window.run()
    except tk.TclError as exc:
        pytest.skip(f"no display for Tk: {exc}")
    return out["labels"], out["entries"], out["buttons"]


def test_fresh_config_shows_nothing_loaded_and_an_empty_ai_field(tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    labels, entries, _ = _render(monkeypatch)
    assert any("No AI loaded yet" in t for t in labels)
    assert not any(t.startswith("Loaded now") for t in labels)
    assert entries[0] == ""  # AI (backend): no default dressed up as a choice


def test_loaded_ai_is_named_and_the_model_field_agrees(tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    config.save({"backend": "claude", "models": {"claude": "sonnet"}})
    labels, entries, _ = _render(monkeypatch)
    assert "Loaded now: claude, model sonnet" in labels
    assert not any("No AI loaded yet" in t for t in labels)
    assert entries[0] == "claude" and entries[1] == "sonnet"  # backend and model field show what is really set


def test_saving_keeps_both_model_places_in_step(tmp_path, monkeypatch):
    from wowclaude import setup_ui
    _isolated(tmp_path, monkeypatch)
    setup_ui.apply({"backend": "openrouter", "model": "openrouter/free"})
    cfg = config.load()
    assert cfg["model"] == "openrouter/free" and cfg["models"] == {"openrouter": "openrouter/free"}
    assert config.model_for("openrouter") == "openrouter/free"
    setup_ui.apply({"backend": "openrouter", "model": ""})
    cfg = config.load()
    assert "model" not in cfg and "models" not in cfg


def test_saving_without_a_chosen_ai_says_so(tmp_path, monkeypatch):
    from wowclaude import setup_ui
    _isolated(tmp_path, monkeypatch)
    r = setup_ui.apply({"backend": ""})
    assert not r["ok"] and "Choose an AI first" in r["status"]
    assert "backend" not in config.load()
