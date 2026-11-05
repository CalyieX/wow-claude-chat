"""The AI can be given a name on the setup page: it is the chat tab, the prefix of every answer and part of the prompt."""
from pathlib import Path

from wowclaude import claude, config, decode, setup_ui, slots


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
    assert f'name = "{name}"' in slots.reply_lua(1, ["x"], None, None, name)
    assert "name =" not in slots.reply_lua(1, ["x"])  # no name: nothing to rename
    setup_ui.apply({"backend": "claude", "name": "", "persona": ""})
    assert claude.persona()[0] == "Claude" and "name" not in config.load()


def test_old_persona_file_first_line_still_works_as_the_name(tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    (tmp_path / "persona.txt").write_text("Gorel\nBe brief.\n", encoding="utf-8")
    assert claude.persona()[0] == "Gorel"
    st = setup_ui._state()
    assert st["name"] == "Gorel" and st["persona"] == "Be brief."


def test_lua_addon_takes_over_the_ai_name_from_the_reply(tmp_path):
    import sys
    import pytest
    pytest.importorskip("lupa")
    sys.path.insert(0, str(Path(__file__).parent))
    import lua_harness as h
    lua = h.run_addon(Path(slots.ADDON_SRC) / "KKMap.lua")
    addons = tmp_path / "Interface" / "AddOns"
    (addons / "KKMap" / "sig").mkdir(parents=True)
    for i in range(1, 8):
        (addons / f"KKR{i:03d}").mkdir()
    lua.eval("function() SlashCmdList['KKCHAT']('Hallo') end")()
    st = decode.decode(h.strip_image(lua))
    marker = addons / "KKMap" / "sig" / f"{st.message_idx:03d}.wav"

    def play(path):
        return marker.exists() and marker.stat().st_size > 0 and str(path).endswith(marker.name)

    def load(name):
        f = addons / name / "Reply.lua"
        if not f.exists():
            return False
        lua.execute(f.read_text(encoding="utf-8"))
        return True
    lua.globals().__play, lua.globals().__load = play, load
    assert lua.eval("function() return KKMapDB.aiName end")() is None  # not renamed yet
    slots.reset_marker(tmp_path, st.message_idx)
    slots.publish(tmp_path, st.message_seq, st.message_idx, ["Gorel: Hi!"], None, None, 1, "Gorel")
    lua.eval("function() __update(1.0) end")()
    assert lua.eval("function() return KKMapDB.aiName end")() == "Gorel"
