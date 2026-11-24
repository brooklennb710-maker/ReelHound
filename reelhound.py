#!/usr/bin/env python
"""ReelHound by BridgesTech - find it, clip it, post it.

One command for everything:

    python reelhound.py init        first-run setup (handle, niche, watermark, search terms)
    python reelhound.py doctor      check this PC can run everything
    python reelhound.py panel       open the control panel (start here for daily use)
    python reelhound.py hunt        scan for new videos (add --loop to keep scanning)
    python reelhound.py clip VIDEO  make one vertical clip
    python reelhound.py auto VIDEO  find the best moments in a video and clip them
    python reelhound.py batch DIR   clip every video in a folder
    python reelhound.py pack        bundle ready clips + captions for uploading
    python reelhound.py review      score media/edits with a local vision model
    python reelhound.py inbox       run the phone inbox server
    python reelhound.py selftest    prove the install works by rendering a test clip

Each command passes extra flags straight through, so `python reelhound.py clip --help`
shows the clip maker's own options. The same tools also run as separate scripts.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

__version__ = "1.0.0"
ROOT = Path(__file__).resolve().parent

# command -> (script, one-line help). Extra arguments are passed through untouched.
SCRIPTS = {
    "panel": ("control-panel/panel.py", "control panel in your browser"),
    "hunt": ("hunter/hunter.py", "scan for new videos to clip"),
    "clip": ("clipmaker/clipmaker.py", "make one vertical clip"),
    "auto": ("clipmaker/autoclip.py", "find the best moments and clip them"),
    "batch": ("batch_clip.py", "clip a whole folder of videos"),
    "pack": ("pack.py", "bundle ready clips for uploading"),
    "review": ("reviewer/review_edits.py", "score clips with a local vision model"),
    "inbox": ("inbox/inbox.py", "phone inbox server"),
    "init": ("setup_wizard.py", "first-run setup"),
    "doctor": ("doctor.py", "check the install"),
    "selftest": ("selftest.py", "render a test clip end to end"),
}


def run(script, args):
    path = ROOT / script
    if not path.exists():
        print(f"[reelhound] {path.relative_to(ROOT)} is missing. Re-download the repo.")
        return 1
    environment = dict(os.environ, PYTHONUTF8="1")
    try:
        return subprocess.call([sys.executable, str(path), *args], cwd=str(path.parent), env=environment)
    except KeyboardInterrupt:
        print("\n[reelhound] Stopped.")
        return 130


def banner():
    import brand

    print(f"\n {brand.label()}  v{__version__}")
    print(f" {brand.tagline()}")
    if not brand.configured():
        print(" Not set up yet: run  python reelhound.py init\n")
    else:
        print(f" Channel: {brand.channel()}  ({brand.handle() or 'no handle'})\n")


def help_text():
    width = max(len(name) for name in SCRIPTS)
    rows = "\n".join(f"  {name.ljust(width)}  {help_text}"
                     for name, (_, help_text) in SCRIPTS.items())
    return (f"usage: python reelhound.py <command> [options]\n\n"
            f"commands:\n{rows}\n\n"
            "Every option after the command is passed straight through, so\n"
            "  python reelhound.py clip --help\n"
            "shows the clip maker's own flags. Run without a command for a summary.")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        banner()
        print(help_text())
        return 0
    if argv[0] in ("-V", "--version", "version"):
        print(f"ReelHound {__version__}")
        return 0

    command, rest = argv[0], argv[1:]
    entry = SCRIPTS.get(command)
    if entry is None:
        print(f"[reelhound] Unknown command '{command}'.\n")
        print(help_text())
        return 2
    script, _ = entry
    if command in ("panel", "hunt", "inbox", "init", "doctor", "selftest", "pack", "batch", "review"):
        banner()
    return run(script, rest)


if __name__ == "__main__":
    sys.exit(main())
