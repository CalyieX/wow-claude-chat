"""The AI setup and harness windows are built for real (hidden, no flash) and every text the player would read is compared
with the config. Each window is built in its own process with its own home folder: Tk breaks after several windows in one
process, and a skipped test would hide exactly what these tests are for.

Earlier tests only checked config.json and the keyboard flow; the window itself said "no AI loaded" while one answered,
showed 'claude' in the AI field with nothing chosen and left the model field empty next to "model sonnet".
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

SCRIPT = r'''
import json, sys, tkinter as tk
sys.path.insert(0, sys.argv[1])
module, kwargs = sys.argv[2], json.loads(sys.argv[3])
from wowclaude import wowframe
import importlib
mod = importlib.import_module("wowclaude." + module)
seen, out = [], []
orig = wowframe.FramedWindow.__init__
def init(self, *a, **k):
    orig(self, *a, **k)
    self.root.withdraw()
    seen.append(self)
wowframe.FramedWindow.__init__ = init
def fake_mainloop(self, n=0):
    root = seen[0].root
    root.update()
    def walk(w):
        for c in w.winfo_children():
            if isinstance(c, tk.Text):
                out.append(c.get("1.0", "end").strip())
            elif isinstance(c, tk.Entry):
                out.append("[entry]" + c.get())
            else:
                try:
                    out.append(str(c.cget("text")))
                except tk.TclError:
                    pass
            walk(c)
    walk(root)
    root.destroy()
tk.Misc.mainloop = fake_mainloop
mod.run(**kwargs)
print("@@" + json.dumps(out))
'''


def _texts(tmp_path, module, config=None, files=None, **kwargs):
    """Every label, button, entry and text-box content of the window, built in a fresh process with `tmp_path` as home."""
    home = tmp_path / "home"
    (home / ".wowclaude").mkdir(parents=True)
    if config is not None:
        (home / ".wowclaude" / "config.json").write_text(json.dumps(config), encoding="utf-8")
    for rel, text in (files or {}).items():
        f = home / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    env = {k: v for k, v in __import__("os").environ.items()
           if k not in ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "OPENROUTER_API_KEY", "CEREBRAS_API_KEY", "OPENAI_API_KEY",
                        "DEEPSEEK_API_KEY", "GROQ_API_KEY", "MISTRAL_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY",
                        "XAI_API_KEY", "TOGETHER_API_KEY", "PERPLEXITY_API_KEY", "WOWCLAUDE_BACKEND")}
    env.update(USERPROFILE=str(home), HOME=str(home))
    r = subprocess.run([sys.executable, "-I", "-c", SCRIPT, str(ROOT), module, json.dumps(kwargs)], env=env,
                       capture_output=True, text=True, timeout=120)
    line = next((ln for ln in r.stdout.splitlines() if ln.startswith("@@")), None)
    if line is None:
        if "no display" in r.stderr or "couldn't connect to display" in r.stderr:
            pytest.skip("no display for Tk")
        raise AssertionError("window did not render:\n" + r.stderr[-800:])
    return json.loads(line[2:])


def test_setup_fresh_config_shows_nothing_loaded_and_an_empty_ai_field(tmp_path):
    t = _texts(tmp_path, "setup_window")
    assert any("No AI loaded yet" in x for x in t)
    assert not any(x.startswith("Loaded now") for x in t)
    assert t[t.index("AI (backend)") + 1] == "[entry]"  # no default dressed up as a choice


def test_setup_loaded_ai_is_named_and_the_model_field_agrees(tmp_path):
    t = _texts(tmp_path, "setup_window", {"backend": "claude", "models": {"claude": "sonnet"}})
    assert "Loaded now: claude, model sonnet" in t
    assert not any("No AI loaded yet" in x for x in t)
    assert t[t.index("AI (backend)") + 1] == "[entry]claude"
    assert t[t.index("Model (empty = default)") + 1] == "[entry]sonnet"


def test_saving_keeps_both_model_places_in_step(tmp_path, monkeypatch):
    from wowclaude import config, setup_ui
    monkeypatch.setattr(config, "HOME", tmp_path)
    monkeypatch.setattr(config, "CONFIG", tmp_path / "config.json")
    monkeypatch.setattr(config, "PERSONA", tmp_path / "persona.txt")
    setup_ui.apply({"backend": "openrouter", "model": "openrouter/free"})
    cfg = config.load()
    assert cfg["model"] == "openrouter/free" and cfg["models"] == {"openrouter": "openrouter/free"}
    assert config.model_for("openrouter") == "openrouter/free"
    setup_ui.apply({"backend": "openrouter", "model": ""})
    cfg = config.load()
    assert "model" not in cfg and "models" not in cfg


def test_saving_without_a_chosen_ai_says_so(tmp_path, monkeypatch):
    from wowclaude import config, setup_ui
    monkeypatch.setattr(config, "HOME", tmp_path)
    monkeypatch.setattr(config, "CONFIG", tmp_path / "config.json")
    monkeypatch.setattr(config, "PERSONA", tmp_path / "persona.txt")
    r = setup_ui.apply({"backend": ""})
    assert not r["ok"] and "Choose an AI first" in r["status"]
    assert "backend" not in config.load()


def test_harness_window_fresh_config_says_nothing_is_loaded(tmp_path):
    t = _texts(tmp_path, "harness_window", tab="own")
    assert any("Nothing loaded yet" in x for x in t)
    assert not any(x.startswith("LOADED:") for x in t)


def test_harness_window_names_loaded_ai_model_and_the_harness_switches(tmp_path):
    t = _texts(tmp_path, "harness_window", {"backend": "openrouter", "models": {"openrouter": "openrouter/free"},
                                           "own_harness_wow": True}, tab="own")
    info = next(x for x in t if x.startswith("LOADED:"))
    assert "Model: openrouter/free" in info
    assert "WoW chat = Own   |   CLI chat = WoW AI   |   CLI window = WoW AI" in info
    assert "[entry]openrouter/free" in t  # the model field agrees


def test_harness_window_api_backend_with_own_folder_says_the_instructions_are_sent(tmp_path):
    t = _texts(tmp_path, "harness_window", {"backend": "openrouter"}, {".claude/CLAUDE.md": "I am a pirate AI."}, tab="own")
    info = next(x for x in t if x.startswith("LOADED:"))
    assert "Own mode sends your instructions" in info and "bare model" not in info
