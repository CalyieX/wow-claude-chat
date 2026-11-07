from wowclaude import cli_mode


def test_chat_mode_hides_the_running_cli_and_cli_mode_shows_it_again(monkeypatch, tmp_path):
    posted = []
    monkeypatch.setattr(cli_mode.CliMode, "_post", staticmethod(lambda text: posted.append(text)))
    m = cli_mode.CliMode()
    m.hide()
    assert m.hidden and posted == [None]  # the tab goes back to the chat, the tool is not touched
    m.show()
    assert not m.hidden and m.repost and m.dirty.is_set()  # the next paint posts the screen again
