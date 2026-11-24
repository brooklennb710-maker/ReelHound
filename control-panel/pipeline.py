import argparse
import csv
import datetime as dt
import importlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path
from tempfile import NamedTemporaryFile

ROOT = Path(os.environ.get("REELHOUND_PANEL_ROOT", Path(__file__).resolve().parents[1]))
HUNTER = ROOT / "hunter"
MEDIA = ROOT / "media"
LOCAL = ROOT / "control-panel"
CONFIG = HUNTER / "config.json"
SCHEDULE = LOCAL / "schedule.json"
DELETED = LOCAL / "deleted"
LINKS = {name: MEDIA / name for name in ("raw", "edits", "ready", "official")}
LINKS.update(finds=HUNTER / "finds.html", playbook=ROOT / "docs" / "PLAYBOOK.md", scoreboard=ROOT / "scoreboard.csv")
PLATFORMS = ("youtube", "reddit", "instagram", "tiktok")
STYLES = ("viral", "clean", "news")
POSITIONS = ("bottom-center", "bottom-left", "top-left", "top-center")
MODELS = ("tiny", "base", "small", "medium", "large-v3")
CAPTION_BREAK = "\n\n---\n"
LOCK = threading.RLock()

sys.dont_write_bytecode = True
sys.path[:0] = [str(ROOT), str(HUNTER), str(ROOT / "clipmaker")]
import brand  # noqa: E402  (time zone, destinations)
hunter = importlib.import_module("hunter")
autoclip = importlib.import_module("autoclip")
reclip = importlib.import_module("reclip")  # start earlier / extend end: re-cut a Reel from its source
wholejob = importlib.import_module("wholejob")  # repost a whole cleared video as one Reel or numbered parts

DESTINATIONS = brand.destinations()
ZONE = brand.tz()


def local(moment):
    """Convert an aware UTC datetime to the time zone in brand.json (default: this PC's)."""
    return moment.astimezone(ZONE)


def zone_label():
    return ZONE.tzname(dt.datetime.now(dt.UTC)) or "local"


def slot_utc(day, clock):
    """UTC instant for a local wall-clock time.

    Scans UTC offsets so any time zone works, and takes the first occurrence of a
    repeated hour at a daylight-saving fall-back.
    """
    wall = dt.datetime.combine(day, dt.time.fromisoformat(clock))
    for offset in range(14, -15, -1):
        utc = (wall - dt.timedelta(hours=offset)).replace(tzinfo=dt.UTC)
        if local(utc).replace(tzinfo=None) == wall:
            return utc
    return None  # that wall time does not exist (spring-forward jump)


def read_json(path, default=None):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except ValueError:
        return default  # a half-edited config should not take the panel down


def atomic(path, write):
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=path.parent, delete=False) as file:
        tmp = Path(file.name)
        try:
            write(file)
            file.close()
            os.replace(tmp, path)
        finally:
            file.close()
            tmp.unlink(missing_ok=True)


def write_json(path, data):
    atomic(path, lambda f: json.dump(data, f, indent=2, ensure_ascii=False))


def csv_rows(path):
    if not path.exists():
        return [], []
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        return reader.fieldnames or [], list(reader)


def integer(data, key, low, high):
    value = data.get(key)
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"Enter {key.replace('_', ' ')} between {low} and {high}.")
    return value


def choice(data, key, values):
    value = data.get(key)
    if value not in values:
        raise ValueError(f"Choose a valid {key.replace('_', ' ')}.")
    return value


def string(data, key, limit=300):
    value = data.get(key, "")
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f"Check the {key.replace('_', ' ')} field.")
    return value.strip()


def lines(data, key):
    return list(dict.fromkeys(x.strip() for x in string(data, key, 12000).splitlines() if x.strip()))


def set_secret(data, target, key):
    if data.get("clear_" + key) is True:
        target[key] = ""
    elif string(data, key, 4096):
        target[key] = string(data, key, 4096)


