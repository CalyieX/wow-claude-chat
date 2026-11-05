# Manual test checklist (things the automated tests cannot see)

Run `py -3 -m wowclaude doctor --deep` first. Then, in the real game:

1. Install, restart the game completely, start `start.bat`. Type in the **Claude** tab: an answer arrives.
2. `/reload` while the AI is thinking: no error, next question works.
3. Write a second message while the first answer is still coming: both answers arrive.
4. In combat: write in the Claude tab, no "action blocked / taint" popup.
5. `/wac` menu: AI Setup and Open Browser both open a window; minimize, ghost, close, resize work.
6. Move/resize the game window: the browser frame follows and scales; minimize the game: it hides.
7. Display scale 125 % / 150 % / 200 %, and a second monitor on the left (negative coordinates).
8. Exclusive fullscreen is NOT supported (expected: the strip is not seen, `doctor` says so).

Please report display scale, monitor setup, Windows version, Python version and game flavour with any bug.
