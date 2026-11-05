"""Command line: wowclaude setup | run | doctor | overlay"""
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
    ok, msg = claude.check_login()
    print(("OK: " if ok else "WARNING: ") + msg)
    print("\nNext steps:\n"
          "  1. Close the game completely and start it again (new addons need a full restart).\n"
          "  2. In the game: a chat tab called 'Claude' appears. Use it with the game window in windowed or borderless mode.\n"
          "  3. Start the bridge:  wowclaude run\n"
          "  4. Click the Claude tab and write a message.\n"
          "  In the game: /wac opens the menu (AI Setup, browser window).")
    return 0


def cmd_uninstall(args) -> int:
    from . import slots
    root = _root(args)
    res = slots.uninstall(root)
    print(f"Removed {res['folders_removed']} addon folders from {root} ({res['character_files_cleaned']} character files cleaned).")
    print("Your settings in ~/.wowclaude are kept; delete that folder too if you want everything gone.")
    return 0


def cmd_run(args) -> int:
    from . import bridge, claude
    ok, msg = claude.check_login()
    if not ok:
        print("No AI set up yet (" + msg + "). The bridge starts anyway: /wac -> AI Setup and the browser work already.")
    try:
        bridge.run(_root(args))
    except KeyboardInterrupt:
        print("stopped")
    return 0


def _scale_info() -> str:
    import ctypes
    if sys.platform != "win32":
        return "n/a"
    try:
        dpi = ctypes.windll.user32.GetDpiForSystem()
        return f"{round(dpi / 96 * 100)} % ({dpi} dpi)"
    except (OSError, AttributeError):
        return "unknown"


def cmd_doctor(args) -> int:
    from . import claude, decode, screen
    root = config.client_root(getattr(args, "root", None))
    print("game folder   :", root or "NOT FOUND (run `wowclaude setup --root \"...\\_forever_\"`)")
    if root:
        flavour = next((f for f in config.FLAVOURS if root.name == f), root.name)
        print("game flavour  :", flavour)
        print("addon present :", bool((root / "Interface" / "AddOns" / "KKMap" / "KKMap.lua").exists()))
    print("display scale :", _scale_info(), "(the program makes itself DPI-aware, so any scale should work)")
    from . import overlay
    print("browser       :", overlay.find_browser() or "NOT FOUND (only needed for the browser window and AI setup page)")
    try:
        import tkinter  # noqa: F401
        print("tkinter       : OK")
    except ImportError:
        print("tkinter       : MISSING (needed for the browser window; reinstall Python with tcl/tk)")
    print("claude command:", claude.claude_path() or "NOT FOUND")
    if getattr(args, "deep", False):
        ok, msg = claude.check_login()  # a real question to the AI: can take a minute
        print("AI backend    :", "OK - " + msg if ok else "PROBLEM - " + msg)
    else:
        print("AI backend    : not asked (add --deep to send one test question)")
    running = screen.game_running()
    print("game running  :", running)
    if running:
        from . import bridge
        img = screen.grab_strip_area()
        st = decode.decode(img) if img is not None else None
        if st is None:
            print("strip         : not visible. It only shows while you type in the Claude tab. In the game type "
                  "`/strip always`, run this again, and if it is still not visible check that the game is in windowed "
                  "or borderless mode and the addon is enabled.")
        else:
            print("strip         : OK, addon version", st.addon_version, "- next reply slot", st.slot_next)
            sample = config.HOME / "strip-sample.png"
            img.save(sample)  # attach this to a bug report: it shows exactly what the program sees
            print("strip sample  :", sample)
    return 0


def _dpi_aware() -> None:
    """Without this, Windows display scaling (125 %, 150 %) shifts screen coordinates: the 1-pixel strip is read blurred."""
    if sys.platform != "win32":
        return
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (OSError, AttributeError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (OSError, AttributeError):
            pass


def main(argv=None) -> int:
    _dpi_aware()
    ap = argparse.ArgumentParser(prog="wowclaude", description="Chat with Claude inside the World of Warcraft chat.")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn, help_ in (("setup", cmd_setup, "install the addon into the game folder"),
                            ("run", cmd_run, "start the bridge (keep it running while you play)"),
                            ("doctor", cmd_doctor, "check that everything is in place"),
                            ("uninstall", cmd_uninstall, "remove the addon and all reply slots from the game folder")):
        p = sub.add_parser(name, help=help_)
        p.add_argument("--root", help="game folder (the one containing Wow.exe), only if it is not found automatically")
        if name == "doctor":
            p.add_argument("--deep", action="store_true", help="also send one real test question to the AI (slow)")
        p.set_defaults(fn=fn)
    pc = sub.add_parser("config", help="open the AI setup page (backend, model, key, persona) in the WoW browser window")
    pc.set_defaults(fn=lambda a: __import__("wowclaude.setup_ui", fromlist=["serve"]).serve())
    po = sub.add_parser("overlay", help="show a web page (YouTube, Netflix, ...) in an always-on-top window over the game")
    po.add_argument("url", nargs="?", default=None, help="page to open (default: Google)")
    po.add_argument("--corner", choices=["tl", "tr", "bl", "br"], default=None, help="start corner (default: remembered position)")
    po.add_argument("--size", default=None, help="WIDTHxHEIGHT (default: remembered size)")
    po.add_argument("--opacity", type=int, default=100, help="10-100")
    po.add_argument("--click-through", action="store_true", help="mouse clicks go to the game")
    po.set_defaults(fn=lambda a: __import__("wowclaude.overlay", fromlist=["run"]).run(
        a.url, a.corner, a.size, a.opacity, a.click_through))
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