def configured(value):
    return bool(value and not value.startswith("PASTE"))


def settings():
    cfg = read_json(CONFIG, {})
    ig = cfg.get("instagram", {})
    own = next((r["channel_id"] for r in hunter.load_creators().values()
                if r["platform"] == "youtube" and r["permission"] == "own" and configured(r["channel_id"])), "")
    return dict(
        every_minutes=cfg.get("every_minutes", 45), keywords="\n".join(cfg.get("keywords", [])),
        min_score=cfg.get("min_score", 40), subreddits="\n".join(cfg.get("subreddits", [])),
        sources={p: cfg.get("sources", {}).get(p, True) for p in PLATFORMS[:3]},
        youtube_key_saved=configured(cfg.get("youtube_api_key")), youtube_channel_id=cfg.get("youtube_channel_id", own),
        ig_user_id=ig.get("ig_user_id", "") if configured(ig.get("ig_user_id")) else "",
        instagram_key_saved=configured(ig.get("access_token")), hashtags="\n".join(ig.get("hashtags", [])),
        reddit_client_id=(cfg.get("reddit") or {}).get("client_id", ""),
        reddit_secret_saved=configured((cfg.get("reddit") or {}).get("client_secret")),
        clip_seconds=cfg.get("clip_seconds", 40), clips_per_video=cfg.get("clips_per_video", 3),
        captions=cfg.get("captions", True), whisper_model=cfg.get("whisper_model", "small"),
        clip_preset=cfg.get("clip_preset", "viral"), caption_size=cfg.get("caption_size"),
        credit_text=cfg.get("credit_text", ""), credit_position=cfg.get("credit_position", "bottom-center"),
    )


def save_settings(kind, data):
    cfg = read_json(CONFIG, {})
    if kind == "hunter":
        cid = string(data, "youtube_channel_id")
        if cid and not re.fullmatch(r"UC[A-Za-z0-9_-]{22}", cid):
            raise ValueError("Enter your YouTube channel ID beginning with UC, or leave it blank.")
        sources = data.get("sources", {})
        if not isinstance(sources, dict) or any(type(sources.get(p)) is not bool for p in PLATFORMS[:3]):
            raise ValueError("Choose which sources to scan.")
        subreddits = [re.sub(r"^/?r/", "", x) for x in lines(data, "subreddits")]
        if any(not re.fullmatch(r"[a-zA-Z0-9_]+", x) for x in subreddits):
            raise ValueError("Enter one subreddit name per line.")
        cfg.update(every_minutes=integer(data, "every_minutes", 1, 1440), keywords=lines(data, "keywords"),
                   min_score=integer(data, "min_score", 0, 100), sources=sources, subreddits=subreddits,
                   youtube_channel_id=cid)
        set_secret(data, cfg, "youtube_api_key")
        ig = cfg.setdefault("instagram", {})
        ig.update(ig_user_id=string(data, "ig_user_id"), hashtags=[x.lstrip("#") for x in lines(data, "hashtags")])
        set_secret(data, ig, "access_token")
        rd = cfg.setdefault("reddit", {})
        rd["client_id"] = string(data, "reddit_client_id", 200)
        if data.get("clear_reddit_client_secret") is True:
            rd["client_secret"] = ""
        elif string(data, "reddit_client_secret", 400):
            rd["client_secret"] = string(data, "reddit_client_secret", 400)
    else:
        length = data.get("clip_seconds")
        if type(length) not in (int, float) or not 8 <= length <= 90:
            raise ValueError("Enter a clip length between 8 and 90 seconds.")
        cfg.update(clip_seconds=length, clips_per_video=integer(data, "clips_per_video", 1, 20),
                   captions=data.get("captions") is True, whisper_model=choice(data, "whisper_model", MODELS),
                   clip_preset=choice(data, "clip_preset", STYLES),
                   caption_size=None if data.get("caption_size") is None else integer(data, "caption_size", 24, 160),
                   credit_text=string(data, "credit_text"), credit_position=choice(data, "credit_position", POSITIONS))
    write_json(CONFIG, cfg)
    return settings()


