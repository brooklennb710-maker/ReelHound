"""ReelHound whole-video repost: turn a full cleared source video into 9:16 Reels.

  python wholejob.py VIDEO.mp4                 one Reel of the whole video (up to 90 s)
  python wholejob.py VIDEO.mp4 --mode parts    a longer video split into parts of about a minute
  python wholejob.py VIDEO.mp4 --mode cap      just the first ~90 s

VIDEO is a file name in media\\raw or media\\official (never media\\_not-cleared). The Clip Maker does the
9:16 framing, Whisper captions, the AI hook and caption, and the source credit, exactly like a normal clip.
Finished Reels land in media\\edits for review. Never posts or schedules anything.

Permission: the source note (.source.json) must say own, official or yes, AND creators.csv must agree.
A creator marked no, asked or unknown in creators.csv (or missing from it) is refused.

The control panel's Editing page starts this in the background with start(); progress is kept in
clipmaker\\whole_jobs\\<video>.json.
"""
import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(HERE), str(ROOT), str(ROOT / "hunter")]
import autoclip  # noqa: E402
import brand     # noqa: E402  (credits for official media)
import reclip    # noqa: E402  (shares its render lock, ffmpeg finder and one-render-at-a-time rule)

FOLDERS = {"raw": ROOT / "media" / "raw", "phone": ROOT / "media" / "raw" / "phone-inbox",
           "official": ROOT / "media" / "official"}   # never media\_not-cleared
JOBS = HERE / "whole_jobs"
LOG = HERE / "wholejob.log"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
MODES = ("auto", "parts", "cap")
BULK_NOTE = "(yes button)"   # ~100 creators were bulk-marked yes on 2026-11-20 without a recorded reply
_durations = {}


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


# ---------- jobs ----------
def job_path(name):
    return JOBS / (Path(name).stem + ".json")


def job(name):
    try:
        with open(job_path(name), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def save_job(name, **fields):
    JOBS.mkdir(parents=True, exist_ok=True)
    data = job(name) or {}
    data.update(fields, name=name, updated=now())
    tmp = str(job_path(name)) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, job_path(name))
    return data


def busy(name):
    j = job(name)
    if not j or j.get("status") not in ("queued", "working"):
        return False
    try:
        age = time.time() - dt.datetime.fromisoformat(j["updated"]).timestamp()
    except (KeyError, ValueError):
        age = 0
    return age < 45 * 60   # a long video in 8 parts can take a while; a dead job stops blocking after this


# ---------- sources and permission ----------
def find(name):
    if not isinstance(name, str) or Path(name).name != name or not name.lower().endswith(".mp4"):
        raise ValueError("Pick a video from the list.")
    for area, folder in FOLDERS.items():
        if (folder / name).is_file():
            return area, folder / name
    raise ValueError("That video isn't in media\\raw or media\\official anymore. Refresh the page.")


