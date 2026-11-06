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


def test_every_helper_process_is_started_hidden():
    """The addon may only ever show pop-ups that are meant to be seen (the browser window): no console flashes."""
    import pathlib
    import re
    root = pathlib.Path(__file__).resolve().parent.parent / "wowclaude"
    bad = []
    for f in root.glob("*.py"):
        src = f.read_text(encoding="utf-8")
        for m in re.finditer(r"subprocess\.(?:run|Popen|call|check_output|check_call)\(", src):
            depth, i = 1, m.end()
            while depth and i < len(src):
                depth += {"(": 1, ")": -1}.get(src[i], 0)
                i += 1
            call = src[m.start():i]
            if not re.search(r"hidden\(\)|CREATE_NO_WINDOW|0x08000000", call):
                bad.append(f"{f.name}: {call[:60]}")
    assert not bad, bad


def test_claude_token_from_setup_page_reaches_chat_and_cli(monkeypatch):
    from wowclaude import claude, config, login, setup_ui
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "stray")
    setup_ui.apply({"backend": "claude", "claude_token": "tok-123"})
    assert config.load().get("claude_token") == "tok-123"
    env = claude._clean_env()
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "tok-123" and "ANTHROPIC_API_KEY" not in env
    assert login.logged_in()  # signed in by token: no browser login needed
    assert setup_ui._state()["has_token"] is True


def test_cli_first_run_is_prepared_so_the_token_is_used(monkeypatch, tmp_path):
    import json
    from wowclaude import cli_mode, claude
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    cli_mode.prepare_config(claude.neutral_cwd())
    d = json.loads((tmp_path / ".claude.json").read_text(encoding="utf-8"))
    assert d["hasCompletedOnboarding"] is True
    assert list(d["projects"].values())[0]["hasTrustDialogAccepted"] is True


def test_memory_saves_forgets_and_never_ships(monkeypatch, tmp_path):
    import pathlib
    from wowclaude import memory
    monkeypatch.setattr(memory, "DIR", tmp_path / "memory")
    ctx = "Gorel | Level 10 | Warlock | Undercity"
    reply, acts = memory.extract("Alles klar [[remember plays solo]] [[remember all: likes short answers]] [[remember my password is x]]")
    assert "[[" not in reply and len(acts) == 3
    notes = memory.apply(ctx, acts)
    assert notes.count("saved to WoW AI memos") == 2  # the password line is refused
    block = memory.prompt_block(ctx)
    assert "plays solo" in block and "likes short answers" in block and "password" not in block
    assert "plays solo" not in memory.prompt_block("Other | Level 5")  # per character
    memory.apply(ctx, [("forget", "solo")])
    assert "plays solo" not in memory.prompt_block(ctx)
    # nothing of the author's own memory is part of the program
    root = pathlib.Path(__file__).resolve().parent.parent
    assert not list((root / "wowclaude").glob("**/memos/*.md")) and not (root / "memos").exists() and not (root / "memory").exists()


def test_cli_mode_gets_the_same_harness_as_chat_mode(monkeypatch):
    from wowclaude import cli_mode, claude
    text = cli_mode.harness_text()
    assert claude.persona()[1] in text and "never say you are Claude" in text
    cmd = cli_mode.command()
    assert "--append-system-prompt-file" in cmd
    assert cli_mode.harness_file().read_text(encoding="utf-8") == text
    monkeypatch.setenv("WOWCLAUDE_BACKEND", "codex")
    monkeypatch.setattr(cli_mode.shutil, "which", lambda n: "C:/x/codex.exe")
    assert any(a.startswith("developer_instructions=") for a in cli_mode.command())


def test_codex_cli_mode_trusts_the_neutral_folder(monkeypatch):
    from wowclaude import cli_mode, claude
    monkeypatch.setenv("WOWCLAUDE_BACKEND", "codex")
    monkeypatch.setattr(cli_mode.shutil, "which", lambda n: "C:/x/codex.exe")
    monkeypatch.setattr(claude, "computer_access", lambda: False)
    cmd = cli_mode.command()
    assert any(a.endswith('.trust_level="trusted"') for a in cmd)