def creator_list():
    with hunter.FILE_LOCK:
        return csv_rows(Path(hunter.CREATORS))[1]


def creator_change(action, data):
    path = Path(hunter.CREATORS)
    with hunter.FILE_LOCK:
        fields, rows = csv_rows(path)
        fields = list(dict.fromkeys(fields + hunter.CREATOR_FIELDS))
        old = data.get("old")
        index = None
        if old is not None:
            index = next((i for i, row in enumerate(rows) if row == old), None)
            if index is None:
                raise ValueError("This creator changed. Refresh the list and try again.")
        if action == "remove":
            if index is None:
                raise ValueError("Select a creator to remove.")
            rows.pop(index)
        else:
            row = {k: string(data, k, 2000) for k in hunter.CREATOR_FIELDS}
            choice(row, "platform", PLATFORMS)
            choice(row, "permission", ("yes", "no", "own", "official", "unknown", "asked"))
            keys = {hunter.norm(row[k]) for k in ("handle", "channel_id")} - {""}
            if not row["handle"]:
                raise ValueError("Enter a creator handle or name.")
            if any(i != index and r["platform"] == row["platform"] and
                   keys.intersection(hunter.norm(r[k]) for k in ("handle", "channel_id")) for i, r in enumerate(rows)):
                raise ValueError("This creator is already on the list.")
            if index is None:
                rows.append(row)
            else:
                rows[index].update(row)
            if row["permission"] == "yes":
                # The existing approval workflow updates matching finds and queues their downloads.
                pending = [r for r in hunter.read_finds() if r["platform"] == row["platform"]
                           and r["action"].startswith("ask permission")
                           and keys.intersection(hunter.norm(r[k]) for k in ("creator", "creator_id"))]
                if pending and row["platform"] != "instagram":
                    require_no_legacy_hunter()
            else:
                pending = []

        def save(file):
            writer = csv.DictWriter(file, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

        atomic(path, save)
        if action != "remove" and pending:
            hunter.approve_creator(row["platform"], row["handle"], row["channel_id"], defer=True)
            HUNT.wake.set()
        return rows


def waiting():
    creators = hunter.load_creators()
    result = []
    for row in reversed(hunter.read_finds()):
        if row["action"].startswith("ask permission") and hunter.permission_for(row, creators) != "no":
            result.append({k: row[k] for k in ("id", "score", "platform", "creator", "title", "url")})
            result[-1]["message"] = hunter.permission_message(row)
            result[-1]["can_approve"] = bool(hunter.norm(row["creator"]) and row["creator"] != "see post")
    return result


def require_no_legacy_hunter(panel_port=8875):
    port = int((read_json(CONFIG, {}) or {}).get("page_port", 8765))
    if port == panel_port:
        return
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            pass
    except OSError:
        return
    try:  # an older copy of this panel on the hunter's port is a duplicate panel, not the legacy hunter
        import urllib.request
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:
            if json.load(response).get("app") == "reelhound-panel":
                raise ValueError(f"Another copy of this panel is open at http://127.0.0.1:{port}. "
                                 "Close its window (or use that copy) so only one panel runs the workers.")
    except (OSError, ValueError, AttributeError) as exc:
        if isinstance(exc, ValueError) and "Another copy" in str(exc):
            raise
    raise ValueError("Close the old start_hunter.bat window before using this control. It is already running the pipeline.")


def approve(id_):
    with hunter.FILE_LOCK:
        row = next((r for r in hunter.read_finds() if r["id"] == id_ and r["action"].startswith("ask permission")), None)
        if not row:
            raise ValueError("This find is no longer waiting for permission.")
        if row["platform"] != "instagram":
            require_no_legacy_hunter()
        result = hunter.approve_creator(row["platform"], row["creator"], row["creator_id"], defer=True)
        if not result["ok"]:
            raise ValueError(result["message"])
    HUNT.wake.set()
    return result


def prepare_ffmpeg():
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        return
    profile = Path(os.environ.get("USERPROFILE", ""))
    candidates = [profile / "AppData/Local/Microsoft/WinGet/Links"]
    packages = profile / "AppData/Local/Microsoft/WinGet/Packages"
    candidates.extend(p.parent for p in packages.glob("*FFmpeg*/*/bin/ffmpeg.exe"))
    for folder in candidates:
        if (folder / "ffmpeg.exe").is_file() and (folder / "ffprobe.exe").is_file():
            os.environ["PATH"] = str(folder) + os.pathsep + os.environ["PATH"]
            return


class Worker:
    def __init__(self, name, run, interval):
        self.name, self.run, self.interval = name, run, interval
        self.enabled = False
        self.status = "idle"
        self.wake = threading.Event()
        self.thread = None
        self.logs = deque(maxlen=60)
        self.lock = threading.RLock()
        self.warning = False

    def log(self, *parts, **_):
        text = " ".join(map(str, parts)).strip()
        if not text:
            return
        with self.lock:
            self.warning |= bool(re.search(r"\b(failed|couldn't read|error|unavailable|continuing without captions)\b", text, re.I))
            try:
                cfg = read_json(CONFIG, {})
                for secret in (cfg.get("youtube_api_key"), cfg.get("instagram", {}).get("access_token")):
                    if configured(secret):
                        text = text.replace(secret, "[hidden]")
            except (ValueError, OSError):
                pass
            text = re.sub(r"(?i)((?:key|access_token)=)[^&\s]+", r"\1[hidden]", text)
            self.logs.append(f"{local(dt.datetime.now(dt.UTC)):%H:%M:%S}  {text[:1300]}")

    def set(self, enabled):
        with self.lock:
            self.enabled = enabled
            self.wake.set()
            if enabled and not (self.thread and self.thread.is_alive()):
                self.status = "running"
                self.thread = threading.Thread(target=self.loop, daemon=True, name=self.name)
                self.thread.start()
            elif not enabled and self.status != "running":
                self.status = "idle"

    def loop(self):
        while True:
            with self.lock:
                if not self.enabled:
                    self.status = "idle"
                    self.thread = None
                    return
                self.wake.clear()
                self.status, self.warning = "running", False
            delay = 30
            try:
                cfg = read_json(CONFIG, {})
                delay = self.interval(cfg)
                self.run(self, cfg)
            except Exception as exc:
                self.log(f"Error: {exc}")
            with self.lock:
                self.status = ("error" if self.warning else "idle") if self.enabled else "idle"
            self.wake.wait(delay)

    def view(self):
        with self.lock:
            return dict(enabled=self.enabled, status=self.status, logs=list(self.logs))


def hunt_cycle(worker, cfg):
    with hunter.WORK_LOCK:
        for row in hunter.read_finds():
            if not worker.enabled:
                return
            if row["action"] != "approved: downloading":
                continue
            if hunter.permission_for(row, hunter.load_creators()) not in ("yes", "own", "official"):
                result = ("", "skipped: creator permission changed")
            elif int(row["duration_s"] or 0) > cfg.get("max_video_minutes", 30) * 60:
                result = ("", "skipped: too long")
            else:
                worker.log(f"Downloading approved video: {row['title']}")
                result = hunter.download(dict(row, permission="yes"), cfg)
                worker.log(result[1])
            with hunter.FILE_LOCK:
                fresh = hunter.read_finds()
                for record in fresh:
                    if record["id"] == row["id"] and record["action"] == "approved: downloading":
                        record["file"], record["action"] = result
                hunter.save_finds(fresh)
                hunter.write_page()
        if worker.enabled:
            worker.log("Scanning enabled sources.")
            hunter.run_once(cfg, stopping=lambda: not worker.enabled)


def clip_cycle(worker, cfg):
    prepare_ffmpeg()
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError("FFmpeg or FFprobe was not found. Run setup.bat in the repo root.")

    def render(cmd):
        with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              encoding="utf-8", errors="replace", env=dict(os.environ, PYTHONUTF8="1"),
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)) as proc:
            for line in proc.stdout:
                if not line.lstrip().startswith("frame="):
                    worker.log(line)
            return proc.wait()

    args = argparse.Namespace(hook="", count=cfg.get("clips_per_video", 3), length=cfg.get("clip_seconds", 25),
                              preset=cfg.get("clip_preset", "viral"), no_captions=not cfg.get("captions", True),
                              whisper_model=cfg.get("whisper_model", "small"), caption_size=cfg.get("caption_size"),
                              credit_position=cfg.get("credit_position", "bottom-center"),
                              credit_text=cfg.get("credit_text", ""), guide_trim=cfg.get("guide_trim", True),
                              run_clip=render)
    autoclip.process_new(args, stopping=lambda: not worker.enabled)


