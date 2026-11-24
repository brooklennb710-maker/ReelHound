"""ReelHound batch clip: turn a whole folder of videos into clips in one run.

    python reelhound.py batch "D:\\footage"                  best moments, 3 clips per video
    python reelhound.py batch "D:\\footage" --mode whole      one clip per video (first 90 s if longer)
    python reelhound.py batch "D:\\footage" --mode parts      longer videos split into ~1 minute parts
    python reelhound.py batch video1.mp4 video2.mp4 --count 5
    python reelhound.py batch "D:\\footage" --dry-run         list what would be clipped

Finished clips land in media\\edits with their caption drafts. Videos that were
already done are remembered in clipmaker\\batch_done.json, so re-running a big
folder only handles the new files (delete that file to start over).

Own footage is the default. A video that already has a <name>.source.json note
(the hunter and phone inbox write those) is clipped with that permission and
credit instead.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CLIPMAKER = ROOT / "clipmaker"
AUTOCLIP = CLIPMAKER / "autoclip.py"
EDITS = ROOT / "media" / "edits"
STATE = CLIPMAKER / "batch_done.json"
LOG = CLIPMAKER / "batch.log"
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}


def log(message):
    stamp = dt.datetime.now().strftime("%H:%M:%S")
    text = f"{stamp}  {message}"
    print(text, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as file:
            file.write(text + "\n")
    except OSError:
        pass


def load_state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def key(path):
    try:
        info = path.stat()
        return f"{path.resolve()}|{info.st_size}|{int(info.st_mtime)}"
    except OSError:
        return str(path)


def collect(targets, recursive):
    files, missing = [], []
    for target in targets:
        path = Path(target).expanduser()
        if path.is_dir():
            pattern = "**/*" if recursive else "*"
            files.extend(p for p in sorted(path.glob(pattern)) if p.suffix.lower() in VIDEO_EXT and p.is_file())
        elif path.is_file() and path.suffix.lower() in VIDEO_EXT:
            files.append(path)
        else:
            missing.append(str(path))
    return files, missing


def main(argv=None):
    parser = argparse.ArgumentParser(description="Clip every video in a folder.",
                                     formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    parser.add_argument("targets", nargs="*", help="video files or folders (default: media\\raw)")
    parser.add_argument("--mode", choices=("moments", "whole", "parts", "cap"), default="moments")
    parser.add_argument("--count", type=int, default=3, help="clips per video in moments mode (default 3)")
    parser.add_argument("--length", type=float, default=40.0, help="seconds per clip (default 40)")
    parser.add_argument("--preset", default="viral", choices=("viral", "clean", "news"))
    parser.add_argument("--no-captions", action="store_true")
    parser.add_argument("--recursive", action="store_true", help="include subfolders")
    parser.add_argument("--limit", type=int, default=0, help="stop after N videos")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--redo", action="store_true", help="clip videos that were already done")
    args = parser.parse_args(argv)

    targets = args.targets or [str(ROOT / "media" / "raw")]
    files, missing = collect(targets, args.recursive)
    for path in missing:
        log(f"Not a video or folder: {path}")
    if not files:
        log("No videos found. Drag a folder path after 'batch', or put videos in media\\raw.")
        return 2

    state = load_state()
    pending = [p for p in files if args.redo or key(p) not in state]
    done_count = len(files) - len(pending)
    log(f"{len(files)} video(s) found, {done_count} already clipped, {len(pending)} to do"
        + (" (dry run)" if args.dry_run else ""))

    if args.dry_run:
        for path in pending:
            side = "own" if not path.with_suffix(".source.json").exists() else "from its .source.json"
            log(f"  would clip {path.name} ({side})")
        return 0

    EDITS.mkdir(parents=True, exist_ok=True)
    made = failed = 0
    for index, path in enumerate(pending, 1):
        if args.limit and index > args.limit:
            log(f"Stopping at the --limit of {args.limit} video(s).")
            break
        log(f"[{index}/{len(pending)}] {path.name}")
        command = [sys.executable, str(AUTOCLIP), str(path)]
        if not path.with_suffix(".source.json").exists():
            command.append("--own")
        command += ["--count", str(args.count), "--length", str(args.length), "--preset", args.preset]
        if args.no_captions:
            command.append("--no-captions")
        if args.mode in ("whole", "parts", "cap"):
            command += ["--whole", "auto" if args.mode == "whole" else args.mode]
        environment = dict(os.environ, PYTHONUTF8="1")
        try:
            result = subprocess.run(command, cwd=str(CLIPMAKER), env=environment)
        except OSError as error:
            log(f"  failed to start: {error}")
            failed += 1
            continue
        if result.returncode == 0:
            made += 1
            state[key(path)] = f"{dt.datetime.now():%Y-%m-%d %H:%M}"
            save_state(state)
        else:
            failed += 1
            log(f"  skipped after an error (exit {result.returncode}); see the output above")

    log(f"Done: {made} video(s) clipped into {EDITS}, {failed} failed.")
    if made:
        log("Watch them, delete the weak ones, move the keepers to media\\ready.")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
