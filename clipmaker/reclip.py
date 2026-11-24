"""ReelHound re-clip: widen a finished Reel and cut it again from the original video.

For a clip in media\\edits that starts too late or gets cut off at the end:

  python reclip.py CLIP.mp4 --earlier 5        start 5 s earlier
  python reclip.py CLIP.mp4 --later 8          keep 8 s more at the end
  python reclip.py CLIP.mp4 --earlier 3 --later 5

It reads the clip's caption sidecar (source video, range, permission, credit, preset), finds the source in
media\\raw or media\\official, and runs the Clip Maker again on the wider window, so Whisper captions, the AI
hook and caption, the 9:16 framing, the credit and the how-to trim are all redone for the new cut.
The new Reel lands in media\\edits for review. The old one moves to media\\edits\\_old-reclip (restorable).
Never posts or schedules anything.

The phone inbox and the panel's Clip review start this in the background with start(); each job's
progress is kept in clipmaker\\reclip_jobs\\<clip>.json.
"""
import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
MEDIA = ROOT / "media"
EDITS = MEDIA / "edits"
OLD = EDITS / "_old-reclip"
STAGE = EDITS / "_reclip-tmp"
JOBS = HERE / "reclip_jobs"
SOURCES = [MEDIA / "raw", MEDIA / "official"]   # never media\_not-cleared: that footage has no permission
CLIPMAKER = HERE / "clipmaker.py"
MAX_LEN = 90.0      # playbook section 6: 15-60 s normal, up to about 90 s for a guide, chase or story
MAX_STEP = 30.0     # one widening step at a time
BREAK = "\n\n---\n"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def safe_name(name):
    if not isinstance(name, str) or Path(name).name != name or not name.lower().endswith(".mp4") \
            or name.endswith(".part.mp4"):
        raise ValueError("Pick a clip from the review list.")
    return name


# ---------- job records (one small file per clip, so the panel and the inbox never fight over one file) ----------
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
    # A job whose process died (PC restarted) shouldn't block the clip forever.
    try:
        age = time.time() - dt.datetime.fromisoformat(j["updated"]).timestamp()
    except (KeyError, ValueError):
        age = 0
    return age < 20 * 60


def resolve(name):
    """Follow finished re-clips: returns (current clip name, the job that is running on it, or None)."""
    for _ in range(10):
        j = job(name)
        if not j:
            return name, None
        if j.get("status") == "done" and j.get("new"):
            name = j["new"]
            continue
        return name, (j if j.get("status") in ("queued", "working", "failed") else None)
    return name, None


def made_from(name):
    """The finished job that produced this clip, if it is a re-cut."""
    for path in JOBS.glob("*.json") if JOBS.exists() else []:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        if data.get("status") == "done" and data.get("new") == name:
            return data
    return None


def describe(earlier, later):
    bits = []
    if earlier:
        bits.append(f"starts {earlier:g} s earlier")
    if later:
        bits.append(f"ends {later:g} s later")
    return " and ".join(bits) or "same range"


# ---------- reading the old clip ----------
def read_sidecar(clip):
    side = clip.with_suffix(".txt")
    if not side.exists():
        raise ValueError("This clip has no caption file, so its source and timestamps are unknown. "
                         "Re-cut it by hand with make_clip.bat.")
    text = side.read_text(encoding="utf-8-sig", errors="replace")
    caption, _, meta = text.partition(BREAK)
    info = {}
    for line in meta.splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip().lower() in ("source", "range", "permission", "credit", "preset", "kept"):
            info.setdefault(key.strip().lower(), value.strip())
    m = re.match(r"\s*([\d.]+)\s+to\s+([\d.]+)", info.get("range", ""))
    if not info.get("source") or not m:
        raise ValueError("This clip's caption file doesn't say which video and timestamps it came from "
                         "(made before that was recorded). Re-cut it by hand with make_clip.bat.")
    info["start"], info["end"] = float(m.group(1)), float(m.group(2))
    info["guide"] = "\nguide trim:" in "\n" + meta
    info["hook"] = (caption.strip().splitlines() or [""])[0].strip()
    info["extra"] = [l for l in meta.splitlines() if l.startswith(("Phone inbox source:", "Permission:"))]
    return info


def find_source(basename):
    for folder in SOURCES:
        direct = folder / basename
        if direct.is_file():
            return direct
        for hit in folder.rglob(basename):
            if hit.is_file():
                return hit
    raise ValueError(f"The original video ({basename}) isn't in media\\raw or media\\official anymore, "
                     "so it can't be re-cut. Download it again first.")


