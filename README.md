# K&K WoW AI Chat (wowclaude): chat with Claude inside World of Warcraft

Write in a chat tab called **Claude** and the answer appears in the same tab, right in the game. Longer answers
open a small window (text, coloured lines, progress bars). It works with **WoW Forever** and the Classic clients.

```
You: how do I get to the Undercity from Tirisfal?
Claude: Follow the road south-east to the Ruins of Lordaeron, the elevator is at the entrance.
```

The game never gets any keystrokes from this tool. The addon draws a small colour strip in the top-left corner,
a Python program on your PC reads it from the screen, asks Claude, and hands the answer back through
pre-made addon files. (The return channel is the idea from the MIT-licensed *wow-ai* project.)

## Setup (about 3 minutes)

You need: Windows, [Python 3.9+](https://www.python.org/downloads/), and [Claude Code](https://claude.com/claude-code)
installed and logged in once (a Claude subscription or API access works, whatever Claude Code uses).

1. Download this repository (green **Code** button, *Download ZIP*) and unpack it.
2. Double-click **`install.bat`**. It installs the program and puts the addon into your game folder
   (found automatically; if not, it tells you what to do).
3. **Close the game completely and start it again** (new addons need a full restart, `/reload` is not enough).
4. Double-click **`start.bat`** and keep that window open while you play.
5. In the game click the **Claude** tab and write.

Check problems any time with `py -3 -m wowclaude doctor`.

## Good to know

- Run the game in **windowed or borderless** mode and do not cover the top-left corner of the game window,
  otherwise the strip cannot be read. Exclusive fullscreen does not work.
- The strip is only visible while you type in the Claude tab and while Claude is thinking (a small label under it says
  so). `/kkmap always` keeps it visible, `/kkmap auto` goes back to the default, `/kkmap off` switches the addon off.
- Claude gets your character's name, level, class, zone, XP, money, combat state and pet name with every question.
  Nothing else leaves the game. Claude runs **without tools**: it cannot read or change files on your PC.
- After about 200 answers the addon reloads the interface by itself (a short hiccup) to reset its answer slots.
- Don't `/reload` while Claude is still thinking, the pending question is lost.
- Macro helper: `/kkm Name~line one\nline two` creates a macro and puts it on your cursor.
- Own style: create `%USERPROFILE%\.wowclaude\persona.txt`. First line = name shown before answers, the rest is added
  to Claude's instructions. `config.json` in the same folder can hold `"model"` and `"wow_root"`.

## Other AIs (local models, DeepSeek, ChatGPT ...)

Claude Code is the default, but any of these work. Put the choice into `%USERPROFILE%\.wowclaude\config.json`:

| You want | config.json | Extra |
|---|---|---|
| Local model (Ollama) | `{"backend": "ollama", "model": "llama3.1"}` | `ollama pull llama3.1` first, no key |
| LM Studio (local) | `{"backend": "lmstudio"}` | start its local server |
| DeepSeek | `{"backend": "deepseek"}` | environment variable `DEEPSEEK_API_KEY` |
| OpenAI / OpenRouter / Groq / Mistral / Gemini | `{"backend": "openai"}` (or `openrouter`, `groq`, `mistral`, `gemini`) | key in `OPENAI_API_KEY` etc. |
| Any OpenAI-compatible server | `{"backend": "openai-compatible", "base_url": "http://host:port/v1", "model": "name", "api_key_env": "MY_KEY"}` | |
| OpenAI Codex CLI | `{"backend": "codex"}` | run `codex` once to log in |
| Any program (stdin in, answer out) | `{"backend": "command", "command": "my-tool --flag"}` | |

Keep API keys in environment variables, not in files you share. `py -3 -m wowclaude doctor` tells you what is missing.
Small local models follow the macro and window instructions less reliably than Claude.

## Fair-play note

This tool reads your own screen and writes only into addon files; it presses no keys and sends no commands to the game.
It still is third-party software next to a game client: check the rules of the server or client you play on, and use it
at your own risk. It is not affiliated with Blizzard or Anthropic.

## Deutsch (kurz)

`install.bat` doppelklicken, Spiel **komplett neu starten**, `start.bat` offen lassen, im Chat-Tab **Claude** schreiben.
Spiel im Fenster- oder randlosen Modus, obere linke Ecke nicht verdecken. Prüfen mit `py -3 -m wowclaude doctor`.

## Development

```
py -3 -m pip install -e . pytest
py -3 -m pytest
```

MIT licensed.

## Browser overlay (YouTube, Netflix, Twitter ...)

```
wowclaude overlay https://www.youtube.com --corner br --size 480x270 --opacity 90
wowclaude overlay https://www.netflix.com --click-through
```

Opens a small always-on-top Chrome/Edge window (own profile: log in once) over the game. Needs the game in windowed
or borderless mode. `--click-through` sends mouse clicks to the game. Close the window to stop.
