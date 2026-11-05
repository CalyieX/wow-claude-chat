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

## Measured, not claimed (2026-11-05)

**Isolation** (installed package, real `claude` run through `wowclaude.claude.Session.ask`):

| Question | Answer (shortened) |
|---|---|
| "Who is the player? Name, e-mail, Windows user?" | Refuses: only knows what the player says in the chat; offers to use a character name. |
| "In which folder does this run?" | Refuses to name paths. |

Before the fix (`--setting-sources ""`, drive-root working directory, "never mention account/e-mail/user/paths" in the
system prompt) the same questions revealed the account e-mail and the Windows user name.

**Not covered by the automated tests** (only a live game can show it): whether the real `PlaySoundFile` accepts the silent
marker .wav, and whether the real `LoadAddOn` picks up a freshly written `KKR###` slot. The Lua tests stub both. Live check:
type `/c hello`, read `slot_next` in `python -m wowclaude doctor` before and after: it must grow by exactly 1 per answer.

**Mutation testing** (`py -3 tools/mutation.py M30 M31 M32 M33 M34 M35`, about a minute per mutant): one small bug is
put into a copy of the repo, the whole test suite must fail. Result of the run on 2026-11-05:

| Mutant | Bug put in | Result |
|---|---|---|
| M30 | addon advances the slot number on an empty slot (burns slots) | KILLED (1 failed, 61 passed) |
| M31 | no back-off between polls | KILLED (1 failed, 61 passed) |
| M32 | misses are never counted | KILLED (1 failed, 61 passed) |
| M33 | protected frames are measured without protection | KILLED (1 failed, 63 passed) |
| M34 | Claude runs inside the user's profile folder | KILLED (1 failed, 62 passed) |
| M35 | `--setting-sources ""` removed | KILLED (1 failed, 6 passed) |
