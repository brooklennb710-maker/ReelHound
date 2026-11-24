"""ReelHound publish pack: one folder (and zip) with the clips you are about to
post, their captions and a manifest you can follow while uploading.

    python reelhound.py pack                    media\\ready -> publish_pack\\ + zip
    python reelhound.py pack --area edits       pack clips that are still in review
    python reelhound.py pack --limit 5          just the newest 5
    python reelhound.py pack --out D:\\drop      somewhere else
    python reelhound.py pack --no-zip           folder only

The manifest.csv columns are: file, caption, credit, preset, seconds, permission,
destinations, slot_local, slot_utc, source. Files are copied, never moved, so
media\\ready stays your archive.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import json
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import brand  # noqa: E402

AREAS = {"ready": ROOT / "media" / "ready", "edits": ROOT / "media" / "edits"}
SCHEDULE = ROOT / "control-panel" / "schedule.json"
CAPTION_BREAK = "\n\n---\n"


def sidecar_data(path):
    """The caption body and the 'key: value' metadata block from the .txt sidecar."""
    side = path.with_suffix(".txt")
    text = side.read_text(encoding="utf-8-sig", errors="replace") if side.exists() else ""
    caption, _, meta = text.partition(CAPTION_BREAK)
    info = {}
    for line in meta.splitlines():
        key, sep, value = line.partition(":")
        if sep:
            info[key.strip().lower()] = value.strip()
    return caption.strip(), info


def seconds_of(path, info):
    span = info.get("range", "")
    if " to " in span:
        try:
            start, end = (float(x) for x in span.split(" to ", 1))
            return round(end - start, 1)
        except ValueError:
            pass
    return ""


def schedule_index():
    try:
        data = json.loads(SCHEDULE.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    out = {}
    for item in data.get("items", []):
        try:
            when = dt.datetime.fromisoformat(item["utc"])
        except (KeyError, ValueError):
            continue
        out[item.get("name")] = dict(destinations=", ".join(item.get("channels", [])),
                                     slot_local=brand.local(when).strftime("%a %b %d %I:%M %p %Z"),
                                     slot_utc=when.astimezone(dt.UTC).strftime("%Y-%m-%d %H:%M UTC"))
    return out


def newest_first(folder):
    return sorted((p for p in folder.glob("*.mp4")
                   if p.is_file() and not p.name.endswith(".part.mp4")),
                  key=lambda p: p.name, reverse=True)


def build(area="ready", out=None, limit=0, make_zip=True, quiet=False):
    folder = AREAS.get(area)
    if folder is None or not folder.is_dir():
        raise SystemExit(f"No {area} folder at {folder}. Render some clips first.")

    clips = newest_first(folder)
    if limit:
        clips = clips[:limit]
    if not clips:
        raise SystemExit(f"{area} is empty. Nothing to pack yet.")

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    target = Path(out) if out else ROOT / "publish_pack"
    if target.suffix.lower() == ".zip":
        make_zip, target = True, target.with_suffix("")
    if target.exists() and any(target.iterdir()):
        target = target.with_name(f"{target.name}-{stamp}")
    clips_dir, caps_dir = target / "clips", target / "captions"
    clips_dir.mkdir(parents=True, exist_ok=True)
    caps_dir.mkdir(parents=True, exist_ok=True)

    queue = schedule_index()
    rows = []
    for path in clips:
        caption, info = sidecar_data(path)
        plan = queue.get(path.name, {})
        shutil.copy2(path, clips_dir / path.name)
        for suffix in (".txt", ".srt"):
            side = path.with_suffix(suffix)
            if side.exists():
                shutil.copy2(side, caps_dir / side.name)
        rows.append({
            "file": path.name,
            "caption": caption,
            "credit": info.get("credit", "").lstrip("@"),
            "preset": info.get("preset", ""),
            "seconds": seconds_of(path, info),
            "permission": info.get("permission", ""),
            "destinations": plan.get("destinations") or ", ".join(brand.destinations()),
            "slot_local": plan.get("slot_local", "not scheduled"),
            "slot_utc": plan.get("slot_utc", ""),
            "source": info.get("source", ""),
        })

    with open(target / "manifest.csv", "w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    (target / "README.txt").write_text(
        f"{brand.label()} - publish pack\n"
        f"Built {dt.datetime.now():%Y-%m-%d %H:%M}\n\n"
        f"{len(rows)} clip(s) from media\\{area}.\n\n"
        "clips\\      the videos, ready to upload\n"
        "captions\\   caption drafts (.txt) and caption files (.srt) where the clip had speech\n"
        "manifest.csv  caption, credit, destination and scheduled time for every clip\n\n"
        "Upload the videos with whatever scheduler you use, paste each caption from the\n"
        "manifest, credit the creator as shown, and post at the listed time.\n",
        encoding="utf-8")

    (target / "index.html").write_text(preview(rows, area), encoding="utf-8")

    archive = ""
    if make_zip:
        archive = str(target.with_suffix(".zip"))
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
            for path in sorted(target.rglob("*")):
                if path.is_file():
                    bundle.write(path, path.relative_to(target))
    if not quiet:
        print(f"[pack] {len(rows)} clip(s) -> {target}")
        if archive:
            print(f"[pack] zip: {archive}")
        print(f"[pack] manifest: {target / 'manifest.csv'}")
    return dict(folder=str(target), zip=archive, count=len(rows), rows=rows)


def preview(rows, area):
    cards = []
    for row in rows:
        caption = html.escape(row["caption"] or "(no caption draft)")
        cards.append(
            f"<article><video src='clips/{html.escape(row['file'])}' controls preload='metadata'></video>"
            f"<h3>{html.escape(row['file'])}</h3>"
            f"<p class='meta'>{html.escape(str(row['seconds']))}s - {html.escape(row['preset'])}"
            f" - {html.escape(row['destinations'])} - {html.escape(row['slot_local'])}</p>"
            f"<pre>{caption}</pre></article>")
    return ("<!doctype html><meta charset='utf-8'><title>Publish pack</title>"
            "<style>body{font:15px system-ui;background:#141414;color:#eee;margin:24px}"
            "article{background:#1e1e1e;border-radius:12px;padding:14px;margin:0 0 18px}"
            "video{width:220px;border-radius:8px;background:#000}h3{font-size:15px;margin:10px 0 4px}"
            ".meta{color:#999;font-size:13px}pre{white-space:pre-wrap;color:#ccc;font-size:13px}"
            "code{color:#f0b429}</style>"
            f"<h1>{html.escape(brand.label())} - publish pack ({len(rows)} clip(s) from media/{area})</h1>"
            "<p class='meta'>Watch each clip, copy its caption, then upload and schedule it.</p>"
            + "".join(cards))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Bundle ready clips, captions and a manifest.")
    parser.add_argument("--area", choices=tuple(AREAS), default="ready")
    parser.add_argument("--out", default="", help="output folder or .zip (default: publish_pack)")
    parser.add_argument("--limit", type=int, default=0, help="only the newest N clips")
    parser.add_argument("--no-zip", action="store_true")
    args = parser.parse_args(argv)
    build(area=args.area, out=args.out or None, limit=args.limit, make_zip=not args.no_zip)
    return 0


if __name__ == "__main__":
    sys.exit(main())
