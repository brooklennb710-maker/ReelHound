"""ReelHound first-run setup.

Answers a handful of questions, then writes brand.json (your handle, niche,
watermark, hashtags, destinations) and hunter/config.json (what to search for),
and copies the sample data files so the panel has something to open.

    python reelhound.py init
    python setup_wizard.py             (same thing)
    python setup_wizard.py --defaults  write the defaults without asking anything
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import brand  # noqa: E402

HUNTER = ROOT / "hunter"
COPIES = [
    ("hunter/config.example.json", "hunter/config.json"),
    ("hunter/creators.sample.csv", "hunter/creators.csv"),
    ("hunter/finds.sample.csv", "hunter/finds.csv"),
    ("control-panel/schedule.example.json", "control-panel/schedule.json"),
    ("scoreboard.sample.csv", "scoreboard.csv"),
]


def ask(prompt, default=""):
    suffix = f" [{default}]" if default not in ("", None) else ""
    try:
        answer = input(f"{prompt}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return default
    return answer or default


def ask_list(prompt, default):
    answer = ask(prompt + " (comma separated)", ", ".join(default))
    return [x.strip() for x in answer.split(",") if x.strip()]


def system_zone():
    import datetime as dt

    now = dt.datetime.now().astimezone()
    return now.tzname() or "local"


def copy_samples(force=False):
    made = []
    for source, target in COPIES:
        src, dst = ROOT / source, ROOT / target
        if dst.exists() and not force:
            continue
        if not src.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        made.append(target)
    for folder in ("media/raw", "media/edits", "media/ready", "media/official",
                   "media/raw/phone-inbox", "media/_not-cleared", "control-panel"):
        (ROOT / folder).mkdir(parents=True, exist_ok=True)
    return made


def read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return dict(default)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def setup(defaults=False):
    current = brand.load(refresh=True)
    print("\n" + "=" * 60)
    print(f" {brand.label()} - first-run setup")
    print("=" * 60)
    print(" Answer these once. Everything can be changed later in brand.json")
    print(" and hunter/config.json (or on the panel's Hunter page).\n")

    if defaults:
        answers = {}
    else:
        answers = dict(
            handle=ask("Your handle on the platforms (e.g. @yourpage)", current.get("handle") or ""),
            channel=ask("Your page/channel name (used in permission messages)", current.get("channel") or ""),
            niche=ask("What is your niche, in a few words", current.get("niche") or "short-form clips"),
            watermark=ask("Watermark burned into clips (blank = none)",
                          current.get("watermark") or current.get("handle") or ""),
            hashtags=ask("Default caption hashtags", current.get("caption_hashtags") or "#reels #shorts"),
            zone=ask(f"Time zone for scheduling (blank = this PC's: {system_zone()})", current.get("timezone") or ""),
        )
        wanted = ask_list("Where do you post?", list(brand.destinations()))

    if defaults:
        data = {"handle": "", "channel": "", "watermark": ""}
        wanted = list(brand.destinations())
    else:
        data = {k: v for k, v in answers.items() if k != "zone" and v not in ("", None)}
        data["destinations"] = wanted
        data["timezone"] = answers.get("zone", "")
    saved = brand.save(data) if data else brand.load(refresh=True)
    print(f"  brand.json: {saved['app']} · handle {saved.get('handle') or '(none yet)'}")

    config_path = HUNTER / "config.json"
    config = read_json(config_path, {})
    fresh = not config_path.exists()
    if fresh:
        example = read_json(HUNTER / "config.example.json", {})
        config.update(example)
    if not defaults and (fresh or ask("Update the search keywords in hunter/config.json? (y/N)", "n").lower().startswith("y")):
        config["keywords"] = ask_list("Search terms (what should the hunter look for?)",
                                      config.get("keywords") or ["game clips"])
        config["subreddits"] = ask_list("Subreddits to watch (names only)",
                                        config.get("subreddits") or ["gaming"])
        tags = ask_list("Instagram hashtags to watch", config.get("instagram", {}).get("hashtags") or ["gaming"])
        config.setdefault("instagram", {})["hashtags"] = [t.lstrip("#") for t in tags]
    write_json(config_path, config)
    print("  hunter/config.json written")

    made = copy_samples()
    print(f"  sample data files: {len(made)} created")

    print("\n" + "-" * 60)
    print(" Next steps")
    print("-" * 60)
    print("  1. python reelhound.py doctor        check everything is ready")
    print("  2. python reelhound.py panel         open the control panel")
    print("  3. Add creators to hunter\\creators.csv (or the panel's Creators page)")
    print("  4. Optional: Ollama for AI hooks and clip scoring (see docs/SETUP.md)")
    print("  Docs: docs/SETUP.md, docs/USER-GUIDE.md, docs/PLAYBOOK.md\n")
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    defaults = "--defaults" in argv or "-y" in argv
    return setup(defaults=defaults)


if __name__ == "__main__":
    sys.exit(main())
