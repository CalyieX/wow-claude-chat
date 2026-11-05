"""The fake chat window: the parts that need no window (answer rendering, the AI hook, single instance)."""
import os
import sys
import types

from wowclaude import chat_overlay as co


def test_answer_is_one_line_with_the_ai_name():
    lines, play = co.render_answer("Gorel", "Hallo\n  du   da")
    assert lines == ["Gorel: Hallo du da"] and play is None


def test_overlay_macro_and_play_blocks_become_lines_and_a_url():
    raw = ("Hier. [[overlay Plan]]|cff00ff00gruen|r Zeile\n[bar 0.5 00ff00] Balken[[/overlay]] "
           "[[macro Pull]]/cast Fluch\n/petattack[[/macro]] [[play https://example.org/x]]")
    lines, play = co.render_answer("Claude", raw)
    assert lines[0] == "Claude: Hier."
    assert any("Plan" in ln for ln in lines) and any("gruen Zeile" in ln for ln in lines) and not any("|c" in ln for ln in lines)
    assert any(ln.strip().startswith("Macro Pull: /cast Fluch / /petattack") for ln in lines)
    assert play == "https://example.org/x"


def test_empty_answer_still_shows_something():
    assert co.render_answer("Claude", "   ")[0] == ["Claude: ..."]


def test_ai_call_can_be_replaced_by_an_environment_hook(monkeypatch):
    mod = types.ModuleType("fake_chat_ai")
    mod.answer = lambda q: "echo " + q
    monkeypatch.setitem(sys.modules, "fake_chat_ai", mod)
    monkeypatch.setenv("WOWCLAUDE_CHAT_ASK", "fake_chat_ai:answer")
    assert co.default_ask("hi") == "echo hi"


def test_alive_knows_own_process_and_a_dead_one():
    assert co.alive(os.getpid()) and not co.alive(0) and not co.alive(4000000)


def test_start_when_running_only_asks_the_window_for_focus(tmp_path, monkeypatch):
    monkeypatch.setattr(co.config, "HOME", tmp_path)
    monkeypatch.setattr(co, "PID_FILE", tmp_path / "chat.pid")
    monkeypatch.setattr(co, "FOCUS_FLAG", tmp_path / "chat.focus")
    (tmp_path / "chat.pid").write_text(str(os.getpid()))
    spawned = []
    monkeypatch.setattr(co.subprocess, "Popen", lambda *a, **k: spawned.append(a))
    assert "already open" in co.start()
    assert (tmp_path / "chat.focus").exists() and not spawned
    (tmp_path / "chat.pid").write_text("4000000")  # stale pid: a new window is started
    co.start()
    assert spawned