HUNT = Worker("Hunter", hunt_cycle, lambda cfg: max(1, cfg.get("every_minutes", 45)) * 60)
CLIP = Worker("Clip maker", clip_cycle, lambda cfg: 25)
hunter.print = HUNT.log
autoclip.print = CLIP.log


def clips(folder):
    return sorted((p for p in folder.glob("*.mp4") if p.is_file() and not p.name.endswith(".part.mp4")),
                  key=lambda p: p.name, reverse=True)


def clip_path(area, name):
    if area not in ("edits", "ready") or not isinstance(name, str) or re.search(r"[/\\:]", name) or Path(name).name != name:
        raise ValueError("Select an available clip.")
    path = LINKS[area] / name
    if path.suffix.lower() != ".mp4" or name.endswith(".part.mp4") or not path.is_file() or path.is_symlink():
        raise ValueError("That clip is no longer available.")
    return path


def caption(path):
    sidecar = path.with_suffix(".txt")
    parts = (sidecar.read_text(encoding="utf-8-sig", errors="replace") if sidecar.exists() else "").partition(CAPTION_BREAK)
    return parts[0].rstrip(), parts[2]


def save_caption(path, value):
    _, metadata = caption(path)
    atomic(path.with_suffix(".txt"), lambda f: f.write(value + (CAPTION_BREAK + metadata if metadata else "\n")))