def test_cli_mode_scrollback():
    import pyte
    from wowclaude import cli_mode
    c = cli_mode.CliMode()
    c.screen = pyte.HistoryScreen(40, 5, history=100)
    c.stream = pyte.Stream(c.screen)
    c.offset = 0
    c.stream.feed("".join(f"line {i}\r\n" for i in range(1, 21)))
    live = c._lines()
    assert "line 20" in live and "line 1\n" not in live
    assert c.scroll("up") == "" and "scrolled back" in c._lines()
    c.scroll("up")
    back = c._lines()
    assert "line 17" in back and "line 20" not in back and len(back.splitlines()) <= 5
    c.scroll("end")
    assert c._lines() == live
    assert "Use:" in c.scroll("sideways")


def test_panel_parse_line_colors_and_bars():
    from wowclaude import panel_window as p
    assert p.parse_line("plain") == ("text", [("plain", None)])
    kind, parts = p.parse_line("a |cff00ff00green|r b")
    assert kind == "text" and ("green", "00ff00") in parts and parts[0] == ("a ", None) and parts[-1] == (" b", None)
    assert p.parse_line("[bar 0.6 FF0000] Mana") == ("bar", (0.6, "ff0000", "Mana"))
    assert p.parse_line("[bar 5 00ff00] x")[1][0] == 1.0


def test_show_tag_and_media_pages(tmp_path, monkeypatch):
    from wowclaude import claude, media_window as m
    assert claude.extract_show("Hi [[show https://x.org/a.png]] there") == ("Hi  there", "https://x.org/a.png")
    assert claude.extract_show("nothing")[1] is None
    assert [m.kind(x) for x in ("a.PNG", "b.mp4", "c.mp3", "d.pdf", "e.md", "f.csv", "g.py")] == \
        ["image", "video", "audio", "pdf", "md", "csv", "text"]
    monkeypatch.setattr(claude, "computer_access", lambda: False)
    f = tmp_path / "n.md"
    f.write_text("# Titel\n- a\n- **b**\n| x | y |\n|---|---|\n| 1 | 2 |\n", encoding="utf-8")
    assert m.page(str(f)) is None  # a local file needs AI access
    monkeypatch.setattr(claude, "computer_access", lambda: True)
    html = m.page(str(f))
    assert "<h1>Titel</h1>" in html and "<li><b>b</b></li>" in html and "<th>x</th>" in html
    assert "<video" in m.page("https://x.org/v.mp4") and m.page("https://x.org/notes.md") is None


def test_prepare_config_uses_the_tools_own_config_folder(tmp_path, monkeypatch):
    import json
    from wowclaude import claude, cli_mode
    monkeypatch.setattr(claude, "_clean_env", lambda mode="wow": {"CLAUDE_CONFIG_DIR": str(tmp_path)})
    cli_mode.prepare_config(r"D:\work\proj")
    data = json.loads((tmp_path / ".claude.json").read_text(encoding="utf-8"))
    assert data["hasCompletedOnboarding"] and data["projects"]["D:/work/proj"]["hasTrustDialogAccepted"]


def test_cli_gets_game_state_once_and_on_change(monkeypatch):
    from wowclaude import cli_mode
    monkeypatch.setattr(cli_mode.claude, "own_harness", lambda mode: False)
    cli_mode._last_context[0] = ""
    first = cli_mode.with_state("hi", "Gorel, Warrior, Classic Era")
    assert first.startswith("[Game state: Gorel, Warrior, Classic Era]") and first.endswith("hi")
    assert cli_mode.with_state("again", "Gorel, Warrior, Classic Era") == "again"
    assert "Mage" in cli_mode.with_state("x", "Lia, Mage, Classic Era")


