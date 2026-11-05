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
    return False, f"Unknown backend '{b}' (use claude, codex or command)."


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
    raise RuntimeError(f"unknown backend {b}")