def review(action, data):
    path = clip_path(data.get("area", "edits"), data["name"])
    if action in ("keep", "delete") and path.parent != LINKS["edits"]:
        raise ValueError("Select a clip in the review folder.")
    if action == "caption":
        save_caption(path, string(data, "caption", 12000))
        return
    if action == "keep":
        destination = LINKS["ready"] / path.name
    elif action == "delete":
        from uuid import uuid4
        destination = DELETED / uuid4().hex / path.name
    else:
        raise ValueError("Unknown review action.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.with_suffix(".txt").exists():
        raise ValueError("A file with that name already exists in the destination.")
    side = path.with_suffix(".txt")
    moved = False
    if action == "keep":
        save_caption(path, string(data, "caption", 12000))
    if side.exists():
        side.rename(destination.with_suffix(".txt"))
        moved = True
    try:
        path.rename(destination)
    except OSError:
        if moved:
            destination.with_suffix(".txt").rename(side)
        raise


def ai_reviews():
    """Scores from reviewer/review_edits.py (local pre-filter), keyed by file name."""
    path = ROOT / "reviewer" / "results.csv"
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            return {r["file"]: {k: r.get(k, "") for k in ("rank", "score", "verdict", "what_happens", "flags",
                                                            "problems", "duplicate_of", "category", "hook", "payoff",
                                                            "standalone", "phone", "title")} for r in csv.DictReader(f)}
    except (OSError, csv.Error, KeyError):
        return {}


def redo_state(name):
    """Re-cut info for a clip in review: a re-cut running or failed on it, or the change that made it."""
    out = {}
    j = reclip.job(name)
    if j and j.get("status") in ("queued", "working") and reclip.busy(name):
        out.update(redo="working", redo_text=reclip.describe(j.get("earlier", 0), j.get("later", 0)))
    elif j and j.get("status") == "failed":
        out.update(redo="failed", redo_text=j.get("error", ""))
    old = reclip.made_from(name)
    if old:
        out["redo_from"] = reclip.describe(old.get("earlier", 0), old.get("later", 0))
    return out


def redo(data):
    name = clip_path("edits", data.get("name")).name
    return reclip.start(name, data.get("earlier") or 0, data.get("later") or 0)


def whole_list():
    return {"rows": wholejob.sources()}


def whole_start(data):
    mode = choice(data, "mode", wholejob.MODES)
    return wholejob.start(string(data, "name"), mode, data.get("confirmed") is True)


def inbox_call(path, data=None):
    """Talk to the phone inbox (it downloads links, checks creators.csv and holds unknown creators)."""
    import urllib.error
    import urllib.request
    port = read_json(ROOT / "inbox" / "config.json", {}).get("port", 8876)
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=body,
                                 headers={"Content-Type": "application/json"} if body else {})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.load(r)
    except urllib.error.HTTPError as exc:
        try:
            message = json.load(exc).get("error")
        except (ValueError, AttributeError):
            message = ""
        raise ValueError(message or "The phone inbox refused that.")
    except (urllib.error.URLError, OSError):
        raise ValueError("The phone inbox isn't running, and it does the downloading. Open "
                         "inbox\\Open Phone Inbox.bat (or Start ReelHound.bat) and try again.")


