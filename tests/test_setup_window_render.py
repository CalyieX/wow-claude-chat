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
from tkinter import ttk
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
            elif isinstance(c, (tk.Entry, ttk.Entry)):
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
    (home / ".wowclaude").mkdir(parents=True, exist_ok=True)
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
    t = _texts(tmp_path, "harness_window", {"backend": "openrouter"}, {".claude" + "/CLAUDE.md": "I am a pirate AI."}, tab="own")
    info = next(x for x in t if x.startswith("LOADED:"))
    assert "Own mode sends your instructions" in info and "bare model" not in info


def _fake_ai_server():
    """A tiny OpenAI-style server on localhost: the real HTTP path of an API backend, without any account."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class H(BaseHTTPRequestHandler):
        def do_GET(self):  # the model list
            body = json.dumps({"data": [{"id": "zeta/big"}, {"id": "alpha/small:free"}, {"id": "openrouter/free"}, {"id": "beta/mid"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            body = json.dumps({"choices": [{"message": {"content": "OK"}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _isolated(tmp_path, monkeypatch):
    from wowclaude import config
    monkeypatch.setattr(config, "HOME", tmp_path)
    monkeypatch.setattr(config, "CONFIG", tmp_path / "config.json")
    monkeypatch.setattr(config, "PERSONA", tmp_path / "persona.txt")
    monkeypatch.setattr(config, "LAST_ANSWER", tmp_path / "last_answer.json")
    monkeypatch.delenv("WOWCLAUDE_BACKEND", raising=False)


def test_unload_stops_every_answer_and_loading_again_restores_it(tmp_path, monkeypatch):
    from wowclaude import claude, config, setup_ui
    _isolated(tmp_path, monkeypatch)
    srv = _fake_ai_server()
    try:
        base = f"http://127.0.0.1:{srv.server_port}/v1"
        assert setup_ui.apply({"backend": "openai-compatible", "base_url": base, "model": "m"})["ok"]
        s = claude.Session()
        assert s.ask("hi") == "OK"
        assert setup_ui.unload()["ok"] and not config.ai_loaded()
        with pytest.raises(RuntimeError, match="No AI loaded"):
            s.ask("hi")
        assert config.load()["backend"] == "openai-compatible" and config.load()["model"] == "m"  # settings stay
        setup_ui.apply({"backend": "openai-compatible", "base_url": base, "model": "m"})  # clicking an AI loads it again
        assert config.ai_loaded() and s.ask("hi again") == "OK"
    finally:
        srv.shutdown()


def test_probe_asks_a_real_question_and_records_the_result(tmp_path, monkeypatch):
    from wowclaude import config, setup_ui
    _isolated(tmp_path, monkeypatch)
    srv = _fake_ai_server()
    try:
        setup_ui.apply({"backend": "openai-compatible", "base_url": f"http://127.0.0.1:{srv.server_port}/v1", "model": "m"})
        r = setup_ui.probe()
        assert r["ok"] and "answered: OK" in r["status"]
        rec = config.last_answer()
        assert rec["ok"] and rec["backend"] == "openai-compatible" and rec["model"] == "m" and rec["seconds"] >= 0
    finally:
        srv.shutdown()
    setup_ui.apply({"backend": "openai-compatible", "base_url": "http://127.0.0.1:1/v1", "model": "m"})  # nothing listens there
    r = setup_ui.probe()
    assert not r["ok"] and not config.last_answer()["ok"] and config.last_answer()["error"]


def test_describe_last_is_plain_about_success_failure_and_nothing_yet():
    from wowclaude import setup_window
    assert "none yet" in setup_window.describe_last({}, 100.0)
    ok = {"t": 90.0, "ok": True, "seconds": 2.5, "backend": "claude", "model": "sonnet"}
    assert setup_window.describe_last(ok, 100.0) == "Last answer: 10 s ago, ok, 2.5 s (claude, sonnet)"
    bad = {"t": 0.0, "ok": False, "seconds": 1.0, "backend": "cerebras", "model": "m", "error": "402 payment"}
    assert setup_window.describe_last(bad, 300.0) == "Last answer: 5 min ago, FAILED (cerebras, m): 402 payment"


def test_setup_window_shows_off_state_and_the_last_answer(tmp_path):
    t = _texts(tmp_path, "setup_window", {"backend": "claude", "models": {"claude": "sonnet"}, "ai_off": True})
    assert "AI is off: nothing answers until you load one." in t
    assert not any(x.startswith("Loaded now") for x in t)
    (tmp_path / "home" / ".wowclaude" / "last_answer.json").write_text(
        json.dumps({"t": __import__("time").time() - 5, "ok": False, "seconds": 3.0, "backend": "cerebras", "model": "m",
                    "error": "402 payment"}), encoding="utf-8")
    t = _texts(tmp_path, "setup_window", {"backend": "cerebras", "model": "m"})
    assert any(x.startswith("Last answer:") and "FAILED (cerebras, m): 402 payment" in x for x in t)
    assert "Unload" in t and "Test now" in t


def test_unload_ends_a_running_cli_session_and_blocks_typed_lines(monkeypatch, tmp_path):
    """Unload must not leave a running command line tool answering: the session ends within a second."""
    import threading
    from wowclaude import cli_mode, config
    monkeypatch.setattr(config, "HOME", tmp_path)
    monkeypatch.setattr(config, "CONFIG", tmp_path / "config.json")
    (tmp_path / "win_in.jsonl").write_text("", encoding="utf-8")
    config.save({"backend": "claude", "ai_off": True})
    m = cli_mode.CliMode(window=True)
    stopped = threading.Event()
    monkeypatch.setattr(m, "running", lambda: True)
    monkeypatch.setattr(m, "stop", lambda: stopped.set())
    threading.Thread(target=m._input_loop, args=(m.gen,), daemon=True).start()
    assert stopped.wait(4)
    assert "No AI loaded" in m.send_line("hi")


def test_list_models_reads_the_servers_own_list_free_ones_first(tmp_path, monkeypatch):
    from wowclaude import backends, config
    _isolated(tmp_path, monkeypatch)
    srv = _fake_ai_server()
    try:
        got = backends.list_models("openai-compatible", f"http://127.0.0.1:{srv.server_port}/v1")
    finally:
        srv.shutdown()
    assert got == ["alpha/small:free", "openrouter/free", "beta/mid", "zeta/big"]
    assert backends.list_models("openai-compatible", "http://127.0.0.1:1/v1") == []  # nothing there: an honest empty list
    assert backends.list_models("claude") == ["sonnet", "opus", "haiku"] and config.load() == {}


def test_setup_window_has_the_model_list_button_and_the_plain_text_key_note(tmp_path):
    t = _texts(tmp_path, "setup_window", {"backend": "openrouter", "model": "openrouter/free"})
    assert "List" in t
    assert any("saved as plain text in config.json" in x for x in t)
    assert t[t.index("Model (empty = default)") + 1] == "[entry]openrouter/free"


def test_no_test_writes_the_real_last_answer_file():
    """The setup window shows last_answer.json as live data: a test run must never put its own results there."""
    from wowclaude import config
    assert config.LAST_ANSWER.parent == config.HOME and "wowclaude-home" in str(config.HOME)
