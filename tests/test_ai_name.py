"""The AI can be given a name on the setup page: it is the chat tab, the prefix of every answer and part of the prompt."""
from pathlib import Path

from wowclaude import claude, config, decode, setup_ui


def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HOME", tmp_path)
    monkeypatch.setattr(config, "CONFIG", tmp_path / "config.json")
    monkeypatch.setattr(config, "PERSONA", tmp_path / "persona.txt")


def test_ai_name_is_used_in_prompt_prefix_and_reply_file(tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    assert claude.persona()[0] == "WoW AI"  # default: nothing chosen
    setup_ui.apply({"backend": "claude", "name": "  Gorel|\x01 der Weise, mit zu langem Namen dahinter ",
                    "persona": "Be brief."})
    name, system = claude.persona()
    assert name.startswith("Gorel") and "|" not in name and len(name) <= 20 and name == claude.clean_name(name)
    assert f"Your name is {name}" in system and "Be brief." in system
    setup_ui.apply({"backend": "claude", "name": "", "persona": ""})
    assert claude.persona()[0] == "WoW AI" and "name" not in config.load()


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


def test_real_tab_names_are_never_taken_over():
    from wowclaude import claude
    assert claude.clean_name("General") == "" and claude.clean_name("Allgemein") == ""
    assert claude.clean_name("Gorel") == "Gorel"


def test_state_offers_a_prompt_for_the_users_own_ai():
    from wowclaude import setup_ui
    p = setup_ui._state()["prompt"]
    assert "backend" in p and "doctor --deep" in p and "openrouter" in p


def test_no_name_chosen_the_ai_writes_as_wow_ai_and_a_chosen_name_wins(monkeypatch):
    from wowclaude import claude, config
    for backend in ("claude", "codex", "openrouter"):
        config.save({"backend": backend})
        assert claude.persona()[0] == "WoW AI"
    config.save({"backend": "codex", "name": "Gandalf"})
    assert claude.persona()[0] == "Gandalf"
    config.save({"backend": "codex"})  # name removed again: back to WoW AI
    assert claude.persona()[0] == "WoW AI"


def test_prompt_for_own_ai_has_no_private_paths():
    from pathlib import Path
    from wowclaude import setup_ui
    p = setup_ui.ai_prompt()
    assert str(Path.home()) not in p and "Users" not in p and "~/.wowclaude/config.json" in p


def test_prompt_tells_the_ai_to_make_a_long_lived_login():
    from wowclaude import setup_ui
    assert "setup-token" in setup_ui.ai_prompt() and "year" in setup_ui.ai_prompt()


def test_player_name_comes_only_from_the_menu_and_the_ai_never_asks(monkeypatch):
    from wowclaude import claude, config, bridge
    system = claude.persona()[1]
    assert "what you should call them" not in system and "[[me" not in system
    assert bridge.handle_command("!me Bob").startswith("Dein Name: Bob") and config.load()["player"] == "Bob"
    assert "Call them Bob" in claude.persona()[1]
    bridge.handle_command("!me")
    assert "player" not in config.load() and "briefly ask" not in claude.persona()[1]


def test_flavor_from_interface_number():
    from wowclaude import claude
    assert "Forever" in claude.flavor("Client 1.16.1 iface 16001 deDE")
    assert "Classic Era" in claude.flavor("x | Client 1.15.8 iface 11508 enUS")
    assert "Wrath" in claude.flavor("iface 30403")
    assert claude.flavor("no version here") == ""


def test_system_prompt_has_version_research_and_tools():
    from wowclaude import claude
    p = claude.DEFAULT_SYSTEM
    assert "GAME VERSION" in p and "RESEARCH FIRST" in p and "CHARACTER" in p
    for tool in ("[[macro", "[[overlay", "[[play", "/wac", "/browser"):
        assert tool in p
    assert not any(w in p.lower() for w in ("bor" + "ro", "caly" + "ie"))


def test_claude_backend_gets_only_web_tools():
    from wowclaude import claude
    assert claude.WEB_TOOLS == "WebSearch,WebFetch"


def test_login_detects_expired_session_errors():
    from wowclaude import login
    assert login.is_auth_error("Failed to authenticate: OAuth session expired and could not be refreshed")
    assert login.is_auth_error("Not logged in - please run codex login")
    assert not login.is_auth_error("ssh: connect to host port 22: Connection timed out")


def test_login_command_follows_backend(monkeypatch):
    from wowclaude import login, backends, claude
    monkeypatch.setattr(backends, "name", lambda: "claude")
    monkeypatch.setattr(claude, "claude_path", lambda: "claude-exe")
    assert login.command() == ["claude-exe", "auth", "login"]
    monkeypatch.setattr(backends, "name", lambda: "openrouter")
    assert login.command() is None
    assert "key" in login.start()


def test_bridge_login_command(monkeypatch):
    from wowclaude import bridge, login
    monkeypatch.setattr(login, "start", lambda: "opened")
    assert bridge.handle_command("!login") == "opened"


def test_custom_harness_replaces_builtin_and_reset(tmp_path):
    from wowclaude import claude, config, setup_ui
    assert claude.custom_harness() is None
    assert "GAME VERSION" in claude.persona()[1] and "MACROS" in claude.persona()[1]
    setup_ui.apply({"backend": "claude", "harness": "You are a pirate. Be brief."})
    p = claude.persona()[1]
    assert p.startswith("You are a pirate") and "GAME VERSION" not in p and "Your name is" in p
    state = setup_ui._state()
    assert state["harness_custom"] and state["harness"].startswith("You are a pirate")
    setup_ui.apply({"backend": "claude", "harness": claude.builtin_harness()})  # unchanged text = built-in again
    assert claude.custom_harness() is None
    setup_ui.apply({"backend": "claude", "harness": "x y z"})
    setup_ui.apply({"backend": "claude", "harness_reset": True})
    assert claude.custom_harness() is None and not config.HARNESS.exists()
