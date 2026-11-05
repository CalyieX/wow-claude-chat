"""The AI can be given a name on the setup page: it is the chat tab, the prefix of every answer and part of the prompt."""
from pathlib import Path

from wowclaude import claude, config, decode, setup_ui


def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HOME", tmp_path)
    monkeypatch.setattr(config, "CONFIG", tmp_path / "config.json")
    monkeypatch.setattr(config, "PERSONA", tmp_path / "persona.txt")


def test_ai_name_is_used_in_prompt_prefix_and_reply_file(tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    assert claude.persona()[0] == "Claude"  # default
    setup_ui.apply({"backend": "claude", "name": "  Gorel|\x01 der Weise, mit zu langem Namen dahinter ",
                    "persona": "Be brief."})
    name, system = claude.persona()
    assert name.startswith("Gorel") and "|" not in name and len(name) <= 20 and name == claude.clean_name(name)
    assert f"Your name is {name}" in system and "Be brief." in system
    setup_ui.apply({"backend": "claude", "name": "", "persona": ""})
    assert claude.persona()[0] == "Claude" and "name" not in config.load()


def test_old_persona_file_first_line_still_works_as_the_name(tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    (tmp_path / "persona.txt").write_text("Gorel\nBe brief.\n", encoding="utf-8")
    assert claude.persona()[0] == "Gorel"
    st = setup_ui._state()
    assert st["name"] == "Gorel" and st["persona"] == "Be brief."


def test_first_message_after_a_game_start_is_not_swallowed():
    from wowclaude import bridge
    assert bridge.is_fresh(1000, now=1010)        # sent 10 s ago: answer it
    assert not bridge.is_fresh(1000, now=1100)    # left over from an earlier game session: skip it
    assert not bridge.is_fresh(1000, now=900)     # a number from the future is no send time: skip it


def test_detect_finds_claude_and_env_key(monkeypatch):
    from wowclaude import backends
    monkeypatch.setattr(backends.shutil, "which", lambda n: "C:/x/claude.exe" if n == "claude" else None)
    monkeypatch.setattr(backends, "_port_open", lambda p, timeout=0.3: p == 11434)
    monkeypatch.setenv("GROQ_API_KEY", "x")
    got = [d["backend"] for d in backends.detect()]
    assert got[:2] == ["claude", "ollama"] and "groq" in got


def test_state_lists_found(monkeypatch):
    from wowclaude import backends, setup_ui
    monkeypatch.setattr(backends, "detect", lambda: [{"backend": "claude", "label": "Claude Code"}])
    assert setup_ui._state()["found"][0]["backend"] == "claude"
