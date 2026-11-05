# K&K WoW AI Chat (wowclaude): chat with an AI inside World of Warcraft

> **Alpha - work in progress.** Under active development: things can break, change or be missing. See
> [Tested on](#tested-on) for what has really been tried. Feedback and bug reports are welcome.

Write in a chat tab called **Claude** and the answer appears in the same tab, right in the game. Longer answers
open a small window (text, coloured lines, progress bars). Made for **WoW Forever**; the Classic clients are detected
too but not verified yet.

```
You: how do I get to the Undercity from Tirisfal?
Claude: Follow the road south-east to the Ruins of Lordaeron, the elevator is at the entrance.
```

How it works: the addon draws a tiny colour strip in the top-left corner, a Python program on your PC reads it from the
screen, asks the AI, and hands the answer back through pre-made addon files. By default the game never receives
keystrokes or commands from this tool. (The return channel is the idea from the MIT-licensed *wow-ai* project.)

## Setup (about 5 minutes)

You need: Windows, [Python 3.9+](https://www.python.org/downloads/) (with tcl/tk, the default installer has it),
Chrome, Edge or Brave (only for the browser window), and an AI: [Claude Code](https://claude.com/claude-code) logged in
once, or any of the [other AIs](#other-ais) below.

1. Download this repository (green **Code** button, *Download ZIP*) and unpack it.
2. Double-click **`install.bat`**. It installs the program and puts the addon into your game folder (found
   automatically; if not, it tells you what to do). The addon is just three small files.
3. **Close the game completely and start it again** (new addons need a full restart, `/reload` is not enough).
4. Double-click **`start.bat`** and keep that window open while you play.
5. In the game click the **Claude** tab and write. No AI set up yet? Type `/wac` and press **AI Setup**.

`py -3 -m wowclaude doctor` checks everything and says what is missing (game folder, display scale, browser, AI login,
whether the strip is visible). `py -3 -m wowclaude uninstall` removes the addon (and any old reply-slot addons) again.
If `wowclaude` is not found, use `py -3 -m wowclaude ...`.

## In the game

- `/wac` opens a small menu: **AI Setup**, **Open Browser**, **Bridge: always visible / only when needed**, **Show
  Overlay Window**, **Help**. `/ol` shows the overlay window, `/strip always|auto|off` controls the colour strip. Other commands: `/browser [url]`, `/c question`, `/wm Name~line one\nline two`
  (creates a macro and puts it on your cursor).
- Run the game in **windowed or borderless** mode and do not cover the top-left corner of the game window; exclusive
  fullscreen does not work. The strip is only visible while you type in the Claude tab and while the AI is thinking
  (a small label next to it says so). `/strip always` keeps it visible, `/strip auto` is the default, `/strip off`
  switches the addon off.
- The conversation in the Claude tab survives `/reload` and restarts (last 100 lines). Windows you moved (menu, answer
  window) stay where you put them.
- Every answer uses one of 300 reply slots (the addons `KKR001`..`KKR300`, collapsed into one `KKMap` group in the addon
  list). Only when all 300 of one game session are used does the addon reload the interface by itself, once. Don't
  `/reload` while the AI is still thinking, the pending question is lost.

## Browser window

`/wac` -> **Open Browser** (or `/browser`, or ask the AI to show a page with `[[play URL]]`) opens a small always-on-top
Chrome/Edge window over the game, styled like the game's own windows: address bar for URLs or search words, ghost button
(see-through, clicks go to the game), minimize (becomes a draggable action-bar-style button), close, resize grip.
It starts on Google. It has its own profile (log in to YouTube, Netflix ... once), remembers position and size, follows
and scales with the game window when you move or resize it, and hides while the game is minimized. Also from a
terminal: `wowclaude overlay https://www.youtube.com --corner br --size 480x270`. If it does not open, see
`~/.wowclaude/overlay.log`.

The frame uses a few small World of Warcraft interface textures (in `wowclaude/art/`, (c) Blizzard Entertainment, only
for the look of this window). If a file is missing the frame is drawn in code instead. Your own textures with the
same file names in `~/.wowclaude/art/` take priority. Put `FRIZQT__.TTF` into `~/.wowclaude/` for the game font.

## Choosing the AI (no files to edit)

`/wac` -> **AI Setup** opens a page in the browser window: pick the backend (Claude, Codex, OpenRouter, DeepSeek,
OpenAI, Groq, local models such as Ollama ...), the model, paste an API key if needed, name the AI, set a persona. Without the game:
`wowclaude config`. The page runs on 127.0.0.1 only, protected by a one-time token. An API key you enter is stored in
plain text in `~/.wowclaude/config.json` on your computer.

### Other AIs

Or write the choice into `~/.wowclaude/config.json` yourself:

| You want | config.json | Extra |
|---|---|---|
| Claude Code (default) | nothing | log in once with `claude` |
| Local model (Ollama) | `{"backend": "ollama", "model": "llama3.1"}` | `ollama pull llama3.1` first, no key |
| LM Studio (local) | `{"backend": "lmstudio"}` | start its local server |
| DeepSeek | `{"backend": "deepseek"}` | environment variable `DEEPSEEK_API_KEY` |
| OpenAI / OpenRouter / Groq / Mistral / Gemini | `{"backend": "openai"}` (or `openrouter`, `groq`, `mistral`, `gemini`) | key in `OPENAI_API_KEY` etc. |
| Any OpenAI-compatible server | `{"backend": "openai-compatible", "base_url": "http://host:port/v1", "model": "name", "api_key_env": "MY_KEY"}` | |
| OpenAI Codex CLI | `{"backend": "codex"}` | run `codex` once to log in |
| Any program (stdin in, answer out) | `{"backend": "command", "command": "my-tool --flag"}` | |

The AI may open web pages in the browser window only with `https://` addresses (`[[play URL]]`). Prefer environment variables for API keys. Small local models follow the macro and window instructions less reliably.

## Privacy

With every question the AI gets your character's name, level, class, zone, XP, money, combat state and pet name.
Nothing else leaves the game. Other players' chat is never read. With the Claude backend the AI runs **without tools**
(it cannot read or change files on your PC); every other backend sends the text to that provider, so check their terms.
Using a Claude subscription through a third-party program may be restricted by Anthropic's terms: if in doubt use an
API key backend. Give the AI a name on the AI Setup page (`/wac` > AI Setup): the chat tab and every answer then show that name instead of
"Claude" (the tab is renamed with the next answer). Your own style: `~/.wowclaude/persona.txt` (extra instructions).

## Fair-play note

By default this tool only reads your own screen and writes addon files; it presses no keys and sends no commands to
the game. An **optional input control** (off by default; `"input_control": true`, `"input_script"` and `"input_ahk"` in
`config.json`, needs AutoHotkey v2 and a helper script you provide) lets the AI click and type into the game window,
which can include chat and slash commands. Do not enable it where automation is not allowed. It is still third-party
software next to a game client: check the rules of the server or client you play on, and use it at your own risk. Not
affiliated with Blizzard or Anthropic; "World of Warcraft" is a trademark of Blizzard Entertainment.

## Tested on

Verified: Windows 11, WoW Forever, Chrome, 100 % display scale, one monitor, Python 3.12, Claude Code and the generic
API backends in tests. **Not verified yet:** display scale above 100 % (the program is DPI-aware now, unproven), several
monitors, Windows 10, Edge/Brave, the Classic clients, Python 3.9-3.11. A manual checklist for what tests cannot see is in [TESTING.md](TESTING.md); CI runs the tests on Python 3.9 and 3.12. Tests: the addon itself runs inside a fake WoW
API (`pip install lupa`) and its strip is decoded by the Python decoder; there are no tests inside the real game.

## Deutsch (kurz)

`install.bat` doppelklicken, Spiel **komplett neu starten**, `start.bat` offen lassen, im Chat-Tab **Claude**
schreiben. `/wac` öffnet das Menü (KI einrichten, Browser). Spiel im Fenster- oder randlosen Modus, obere linke Ecke
nicht verdecken. Prüfen mit `py -3 -m wowclaude doctor`, entfernen mit `py -3 -m wowclaude uninstall`.

## Development

```
py -3 -m pip install -e . pytest lupa
py -3 -m pytest
```

MIT licensed.

## Chat window over the game (no addon slots, no reload)

`/chat` in the game (or `wowclaude chat`) opens a chat window over the game that looks like the WoW chat and talks to
the AI directly. Click into it or press `Ctrl+Shift+Space` to write, `Enter` sends and gives the keyboard back to the
game, `Esc` too. Drag the title to move it, the corner to resize it; it follows the game window and is hidden while the
game is minimized. Answers can still open pages (`[[play URL]]`) and show window/macro blocks as text lines.