def test_harness_import_reads_claude_and_codex_setups(tmp_path, monkeypatch):
    from wowclaude import harness_import as hi
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    home = tmp_path / "home"
    cfg = home / ".claude"
    slug = hi.re.sub(r"[^A-Za-z0-9]", "-", str(home))
    (cfg / "projects" / slug / "memory").mkdir(parents=True)
    (cfg / "CLAUDE.md").write_text("# Mira\nYou are Mira.", encoding="utf-8")
    (cfg / "projects" / slug / "memory" / "MEMORY.md").write_text("- [Note](note.md) - a thing", encoding="utf-8")
    (cfg / "skills" / "demo").mkdir(parents=True)
    (cfg / "skills" / "demo" / "SKILL.md").write_text("---\nname: demo\ndescription: Does a demo\n---\nbody", encoding="utf-8")
    (home / ".codex").mkdir()
    (home / ".codex" / "AGENTS.md").write_text("Codex rules", encoding="utf-8")
    found = {s.kind: s for s in hi.sources(home)}
    assert set(found) == {"claude", "codex"}
    text = hi.render(found["claude"], "GAME PART")
    assert text.index("You are Mira.") < text.index("Your own memory") < text.index("Your own skills") < text.index(hi.MARK)
    assert "demo: Does a demo" in text and text.endswith("GAME PART")
    assert "Codex rules" in hi.render(found["codex"], "G")
    assert hi.sources(tmp_path / "empty") == [] and hi.render(hi.Source("claude", "x"), "G") == "G"


def test_harness_import_from_picked_folder(tmp_path):
    from wowclaude import harness_import as hi
    (tmp_path / "CLAUDE.md").write_text("I am Mira.", encoding="utf-8")
    mem = tmp_path / "projects" / "p1" / "memory"
    mem.mkdir(parents=True)
    (mem / "MEMORY.md").write_text("- note", encoding="utf-8")
    sk = tmp_path / "skills" / "demo"
    sk.mkdir(parents=True)
    (sk / "SKILL.md").write_text("---\nname: demo\ndescription: does demo\n---\nbody", encoding="utf-8")
    src = hi.from_folder(tmp_path)
    assert src.found() and src.memory_dir == mem and [s[0] for s in src.skills] == ["demo"]
    assert "I am Mira." in hi.render(src, "GAME")
    assert not hi.from_folder(tmp_path / "nothing").found()


def test_own_uses_the_chosen_claude_folder(monkeypatch):
    from wowclaude import claude, config
    cfg = {"own_harness_wow": True, "own_config_dir": "X:/claude-work"}
    monkeypatch.setattr(config, "load", lambda: cfg)
    assert claude._clean_env("wow")["CLAUDE_CONFIG_DIR"] == "X:/claude-work"
    cfg["own_harness_wow"] = False
    assert claude._clean_env("wow").get("CLAUDE_CONFIG_DIR") != "X:/claude-work"


def test_model_is_chosen_per_ai(monkeypatch):
    from wowclaude import config
    cfg = {"models": {"codex": "gpt-6-mini"}, "model": "general"}
    monkeypatch.setattr(config, "load", lambda: cfg)
    assert config.model_for("codex") == "gpt-6-mini"
    assert config.model_for("claude") == "general"
    cfg.pop("model")
    assert config.model_for("claude") is None


def test_model_command_sets_and_resets(tmp_path, monkeypatch):
    from wowclaude import bridge, config
    store = {}
    monkeypatch.setattr(config, "load", lambda: dict(store))
    monkeypatch.setattr(config, "save", lambda c: (store.clear(), store.update(c)))
    monkeypatch.setenv("WOWCLAUDE_BACKEND", "codex")
    import subprocess
    opened = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: opened.append(a))
    assert "own default" in bridge.handle_command("!model") and opened  # no name: the model popup opens
    assert "gpt-mini" in bridge.handle_command("!model gpt-mini")
    assert store["models"]["codex"] == "gpt-mini"
    assert "own default" in bridge.handle_command("!model reset")
    assert "codex" not in store["models"]