def whole_link(data):
    text = string(data, "url", 2000)
    if not re.search(r"https?://", text):
        raise ValueError("Paste a video link (YouTube, Instagram, TikTok, X, Reddit...).")
    whose = choice(data, "whose", ("mine", "other"))
    result = inbox_call("/api/add", {"text": text, "whose": whose, "whole": True})
    n = len(result.get("added", []))
    extra = (" " + "; ".join(result["errors"])) if result.get("errors") else ""
    return (f"Sent {n} link{'s' if n != 1 else ''} to download. Cleared creators become a whole-video Reel in "
            "Clip review; unknown ones wait here with a draft message (nothing is sent)." + extra)


def whole_links():
    try:
        rows = inbox_call("/api/items")["items"]
    except ValueError as exc:
        return {"running": False, "error": str(exc), "rows": []}
    keep = ("id", "url", "status", "platform", "creator", "title", "message", "note", "parts", "part_len",
            "whole_mode", "added")
    out = [dict({k: r.get(k, "") for k in keep}, reels=[x["name"] for x in r.get("reels", [])])
           for r in rows if r.get("whole") or r.get("whole_mode")]
    return {"running": True, "rows": out[:15]}


def whole_link_action(data):
    act = choice(data, "do", ("parts", "cap", "retry", "remove"))
    item = string(data, "id", 40)
    if act in ("parts", "cap"):
        inbox_call("/api/whole", {"id": item, "mode": act})
    else:
        inbox_call("/api/" + act, {"id": item})
    return {"ok": True}


def reclipping():
    return sum(1 for p in reclip.JOBS.glob("*.json") if reclip.busy(p.stem + ".mp4")) if reclip.JOBS.exists() else 0


def clip_facts(path):
    """Search fields for Clip review: credit, preset, length and render time from the caption sidecar."""
    text, meta = caption(path)
    info = dict(re.findall(r"^([a-z_]+):\s*(.*?)\s*$", meta, re.M))
    seconds = None
    span = re.fullmatch(r"([\d.]+) to ([\d.]+)", info.get("range", ""))
    if span:
        seconds = round(float(span.group(2)) - float(span.group(1)), 1)
    return dict(caption=text, credit=info.get("credit", "").lstrip("@"), preset=info.get("preset", ""),
                permission=info.get("permission", ""), seconds=seconds, modified=path.stat().st_mtime)


