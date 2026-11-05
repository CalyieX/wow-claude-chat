"""Every test runs against an empty private HOME: never touch (or depend on) the real ~/.wowclaude."""
import pytest


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    from wowclaude import config
    home = tmp_path / "wowclaude-home"
    home.mkdir()
    monkeypatch.setattr(config, "HOME", home)
    monkeypatch.setattr(config, "CONFIG", home / "config.json")
    monkeypatch.setattr(config, "PERSONA", home / "persona.txt")
    monkeypatch.setattr(config, "SESSION", home / "session.txt")
    monkeypatch.delenv("WOWCLAUDE_CLAUDE", raising=False)
