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
    assert bridge.handle_command("!me Bob").startswith("Your name: Bob") and config.load()["player"] == "Bob"
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


def test_every_backend_receives_the_harness(monkeypatch):
    """A new AI (any backend) gets the same harness with every question: text prompt, system message or system file."""
    from wowclaude import backends, claude, config, setup_ui
    setup_ui.apply({"backend": "claude", "harness": "HARNESS-MARK classic is not forever"})
    seen = {}

    monkeypatch.setattr(claude, "_exec", lambda cmd, prompt, timeout=None: seen.setdefault("exec", prompt) and (0, "ok", ""))
    for b in ("codex", "command"):
        cfg = config.load(); cfg["backend"] = b; cfg["command"] = "echo"; config.save(cfg)
        monkeypatch.setattr(backends.shutil, "which", lambda n: "x")
        monkeypatch.setattr(backends, "_command", lambda: ["echo"])
        seen.clear()
        try:
            backends.ask(claude.persona()[1], [], "hi", None)
        except Exception:  # noqa: BLE001 - codex reads an output file that the stub never writes
            pass
        assert "HARNESS-MARK" in seen.get("exec", ""), b
    cfg = config.load(); cfg["backend"] = "openrouter"; config.save(cfg)
    monkeypatch.setattr(backends, "_ask_api", lambda system, h, p, m: seen.setdefault("api", system) and "ok")
    backends.ask(claude.persona()[1], [], "hi", None)
    assert "HARNESS-MARK" in seen["api"]


def test_mouse_keyboard_tool_ships_and_switches_on_from_setup_page():
    from wowclaude import vinput, setup_ui, config
    assert vinput.SHIPPED.exists() and not vinput.available()
    setup_ui.apply({"backend": "claude", "input_control": True})
    assert vinput.available() and vinput.script() == vinput.SHIPPED
    setup_ui.apply({"backend": "claude", "input_control": False})
    assert not vinput.available() and "input_control" not in config.load()


def test_setup_page_has_no_name_field_and_keeps_menu_name():
    from wowclaude import setup_ui, config
    assert 'id="ainame"' not in setup_ui.PAGE if hasattr(setup_ui, "PAGE") else True
    cfg = config.load(); cfg["name"] = "Gandalf"; config.save(cfg)
    setup_ui.apply({"backend": "claude"})
    assert config.load().get("name") == "Gandalf"


def test_errors_are_explained_in_plain_words(monkeypatch):
    from wowclaude import login, claude, backends
    monkeypatch.setattr(login, "command", lambda: None)
    assert "too long" in login.explain(claude.AskTimeout("x"))
    assert "login or key" in login.explain(RuntimeError("401 Unauthorized"))
    assert "balance" in login.explain(RuntimeError("HTTP 429 rate limit"))
    assert "internet" in login.explain(RuntimeError("getaddrinfo failed"))
    assert "not found" in login.explain(RuntimeError("the 'codex' command was not found"))
    assert "did not answer" in login.explain(RuntimeError("something odd"))


def test_login_code_is_sent_to_the_waiting_login(monkeypatch):
    from wowclaude import login
    class P:
        returncode = 0
        def __init__(self): self.got = ""; self.stdin = self
        def poll(self): return None
        def write(self, t): self.got += t
        def flush(self): pass
        def wait(self, t): self.returncode = 0
    proc = P()
    login._running[:] = [proc]
    assert "Logged in" in login.submit("abc123")
    assert proc.got == "abc123\n"
    login._running[:] = []
    assert "No login" in login.submit("x")


def test_keys_from_the_ai_cannot_run_destructive_chat_commands():
    from wowclaude import vinput
    text = "x [[keys {Enter}/run DeleteCursorItem(){Enter}]] [[keys /gquit]] [[keys {Esc}]] [[click 10 20]] [[keys hello]]"
    _, cmds = vinput.extract(text)
    assert cmds == ["keys {Esc}", "click 10 20", "keys hello"]
    assert vinput.extract("[[keys {ctrl down}]]")[1] == []


