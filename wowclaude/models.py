"""Which models the loaded AI can use right now - always read live from the AI itself, never a list kept in this program.

  Claude Code   the aliases sonnet / opus / haiku (always the newest of each), plus the extra models the account unlocked
                (Claude Code keeps them in its own .claude.json cache, refreshed by Claude Code)
  Codex         the model cache of the account (~/.codex/models_cache.json, refreshed by Codex from the server)
  API / Ollama  the /models endpoint of the provider (needs the key / the local program running)
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from . import backends, config


def _json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def claude_models(home: Path | None = None) -> list[tuple[str, str]]:
    home = home or Path.home()
    out = [("sonnet", "Sonnet - the newest Sonnet"), ("opus", "Opus - the newest Opus"), ("haiku", "Haiku - the newest, fastest and cheapest")]
    cfg_dir = Path(config.load().get("own_config_dir") or os.environ.get("CLAUDE_CONFIG_DIR") or home)
    for f in (cfg_dir / ".claude.json", home / ".claude.json"):
        data = _json(f)
        if isinstance(data, dict):
            for m in data.get("additionalModelOptionsCache") or []:
                if isinstance(m, dict) and m.get("value"):
                    out.append((str(m["value"]), f'{m.get("label", m["value"])} - {m.get("description", "")}'.strip(" -")))
            break
    return out


def codex_models(home: Path | None = None) -> list[tuple[str, str]]:
    home = home or Path.home()
    data = _json(Path(os.environ.get("CODEX_HOME") or (home / ".codex")) / "models_cache.json")
    models = [m for m in (data or {}).get("models", []) if isinstance(m, dict) and m.get("visibility", "list") == "list"]
    models.sort(key=lambda m: m.get("priority", 99))
    return [(str(m["slug"]), f'{m.get("display_name", m["slug"])}' + (f' - {m["description"]}' if m.get("description") else "")) for m in models]


def api_models() -> list[tuple[str, str]]:
    import urllib.request
    base, _model, key = backends._api_settings()
    req = urllib.request.Request(base + "/models", headers={"Authorization": f"Bearer {key}"} if key else {})
    with urllib.request.urlopen(req, timeout=8) as r:  # noqa: S310 - the provider the player configured
        data = json.loads(r.read().decode("utf-8"))
    ids = sorted(str(m.get("id")) for m in data.get("data", data if isinstance(data, list) else []) if isinstance(m, dict) and m.get("id"))
    return [(i, i) for i in ids]


def available(backend: str | None = None) -> tuple[list[tuple[str, str]], str]:
    """([(id, label)], note). The note says where the list came from or why it is empty."""
    b = backend or backends.name()
    try:
        if b == "claude":
            return claude_models(), "Claude Code: newest of each family plus what your account unlocked."
        if b == "codex":
            ms = codex_models()
            return ms, ("Codex: what your account can use (read from Codex itself)." if ms else "Codex has not loaded its model list yet: open Codex once.")
        if b in backends.PRESETS or b == "openai-compatible":
            ms = api_models()
            return ms, f"{b}: live from the provider."
    except Exception as exc:  # noqa: BLE001 - offline, bad key, program not running: say it, do not crash the popup
        return [], f"{b}: the list could not be read ({str(exc)[:80]})."
    return [], f"{b}: no model list available - type the name with /model <name>."