def library(area):
    ai = ai_reviews() if area == "edits" else {}
    return [dict(name=p.name, ai=ai.get(p.name), **clip_facts(p), **(redo_state(p.name) if area == "edits" else {}))
            for p in clips(LINKS[area])]


def schedule():
    return read_json(SCHEDULE, dict(times=["09:00", "15:00", "21:00"], posts_per_day=3,
                                    day_start="04:00", items=[]))


def service_clock(clock, day_start):
    """Sort key that keeps after-midnight slots at the end of the posting day."""
    return clock if clock >= day_start else "24+" + clock


def schedule_save(data):
    clocks = lines(data, "times")
    if not clocks or any(not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", c) for c in clocks):
        raise ValueError("Enter posting times as HH:MM (24-hour), one per line.")
    day_start = string(data, "day_start", 5) or "04:00"
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", day_start):
        raise ValueError("Enter when the posting day starts as HH:MM (24-hour), like 04:00.")
    limit = integer(data, "posts_per_day", 1, min(len(clocks), 24))
    cfg = schedule()
    cfg.update(times=sorted(clocks, key=lambda c: service_clock(c, day_start)), posts_per_day=limit,
               day_start=day_start)
    write_json(SCHEDULE, cfg)
    return cfg


def add_queue(data):
    path = clip_path("ready", data["name"])
    channels = data.get("channels", [])
    if not isinstance(channels, list) or not channels or any(c not in DESTINATIONS for c in channels):
        raise ValueError("Select at least one destination.")
    cfg = schedule()
    day_start = cfg.get("day_start", "04:00")
    if any(x["name"] == path.name for x in cfg["items"]):
        raise ValueError("This clip is already scheduled.")
    now = dt.datetime.now(dt.UTC)
    now_local = local(now)
    day = now_local.date() - dt.timedelta(days=int(now_local.strftime("%H:%M") < day_start))
    occupied = {x["utc"] for x in cfg["items"]}
    counts = {}
    for item in cfg["items"]:
        counts[item["posting_day"]] = counts.get(item["posting_day"], 0) + 1
    for offset in range(len(cfg["items"]) + 4):
        posting_day = day + dt.timedelta(days=offset)
        if counts.get(posting_day.isoformat(), 0) >= cfg["posts_per_day"]:
            continue
        for clock in cfg["times"]:
            calendar_day = posting_day + dt.timedelta(days=int(clock < day_start))
            stamp = slot_utc(calendar_day, clock)
            if stamp and stamp > now and stamp.isoformat() not in occupied:
                item = dict(name=path.name, channels=list(dict.fromkeys(channels)), utc=stamp.isoformat(),
                            posting_day=posting_day.isoformat())
                cfg["items"].append(item)
                cfg["items"].sort(key=lambda x: x["utc"])
                write_json(SCHEDULE, cfg)
                return cfg
    raise ValueError("No upcoming posting slot is available.")


def queue_view():
    cfg = schedule()
    items = []
    for item in cfg["items"]:
        utc = dt.datetime.fromisoformat(item["utc"])
        path = LINKS["ready"] / item["name"]
        items.append(dict(item, local=local(utc).strftime("%a, %b %d · %I:%M %p %Z"),
                          caption=caption(path)[0] if path.exists() else "", available=path.exists(),
                          file=str(path), past=utc <= dt.datetime.now(dt.UTC)))
    return dict(cfg, items=items, destinations=list(DESTINATIONS), zone=zone_label())


def scoreboard():
    fields, rows = csv_rows(LINKS["scoreboard"])

    def as_number(value):
        try:
            return int(str(value).replace(",", ""))
        except ValueError:
            return 0

    best = max(rows, key=lambda r: as_number(r.get("views_24h")), default=None)
    return dict(fields=fields, rows=rows, best=best if best and best.get("views_24h") else None,
                views=sum(as_number(r.get("views_24h")) for r in rows))


def overview():
    today = local(dt.datetime.now(dt.UTC)).date()
    finds = hunter.read_finds()
    raw = clips(LINKS["raw"])
    edits = clips(LINKS["edits"])
    ready = clips(LINKS["ready"])
    deleted = list(DELETED.glob("*/*.mp4"))

    def today_file(p):
        try:
            info = p.stat()
            return local(dt.datetime.fromtimestamp(max(info.st_mtime, getattr(info, "st_birthtime", 0)), dt.UTC)).date() == today
        except FileNotFoundError:
            return False

    downloaded = {p.name for p in raw if today_file(p)}
    downloaded.update(Path(r["file"]).name for r in finds if r["file"] and r["action"] == "downloaded"
                      and Path(r["file"]).name.startswith(today.strftime("%Y%m%d")))
    made = [p for p in edits + ready + deleted if today_file(p)]
    sources = set()
    for path in made:
        match = re.search(r"^source: (.+)$", caption(path)[1], re.M)
        if match:
            sources.add(match[1])
    latest = max(edits + ready, key=lambda p: p.name, default=None)
    return dict(date=today.strftime("%A, %B %d"), zone=zone_label(), found=len({r["id"] for r in finds
                if r["found_at"] and local(hunter.parse_time(r["found_at"])).date() == today}),
                downloaded=len(downloaded), videos_clipped=len(sources), clips_created=len(made),
                edits=len(edits), ready=len(ready), queued=len(schedule()["items"]), reclipping=reclipping(),
                latest=dict(area=latest.parent.name, name=latest.name) if latest else None,
                workers={"hunter": HUNT.view(), "clip": CLIP.view()}, ai=ai_view(edits))


class AIReview:
    """Runs reviewer/review_edits.py (local Ollama vision model) in the background. Read-only on media."""

    def __init__(self):
        self.proc = None
        self.lines = deque(maxlen=60)
        self.done = self.total = 0
        self.finished = None
        self.code = None
        self.lock = threading.Lock()

    def start(self):
        with self.lock:
            if self.proc and self.proc.poll() is None:
                raise ValueError("The AI review is already running.")
            script = ROOT / "reviewer" / "review_edits.py"
            if not script.exists():
                raise ValueError("reviewer/review_edits.py is missing.")
            self.lines.clear()
            self.done = self.total = 0
            self.finished = self.code = None
            self.proc = subprocess.Popen([sys.executable, "-u", str(script), "--top", "12"], cwd=str(script.parent),
                                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8",
                                         errors="replace", env=dict(os.environ, PYTHONUTF8="1"),
                                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        threading.Thread(target=self._read, args=(self.proc,), daemon=True).start()

    def _read(self, proc):
        for line in proc.stdout:
            line = line.rstrip()
            if not line:
                continue
            self.lines.append(line)
            m = re.match(r"\[(\d+)/(\d+)\]", line)
            if m:
                self.done, self.total = int(m[1]), int(m[2])
        self.code = proc.wait()
        self.finished = dt.datetime.now(dt.UTC).isoformat()
        if self.code and not self.lines:
            self.lines.append("The AI review stopped. Is Ollama running?")

    def view(self):
        running = bool(self.proc and self.proc.poll() is None)
        status = "running" if running else ("error" if self.code else ("done" if self.finished else "idle"))
        return dict(status=status, done=self.done, total=self.total, logs=list(self.lines)[-6:])


AI = AIReview()


def ai_view(edits=None):
    names = {p.name for p in (edits if edits is not None else clips(LINKS["edits"]))}
    reviews = ai_reviews()
    rows = sorted((dict(r, name=n) for n, r in reviews.items() if n in names and not r.get("duplicate_of")),
                  key=lambda r: int(r.get("rank") or 10**6))
    path = ROOT / "reviewer" / "results.csv"
    when = dt.datetime.fromtimestamp(path.stat().st_mtime, dt.UTC).isoformat() if path.exists() else None
    return dict(AI.view(), top=rows[:6], scored=sum(1 for n in names if n in reviews),
                unscored=sum(1 for n in names if n not in reviews), updated=when)