def test_input_tool_text_is_not_part_of_the_editable_harness(monkeypatch):
    from wowclaude import claude, vinput, setup_ui
    before = claude.builtin_harness()
    setup_ui.apply({"backend": "claude", "input_control": True})
    assert claude.builtin_harness() == before  # switching the tool on must not change what the page shows
    assert "BACKGROUND INPUT" in claude.persona()[1]
    setup_ui.apply({"backend": "claude", "harness": "my own text"})
    assert "BACKGROUND INPUT" in claude.persona()[1]  # the program adds the tool text even to an edited harness


def test_broken_harness_file_falls_back_to_builtin():
    from wowclaude import claude, config
    config.HOME.mkdir(parents=True, exist_ok=True)
    config.HARNESS.write_bytes("Text mit \xe4 ANSI".encode("latin-1"))
    assert claude.custom_harness() is None
    assert "GAME VERSION" in claude.persona()[1]


def test_missing_program_is_not_reported_as_login_problem():
    from wowclaude import login
    assert "not found" in login.explain(RuntimeError("The 'claude' command was not found. Install Claude Code and log in."))


def test_claude_command_line_keeps_the_tool_limits(monkeypatch):
    from wowclaude import claude, config
    seen = {}
    monkeypatch.setattr(claude, "_exec", lambda cmd, prompt, timeout=None: seen.setdefault("cmd", cmd) and (0, "ok", ""))
    claude.Session()._run("claude", "hi", None)
    cmd = seen["cmd"]
    assert cmd[cmd.index("--tools") + 1] == "WebSearch,WebFetch" and cmd[cmd.index("--allowedTools") + 1] == "WebSearch,WebFetch"
    assert "--strict-mcp-config" in cmd and "--permission-mode" not in cmd
    cfg = config.load(); cfg["computer_access"] = True; config.save(cfg)
    seen.clear()
    claude.Session()._run("claude", "hi", None)
    assert "Bash" in seen["cmd"][seen["cmd"].index("--tools") + 1]


def test_cli_mode_screen_events_replace_each_other_and_paint():
    from wowclaude import chat_fake
    e = chat_fake.apply_events([("user", "hi"), ("ai", "yo")], [{"kind": "cli", "text": "line one\nline two"}])
    e = chat_fake.apply_events(e, [{"kind": "cli", "text": "line one\nline three"}])
    assert [k for k, _ in e].count("cli") == 1 and e[-1] == ("cli", "line one\nline three")
    img = chat_fake.paint(e, (400, 200), fsize=17)
    assert img.size == (400, 200)
    e = chat_fake.apply_events(e, [{"kind": "cli", "text": ""}])  # leaving CLI mode removes the screen
    assert all(k != "cli" for k, _ in e)


def test_cli_mode_tab_size_and_keys(monkeypatch, tmp_path):
    from wowclaude import cli_mode, chat_fake, config
    assert cli_mode.tab_size() == cli_mode.DEFAULT_SIZE
    chat_fake.report_tab_size((500, 300), 17)
    cols, rows = cli_mode.tab_size()
    assert 20 <= cols <= 200 and 5 <= rows <= 60
    assert cli_mode.KEYS["up"] == "\x1b[A" and cli_mode.KEYS["enter"] == "\r"


def test_cli_mode_needs_a_command_line_login_and_is_off_by_default(monkeypatch):
    from wowclaude import cli_mode, backends, config
    assert not cli_mode.active()
    monkeypatch.setattr(backends, "name", lambda: "openrouter")
    assert cli_mode.command() is None
    monkeypatch.setattr(cli_mode, "available", lambda: (True, ""))
    assert "Claude Code or Codex" in cli_mode.set_mode("cli") and not cli_mode.active()


def test_cli_mode_bridge_commands(monkeypatch):
    from wowclaude import bridge, cli_mode
    monkeypatch.setattr(cli_mode, "set_mode", lambda m: "mode " + m)
    assert bridge.handle_command("!aimode cli") == "mode cli"
    assert bridge.handle_command("!aimode chat") == "mode chat"
    assert "off" in bridge.handle_command("!k up")