def source_note(video):
    try:
        with open(video.with_suffix(".source.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def duration(video):
    key = (str(video), video.stat().st_mtime)
    if key not in _durations:
        reclip.prepare_ffmpeg()
        _durations[key] = autoclip.duration(str(video))
    return _durations[key]


def permission(area, video, src):
    """Returns (allowed, clip-maker permission, short label, warning or reason)."""
    if src is None:
        if area == "official":
            return True, "official", "Official", ""
        return False, "", "No source note", "No .source.json next to it, so who made it and who allowed it is unknown."
    note = (src.get("permission") or "").strip().lower()
    perm = {"yes": "creator-yes", "creator-yes": "creator-yes", "own": "own", "official": "official"}.get(note, "")
    if not perm:
        return False, "", note.title() or "Unknown", "The source note has no permission (yes, own or official)."
    handle, platform = (src.get("creator") or "").strip().lstrip("@"), (src.get("platform") or "").lower()
    import hunter
    creators = hunter.load_creators()
    row = None
    for key in (handle, src.get("creator_id") or ""):
        if key and not row:
            row = creators.get((platform, hunter.norm(key)))
    recorded = (row or {}).get("permission", "")
    if recorded == "no":
        return False, "", "No", f"{handle or 'This creator'} is marked no in creators.csv."
    if perm == "creator-yes":
        if recorded != "yes":
            return False, "", recorded.title() or "Not recorded", \
                f"{handle or 'This creator'} has no recorded yes in creators.csv ({recorded or 'missing'})."
        if BULK_NOTE in (row.get("notes") or "").lower() and not (row.get("contact") or "").strip():
            return True, perm, "Yes (bulk-marked)", \
                "Marked yes with the bulk Yes button on 11/20 and no contact on file. Confirm they really said yes before posting."
        return True, perm, "Yes", ""
    if perm == "own" and recorded not in ("own", ""):
        return False, "", recorded.title(), f"creators.csv says {recorded}, not your own channel."
    return True, perm, "My video" if perm == "own" else "Official", ""


def plan_text(total):
    if total <= autoclip.WHOLE_MAX:
        return "One Reel of the whole video"
    n = autoclip.parts_needed(total)
    if n > autoclip.MAX_PARTS:
        return f"Over {autoclip.MAX_PARTS} parts: first 90 s only"
    return f"about {n} parts of ~1 min, or the first 90 s"


def describe(name):
    area, video = find(name)
    src = source_note(video)
    allowed, perm, label, warning = permission(area, video, src)
    try:
        total = float((src or {}).get("duration_s") or 0)
    except (TypeError, ValueError):
        total = 0.0
    # (the hunter's recorded length above keeps a list of 100+ videos fast; ffprobe only when missing)
    if not total:
        try:
            total = duration(video)
        except Exception:
            pass
    j = job(name) or {}
    status = j.get("status", "")
    if status in ("queued", "working") and not busy(name):
        status = "failed"
    return dict(name=name, area=area, title=(src or {}).get("title") or video.stem,
                creator=(src or {}).get("credit") or (src or {}).get("creator") or "",
                url=(src or {}).get("url", ""), seconds=round(float(total or 0), 1),
                allowed=allowed, permission=label, warning=warning, confirm=label == "Yes (bulk-marked)", plan=plan_text(float(total or 0)),
                parts=autoclip.parts_needed(total) if total > autoclip.WHOLE_MAX else 1,
                job=status, job_mode=j.get("mode", ""), job_note=j.get("error") or j.get("note", ""),
                made=j.get("made", 0))


def sources():
    out = []
    for folder in FOLDERS.values():
        if folder.is_dir():
            for path in folder.glob("*.mp4"):
                if path.name.endswith(".part.mp4"):
                    continue
                try:
                    out.append(describe(path.name))
                except (ValueError, OSError):
                    continue
    out.sort(key=lambda r: r["name"], reverse=True)   # newest downloads first
    out.sort(key=lambda r: not r["allowed"])           # then cleared ones above blocked ones (stable sort)
    return out


# ---------- the render ----------
def check(name, mode, confirmed=True):
    if mode not in MODES:
        raise ValueError("Pick one Reel, split into parts, or first 90 s.")
    area, video = find(name)
    src = source_note(video)
    allowed, perm, label, reason = permission(area, video, src)
    if not allowed:
        raise ValueError(f"Can't repost this one: {reason}")
    if label == "Yes (bulk-marked)" and not confirmed:
        raise ValueError(f"{reason} Tick 'They really said yes' to go ahead.")
    total = duration(video)
    if total < 3:
        raise ValueError("Couldn't read the video's length, or it's under 3 seconds.")
    if mode == "auto" and total > autoclip.WHOLE_MAX:
        raise ValueError(f"It's {autoclip.mmss_short(total)}, over the 90 s Reel limit. "
                         f"Choose Split into parts ({autoclip.parts_needed(total)}) or First 90 s.")
    if mode == "parts" and autoclip.parts_needed(total) > autoclip.MAX_PARTS:
        raise ValueError(f"It's {autoclip.mmss_short(total)}, which would be over {autoclip.MAX_PARTS} parts. "
                         "Choose First 90 s, or let the Clip Maker pick the best moments.")
    if mode in ("parts", "cap") and total <= autoclip.WHOLE_MAX:
        mode = "auto"   # it already fits in one Reel
    src = dict(src or {}, permission=perm)
    src.setdefault("title", video.stem)
    if perm == "official" and not (src.get("credit") or "").strip():
        src["credit"] = brand.credit_for(src.get("creator"), "official")
    return video, src, mode, total


def run(name, mode, log=print):
    try:
        video, src, mode, total = check(name, mode)
        with reclip.RenderLock():
            save_job(name, status="working", mode=mode, seconds=round(total, 1))
            cfg = {}
            try:
                with open(ROOT / "hunter" / "config.json", encoding="utf-8") as f:
                    cfg = json.load(f)
            except (OSError, ValueError):
                pass

            def render(cmd):
                proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                      env=dict(os.environ, PYTHONUTF8="1"), creationflags=NO_WINDOW)
                for line in (proc.stdout + proc.stderr).splitlines():
                    if line.strip() and not line.lstrip().startswith("frame="):
                        log("   " + line.rstrip()[:300])
                return proc.returncode

            args = argparse.Namespace(hook="", preset=cfg.get("clip_preset", "viral"),
                                      no_captions=not cfg.get("captions", True),
                                      whisper_model=cfg.get("whisper_model", "small"),
                                      caption_size=cfg.get("caption_size"),
                                      credit_position=cfg.get("credit_position", "bottom-center"),
                                      credit_text=cfg.get("credit_text", ""), guide=False, guide_trim=False,
                                      run_clip=render)
            log(f"Whole video: {name} ({total:.0f} s, mode {mode}), {src.get('permission')}, credit "
                f"{src.get('credit') or 'none'}")
            autoclip.log = lambda msg: log(msg)
            made = autoclip.clip_whole(str(video), src, args, mode)
        save_job(name, status="done", made=made, finished=now(), error="",
                 note=f"{made} Reel{'s' if made != 1 else ''} in media\\edits")
        log(f"Whole video done: {made} Reel(s) from {name} in media\\edits.")
        return made
    except Exception as exc:
        save_job(name, status="failed", error=str(exc)[:400], finished=now())
        log(f"Whole video {name} failed: {exc}")
        raise


def start(name, mode="auto", confirmed=False):
    """Check the request, then render in a background process. Returns a short message for the page."""
    if busy(name):
        raise ValueError("That video is already being clipped. Its Reels show up in review when done.")
    _, _, mode, total = check(name, mode, confirmed)   # fail fast: permission, length, parts limit
    save_job(name, status="queued", mode=mode, started=now(), error="", note="", made=0)
    log_file = open(LOG, "a", encoding="utf-8")
    subprocess.Popen([sys.executable, str(Path(__file__)), name, "--mode", mode, "--quiet-start"],
                     stdout=log_file, stderr=subprocess.STDOUT, cwd=str(HERE),
                     env=dict(os.environ, PYTHONUTF8="1"), creationflags=NO_WINDOW)
    log_file.close()
    what = {"auto": "one Reel of the whole video",
            "parts": f"{autoclip.parts_needed(total)} parts",
            "cap": "the first ~90 s"}[mode]
    return (f"Clipping {what} ({autoclip.mmss_short(total)} source) with AI captions, hook and credit. "
            "It shows up in Clip review in a few minutes (longer for parts).")


def main():
    ap = argparse.ArgumentParser(description="Repost a whole cleared video as 9:16 Reels in media\\edits.")
    ap.add_argument("video", help="file name in media\\raw or media\\official")
    ap.add_argument("--mode", default="auto", choices=MODES)
    ap.add_argument("--quiet-start", action="store_true", help=argparse.SUPPRESS)
    a = ap.parse_args()

    def log(text):
        print(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}  {text}", flush=True)
    try:
        run(Path(a.video).name, a.mode, log)
    except Exception as exc:
        if not a.quiet_start:
            print(f"\n[wholejob] {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
