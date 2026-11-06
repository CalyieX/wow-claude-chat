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
    monkeypatch.setattr(config, "HARNESS", home / "harness.txt")
    monkeypatch.setattr(config, "SESSION", home / "session.txt")
    monkeypatch.delenv("WOWCLAUDE_CLAUDE", raising=False)
    monkeypatch.setattr(config, "client_root", lambda *a, **k: (a[0] if a and a[0] else k.get("root")) and __import__("pathlib").Path(a[0] if a and a[0] else k.get("root")))  # never autodetect (and write into) the real game folder
