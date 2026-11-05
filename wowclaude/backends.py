"""Other AI command line tools instead of Claude Code: OpenAI Codex, or any program that reads the prompt from
stdin and prints the answer (Gemini CLI, Ollama, a script of your own ...).

config.json:  {"backend": "codex"}                                  uses `codex exec` (read-only, no files touched)
              {"backend": "command", "command": "ollama run llama3.1"}   any program, prompt on stdin, answer on stdout
"""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import config

FLAGS = 0x08000000 if os.name == "nt" else 0


def name() -> str:
    return (os.environ.get("WOWCLAUDE_BACKEND") or config.load().get("backend") or "claude").lower()


PRESETS = {  # name -> (base url, default model, environment variable holding the API key or None)
    "ollama": ("http://localhost:11434/v1", "llama3.1", None),
    "lmstudio": ("http://localhost:1234/v1", "local-model", None),
    "deepseek": ("https://api.deepseek.com/v1", "deepseek-chat", "DEEPSEEK_API_KEY"),
    "openai": ("https://api.openai.com/v1", "gpt-4o-mini", "OPENAI_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1", "deepseek/deepseek-chat", "OPENROUTER_API_KEY"),
    "groq": ("https://api.groq.com/openai/v1", "llama-3.3-70b-versatile", "GROQ_API_KEY"),
    "mistral": ("https://api.mistral.ai/v1", "mistral-small-latest", "MISTRAL_API_KEY"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.0-flash", "GEMINI_API_KEY"),
}


def _api_settings() -> tuple[str, str, str | None]:
    """(base url, model, api key) for the OpenAI-compatible backends. config.json can override every part."""
    cfg = config.load()
    b = name()
    preset = PRESETS.get(b, PRESETS["ollama"])
    base = cfg.get("base_url") or preset[0]
    model = cfg.get("model") or preset[1]
    key = cfg.get("api_key")
    env = cfg.get("api_key_env") or preset[2]
    if not key and env:
        key = os.environ.get(env)
    return base.rstrip("/"), model, key


def _ask_api(system: str, history: list[tuple[str, str]], prompt: str, model: str | None) -> str:
    import json
    import urllib.error
    import urllib.request
    base, default_model, key = _api_settings()
    messages = [{"role": "system", "content": system}]
    for q, a in history[-6:]:
        messages += [{"role": "user", "content": q}, {"role": "assistant", "content": a}]
    messages.append({"role": "user", "content": prompt})
    body = json.dumps({"model": model or default_model, "messages": messages}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(base + "/chat/completions", data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=170) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"{exc.code} {exc.read().decode('utf-8', 'replace')[:180]}") from None
    except (urllib.error.URLError, OSError) as exc:
        raise RuntimeError(f"cannot reach {base}: {exc}") from None
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError, AttributeError):
        raise RuntimeError("unexpected answer: " + str(data)[:180]) from None


def _command() -> list[str]:
    raw = config.load().get("command") or os.environ.get("WOWCLAUDE_COMMAND") or ""
    if isinstance(raw, list):
        return [str(x) for x in raw]
    return shlex.split(raw, posix=(os.name != "nt")) if raw else []


def _which(cmd: list[str]) -> str | None:
    return shutil.which(cmd[0]) if cmd else None


def check() -> tuple[bool, str]:
    b = name()
    if b == "codex":
        if not shutil.which("codex"):
            return False, "The 'codex' command was not found. Install OpenAI Codex CLI and run `codex` once to log in."
        return True, "Codex found (login is checked on the first question)."
    if b == "command":
        cmd = _command()
        if not cmd:
            return False, 'backend "command" needs a "command" in ~/.wowclaude/config.json, e.g. "ollama run llama3.1".'
        if not _which(cmd):
            return False, f"Command not found: {cmd[0]}"
        return True, f"Using command: {' '.join(cmd)}"
    if b in PRESETS or b == "openai-compatible":
        base, model, key = _api_settings()
        env = config.load().get("api_key_env") or PRESETS.get(b, ("", "", None))[2]
        if env and not key and "localhost" not in base:
            return False, f"Set the environment variable {env} to your API key (or put \"api_key\" into ~/.wowclaude/config.json)."
        return True, f"Using {b}: {base}, model {model}"
    return False, f"Unknown backend '{b}' (use claude, codex, command, openai-compatible or one of: {', '.join(PRESETS)})."


def ask(system: str, history: list[tuple[str, str]], prompt: str, model: str | None) -> str:
    text = system + "\n\n"
    for q, a in history[-6:]:
        text += f"Player: {q}\nYou: {a}\n\n"
    text += f"Player: {prompt}\nYou:"
    b = name()
    if b == "codex":
        exe = shutil.which("codex")
        if not exe:
            raise RuntimeError("the 'codex' command was not found")
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "answer.txt"
            cmd = [exe, "exec", "--skip-git-repo-check", "--ephemeral", "--ignore-user-config", "-s", "read-only",
                   "--color", "never",
                   "-C", str(config.HOME), "-o", str(out_file)]
            if model:
                cmd += ["-m", model]
            config.HOME.mkdir(parents=True, exist_ok=True)
            done = subprocess.run(cmd + ["-"], input=text, capture_output=True, text=True, encoding="utf-8",
                                  timeout=180, creationflags=FLAGS)
            answer = out_file.read_text(encoding="utf-8").strip() if out_file.exists() else ""
            if done.returncode != 0 or not answer:
                raise RuntimeError((done.stderr or done.stdout or "codex failed").strip()[-200:])
            return answer
    if b == "command":
        cmd = _command()
        done = subprocess.run(cmd, input=text, capture_output=True, text=True, encoding="utf-8", timeout=180,
                              creationflags=FLAGS)
        answer = (done.stdout or "").strip()
        if done.returncode != 0 or not answer:
            raise RuntimeError((done.stderr or answer or "command failed").strip()[:200])
        return answer
    if b in PRESETS or b == "openai-compatible":
        return _ask_api(system, history, prompt, model)
    raise RuntimeError(f"unknown backend {b}")