def source_info(video):
    try:
        with open(video.with_suffix(".source.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def still_allowed(src, permission):
    """Re-check creators.csv: a creator who has since said no can't be re-cut."""
    if permission not in ("own", "official", "creator-yes"):
        raise ValueError(f"This clip's permission is '{permission or 'missing'}', so it can't be re-cut.")
    handle, platform = (src.get("creator") or "").strip().lstrip("@"), (src.get("platform") or "").lower()
    if permission != "creator-yes" or not handle or not platform:
        return
    try:
        sys.path.insert(0, str(ROOT / "hunter"))
        import hunter
        perm = (hunter.load_creators().get((platform, hunter.norm(handle))) or {}).get("permission", "")
    except Exception:
        return
    if perm == "no":
        raise ValueError(f"@{handle} is marked 'no' in creators.csv now, so this clip can't be re-cut.")


def duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True, creationflags=NO_WINDOW)
    try:
        return float(r.stdout.strip())
    except ValueError:
        raise ValueError("Couldn't read the original video's length.")


def prepare_ffmpeg():
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        return
    profile = Path(os.environ.get("USERPROFILE", ""))
    candidates = [profile / "AppData/Local/Microsoft/WinGet/Links"]
    candidates += [p.parent for p in (profile / "AppData/Local/Microsoft/WinGet/Packages").glob("*FFmpeg*/*/bin/ffmpeg.exe")]
    for folder in candidates:
        if (folder / "ffmpeg.exe").is_file() and (folder / "ffprobe.exe").is_file():
            os.environ["PATH"] = str(folder) + os.pathsep + os.environ["PATH"]
            return


def plan(name, earlier, later):
    """Check everything that can be checked before starting. Returns the job settings or raises ValueError."""
    name = safe_name(name)
    clip = EDITS / name
    if not clip.is_file():
        raise ValueError("That clip isn't in media\\edits anymore. Refresh the page.")
    earlier, later = float(earlier or 0), float(later or 0)
    if earlier < 0 or later < 0 or earlier > MAX_STEP or later > MAX_STEP:
        raise ValueError(f"Pick between 1 and {MAX_STEP:.0f} seconds.")
    if not earlier and not later:
        raise ValueError("Choose Start earlier or Extend end.")
    info = read_sidecar(clip)
    video = find_source(info["source"])
    src = source_info(video)
    still_allowed(src, info.get("permission", ""))
    prepare_ffmpeg()
    total = duration(video)
    start = max(0.0, info["start"] - earlier)
    end = min(total, info["end"] + later)
    if earlier and not later and start >= info["start"] - 0.05:
        raise ValueError("This clip already starts at the very beginning of the original video.")
    if later and not earlier and end <= info["end"] + 0.05:
        raise ValueError("This clip already runs to the very end of the original video.")
    if end - start > MAX_LEN + 0.01:
        raise ValueError(f"That would make it {end - start:.0f} s, over the {MAX_LEN:.0f} s Reel limit. "
                         f"It's {info['end'] - info['start']:.0f} s now, so pick a smaller amount.")
    return dict(clip=clip, info=info, video=video, src=src, start=start, end=end, earlier=earlier, later=later)


# ---------- the re-cut ----------
class RenderLock:
    """One re-cut renders at a time (Whisper and FFmpeg are heavy); others wait their turn."""
    def __enter__(self):
        JOBS.mkdir(parents=True, exist_ok=True)
        self.f = open(JOBS / ".render.lock", "a+")
        import msvcrt
        while True:
            try:
                self.f.seek(0)
                msvcrt.locking(self.f.fileno(), msvcrt.LK_NBLCK, 1)
                return self
            except OSError:
                time.sleep(2)

    def __exit__(self, *_):
        import msvcrt
        try:
            self.f.seek(0)
            msvcrt.locking(self.f.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        self.f.close()


def move_aside(path, folder):
    """Move a clip and its sidecar into folder; retries while the file is open in a player."""
    folder.mkdir(parents=True, exist_ok=True)
    for attempt in range(15):
        try:
            side = path.with_suffix(".txt")
            if side.exists():
                side.replace(folder / side.name)
            path.replace(folder / path.name)
            return True
        except OSError:
            time.sleep(2)
    return False


def run(name, earlier, later, log=print):
    save_job(name, status="queued", earlier=earlier, later=later, started=now(), error="", new="")
    try:
        p = plan(name, earlier, later)
        info, src = p["info"], p["src"]
        with RenderLock():
            save_job(name, status="working", start=round(p["start"], 2), end=round(p["end"], 2))
            cfg = {}
            try:
                with open(ROOT / "hunter" / "config.json", encoding="utf-8") as f:
                    cfg = json.load(f)
            except (OSError, ValueError):
                pass
            preset = info.get("preset") or cfg.get("clip_preset", "viral")
            title = src.get("title", "")
            log(f"Re-clipping {name}: {describe(earlier, later)} -> {p['start']:.2f} to {p['end']:.2f} "
                f"({p['end'] - p['start']:.1f} s) from {p['video'].name}")
            stage = STAGE / Path(name).stem
            shutil.rmtree(stage, ignore_errors=True)
            stage.mkdir(parents=True, exist_ok=True)
            cmd = [sys.executable, str(CLIPMAKER), str(p["video"]), "--start", f"{p['start']:.2f}",
                   "--end", f"{p['end']:.2f}", "--permission", info["permission"], "--preset", preset,
                   "--out", str(stage), "--whisper-model", str(cfg.get("whisper_model", "small")),
                   "--credit-position", cfg.get("credit_position", "bottom-center")]
            if preset == "news" and info["hook"]:
                cmd += ["--hook", info["hook"], "--title", info["hook"]]
            else:
                cmd += ["--auto-hook", "--source-title", title or info["hook"]]
            part = re.search(r"\(PART (\d+/\d+)\)", info["hook"], re.I)
            if part:
                cmd += ["--part", part.group(1)]
            if info.get("credit"):
                cmd += ["--credit", info["credit"]]
            if cfg.get("caption_size"):
                cmd += ["--caption-size", str(cfg["caption_size"])]
            if not cfg.get("captions", True):
                cmd.append("--no-captions")
            if info["guide"]:  # the old cut had the how-to trim, so the new one gets it too
                cmd.append("--guide")
            proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                  env=dict(os.environ, PYTHONUTF8="1"), creationflags=NO_WINDOW)
            for line in (proc.stdout + proc.stderr).splitlines():
                if line.strip() and not line.lstrip().startswith("frame="):
                    log("   " + line.rstrip()[:300])
            made = sorted(stage.glob("*.mp4"))
            if proc.returncode != 0 or not made:
                tail = [l for l in (proc.stdout + proc.stderr).splitlines() if l.startswith("[clipmaker]")]
                raise RuntimeError("Clip Maker failed" + (": " + tail[-1].replace("[clipmaker] ", "") if tail else "."))
            new = made[0]
            side = new.with_suffix(".txt")
            if side.exists():
                with open(side, "a", encoding="utf-8") as f:
                    f.write(f"reclipped from: {name} ({describe(earlier, later)}; was {info['start']:.2f} to "
                            f"{info['end']:.2f})\n" + "".join(l + "\n" for l in info["extra"]))
            for f in (side, new):
                if f.exists():
                    f.replace(EDITS / f.name)
            shutil.rmtree(stage, ignore_errors=True)
        old_note = ""
        if (EDITS / name).is_file():
            if not move_aside(EDITS / name, OLD):
                old_note = " The old version is still in media\\edits (it was open in a player)."
        else:
            old_note = " The old version had already been moved out of review."
        save_job(name, status="done", new=new.name, finished=now(), note=old_note.strip())
        log(f"Re-clip done: {new.name}.{old_note} Old version: media\\edits\\_old-reclip\\{name}")
        return new.name
    except Exception as exc:
        save_job(name, status="failed", error=str(exc)[:400], finished=now())
        log(f"Re-clip of {name} failed: {exc}")
        shutil.rmtree(STAGE / Path(name).stem, ignore_errors=True)
        raise


def start(name, earlier=0, later=0):
    """Check the request, then re-cut in a background process. Returns a short message for the page."""
    name = safe_name(name)
    if busy(name):
        raise ValueError("That clip is already being re-cut. It shows up in review when it's done.")
    p = plan(name, earlier, later)   # fail fast with a clear message (no source, too long, permission)
    save_job(name, status="queued", earlier=p["earlier"], later=p["later"], started=now(), error="", new="")
    log_file = open(HERE / "reclip.log", "a", encoding="utf-8")
    subprocess.Popen([sys.executable, str(Path(__file__)), name, "--earlier", str(p["earlier"]),
                      "--later", str(p["later"]), "--quiet-start"],
                     stdout=log_file, stderr=subprocess.STDOUT, cwd=str(HERE),
                     env=dict(os.environ, PYTHONUTF8="1"), creationflags=NO_WINDOW)
    log_file.close()
    return (f"Re-cutting it so it {describe(p['earlier'], p['later'])} "
            f"({p['end'] - p['start']:.0f} s). The AI redoes the captions and hook. "
            "The new version shows up in review in 1-3 minutes.")


def main():
    ap = argparse.ArgumentParser(description="Widen a Reel in media\\edits and cut it again from the original video.")
    ap.add_argument("clip", help="file name of the clip in media\\edits")
    ap.add_argument("--earlier", type=float, default=0, help="start this many seconds earlier")
    ap.add_argument("--later", type=float, default=0, help="end this many seconds later")
    ap.add_argument("--quiet-start", action="store_true", help=argparse.SUPPRESS)
    a = ap.parse_args()

    def log(text):
        print(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}  {text}", flush=True)
    try:
        run(Path(a.clip).name, a.earlier, a.later, log)
    except Exception as exc:
        if not a.quiet_start:
            print(f"\n[reclip] {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