def test_model_lists_come_from_the_ai_itself(tmp_path, monkeypatch):
    import json
    from wowclaude import config, models
    monkeypatch.setattr(config, "load", lambda: {})
    (tmp_path / ".claude.json").write_text(json.dumps({"additionalModelOptionsCache": [{"value": "fable-x", "label": "Fable", "description": "big"}]}), encoding="utf-8")
    ids = [i for i, _ in models.claude_models(tmp_path)]
    assert ids[:3] == ["sonnet", "opus", "haiku"] and "fable-x" in ids
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex" / "models_cache.json").write_text(json.dumps({"models": [
        {"slug": "b", "display_name": "B", "visibility": "list", "priority": 2},
        {"slug": "a", "display_name": "A", "visibility": "list", "priority": 1},
        {"slug": "h", "display_name": "H", "visibility": "hide", "priority": 3}]}), encoding="utf-8")
    monkeypatch.delenv("CODEX_HOME", raising=False)
    assert [i for i, _ in models.codex_models(tmp_path)] == ["a", "b"]


def test_claude_model_dialog_is_parsed():
    from wowclaude import models
    lines = ["   Select model",
             "   > 1. Default (recommended) \u221a  Sonnet 5.5 \u00b7 Efficient for routine tasks",
             "     2. Opus                     Opus 5.5 \u00b7 Best for everyday, complex tasks",
             "     3. More models              Show 8 more",
             "   Enter to set as default"]
    rows = models.parse_claude_picker(lines)
    assert [r[0] for r in rows] == ["Default (recommended)", "Opus", "More models"]
    assert rows[0][2] and not rows[1][2]


def test_setup_window_deep_search_and_command(monkeypatch):
    from wowclaude import backends, setup_window, bridge
    monkeypatch.setattr(backends, "detect", lambda: [])
    monkeypatch.setattr(backends, "_port_open", lambda p, t=0.3: p == 8080)
    monkeypatch.setattr("shutil.which", lambda n: None)
    found = setup_window.deep_search()
    assert any(f["backend"] == "openai-compatible" and f["base_url"].endswith(":8080/v1") for f in found)
    launched = []
    monkeypatch.setattr("subprocess.Popen", lambda cmd, **kw: launched.append(cmd))
    assert "own window" in bridge.handle_command("!setup")
    assert launched and launched[0][-1] == "setup-window"


def test_default_name_in_persona_file_is_not_a_chosen_name(monkeypatch, tmp_path):
    from wowclaude import claude, config
    monkeypatch.setattr(config, "PERSONA", tmp_path / "persona.txt")
    monkeypatch.setattr(config, "load", lambda: {"own_harness_wow": True})
    (tmp_path / "persona.txt").write_text(claude.DEFAULT_NAME + "\nAntworte kurz.\n", encoding="utf-8")
    assert claude.persona()[0] == "Own AI"
    assert not claude.persona_name_in_file()


def test_codex_cli_command_builds_in_every_harness_mode(monkeypatch, tmp_path):
    """Regression: the Codex command line of the CLI chat/window used Path without importing it ("name 'Path' is not defined")."""
    from wowclaude import cli_mode, config
    monkeypatch.setattr(config, "load", lambda: {"backend": "codex"})
    monkeypatch.setattr("shutil.which", lambda n: "codex")
    for own in (False, True):
        for window in (False, True):
            monkeypatch.setattr(config, "load", lambda own=own: {"backend": "codex", "own_harness_cli": own, "own_harness_win": own})
            cmd = cli_mode.command(window)
            assert cmd and cmd[0] == "codex"


def test_window_title_has_the_prefix_only_once():
    from wowclaude.wowframe import _real_title
    assert _real_title("AI setup") == "WoW AI - AI setup"
    assert _real_title("WoW AI - CLI") == "WoW AI - CLI"
    assert _real_title("Own AI - CLI") == "Own AI - CLI"
