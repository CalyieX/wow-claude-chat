"""Command line: wowclaude setup | run | doctor"""
from __future__ import annotations

import argparse
import sys

from . import __version__, config


def _root(args):
    root = config.client_root(getattr(args, "root", None))
    if root is None:
        print("Could not find the game folder. Run again with:  wowclaude setup --root \"D:\\path\\to\\World of Warcraft\\_forever_\"")
        sys.exit(2)
    return root


def cmd_setup(args) -> int:
    from . import claude, slots
    root = _root(args)
    print(f"Game folder: {root}")
    res = slots.install(root)
    cfg = config.load()
    cfg["wow_root"] = str(root)
    config.save(cfg)
    print(f"Addon installed ({res['slots_created']} reply slots created).")
    if claude.claude_path():
        print("Claude Code found.")
    else:
        print("WARNING: the 'claude' command was not found. Install Claude Code (https://claude.com/claude-code), log in once, then run again.")
    print("\nNext steps:\n"
          "  1. Close the game completely and start it again (new addons need a full restart).\n"
          "  2. In the game: a chat tab called 'Claude' appears. Use it with the game window in windowed or borderless mode.\n"
          "  3. Start the bridge:  wowclaude run\n"
          "  4. Click the Claude tab and write a message.")
    return 0


def cmd_run(args) -> int:
    from . import bridge
    try:
        bridge.run(_root(args))
    except KeyboardInterrupt:
        print("stopped")
    return 0


def cmd_doctor(args) -> int:
    from . import claude, screen
    root = config.client_root(getattr(args, "root", None))
    print("game folder   :", root or "NOT FOUND")
    print("addon present :", bool(root and (root / "Interface" / "AddOns" / "KKMap" / "KKMap.lua").exists()))
    print("claude command:", claude.claude_path() or "NOT FOUND")
    print("game running  :", screen.game_running())
    if screen.game_running():
        from . import bridge
        st = bridge.read_state()
        if st is None:
            print("strip         : not visible (normal while idle: it shows when you type in the Claude tab; `/kkmap always` in the game keeps it visible)")
        else:
            print("strip         : OK, addon version", st.addon_version)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="wowclaude", description="Chat with Claude inside the World of Warcraft chat.")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn, help_ in (("setup", cmd_setup, "install the addon into the game folder"),
                            ("run", cmd_run, "start the bridge (keep it running while you play)"),
                            ("doctor", cmd_doctor, "check that everything is in place")):
        p = sub.add_parser(name, help=help_)
        p.add_argument("--root", help="game folder (the one containing Wow.exe), only if it is not found automatically")
        p.set_defaults(fn=fn)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
