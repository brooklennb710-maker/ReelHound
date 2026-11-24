"""ReelHound phone inbox.

Send a clip from your phone (a link, or the video file itself) and this turns it into Reels in media\\edits:
download -> permission check -> Clip Maker (with the how-to trim) -> media\\edits for review.

It never posts or schedules anything.

Runs at http://127.0.0.1:8876 and is shared to your own devices only through `tailscale serve`
(tailnet-only, not public). See inbox\\README.md.
"""
import argparse
import csv
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
MEDIA = ROOT / "media"
WORK = MEDIA / "raw" / "phone-inbox"           # subfolder: the panel's auto-clip only scans media\raw itself
HOLD = MEDIA / "_not-cleared" / "phone-inbox"  # downloads waiting on a creator's permission
EDITS = MEDIA / "edits"
READY = MEDIA / "ready"
DELETED = ROOT / "control-panel" / "deleted"   # same restorable bin the panel's Delete uses
CONFIG = HERE / "config.json"
ITEMS = HERE / "items.json"
PAGE = HERE / "page.html"
LOG = HERE / "inbox.log"
MAX_UPLOAD = 1024 * 1024 * 1024
MAX_SOURCE_MINUTES = 30

sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONUTF8", "1")
sys.path[:0] = [str(ROOT), str(ROOT / "hunter"), str(ROOT / "clipmaker")]
import hunter     # noqa: E402  creators.csv helpers and the permission message
import autoclip   # noqa: E402  moment finder + Clip Maker command builder
import brand      # noqa: E402  credits and watermark text
import reclip     # noqa: E402  start earlier / extend end: re-cut a finished Reel from its source

LOCK = threading.RLock()
WAKE = threading.Event()
DEFAULTS = {"port": 8876, "my_accounts": {"instagram": [], "facebook": [], "tiktok": [], "youtube": []},
            "cookies_from_browser": "", "short_clip_max_seconds": 90}


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def log(*parts):
    text = " ".join(str(p) for p in parts)
    line = f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}  {text}"
    try:
        print(line, flush=True)
    except (OSError, ValueError):
        pass
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, data):
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def config():
    cfg = dict(DEFAULTS)
    cfg.update(read_json(CONFIG, {}))
    cfg["my_accounts"] = {**DEFAULTS["my_accounts"], **cfg.get("my_accounts", {})}
    return cfg


def items():
    return read_json(ITEMS, [])


def update(item_id, **changes):
    with LOCK:
        rows = items()
        for row in rows:
            if row["id"] == item_id:
                row.update(changes, updated=now())
                write_json(ITEMS, rows)
                return row
    return None


def add_item(**fields):
    with LOCK:
        rows = items()
        url = fields.get("url")
        if url and any(r.get("url") == url and not r["status"].startswith(("failed", "removed")) for r in rows):
            raise ValueError("already in the inbox")
        row = dict(id=uuid.uuid4().hex[:10], added=now(), updated=now(), status="queued", platform="", creator="",
                   title="", file="", clips=[], message="", note="", guide=False, whose="mine", url="",
                   whole=False, whole_mode="")
        row.update(fields)
        rows.append(row)
        write_json(ITEMS, rows)
    WAKE.set()
    return row


# ---------- permission ----------
PLATFORM_OF = {"instagram": "instagram", "youtube": "youtube", "youtubetab": "youtube", "tiktok": "tiktok",
               "facebook": "facebook", "reddit": "reddit", "twitter": "x", "twitch": "twitch", "kick": "kick"}


def platform_from_url(url):
    host = urlsplit(url).netloc.lower()
    for key, name in (("instagram", "instagram"), ("youtu", "youtube"), ("tiktok", "tiktok"), ("facebook", "facebook"),
                      ("fb.watch", "facebook"), ("reddit", "reddit"), ("x.com", "x"), ("twitter", "x"),
                      ("twitch", "twitch"), ("kick.com", "kick")):
        if key in host:
            return name
    return host or "upload"


def creator_permission(platform, handle):
    c = hunter.load_creators().get((platform, hunter.norm(handle)))
    return (c or {}).get("permission", "unknown")


def record_creator(platform, handle, permission, note):
    """Add or update the creator's row in hunter\\creators.csv (the permission record)."""
    path = Path(hunter.CREATORS)
    with hunter.FILE_LOCK:
        rows, fields = [], list(hunter.CREATOR_FIELDS)
        if path.exists():
            with open(path, encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                fields = list(dict.fromkeys((reader.fieldnames or []) + fields))
                rows = list(reader)
        key = hunter.norm(handle)
        row = next((r for r in rows if (r.get("platform") or "").lower() == platform and
                    key in (hunter.norm(r.get("handle", "")), hunter.norm(r.get("channel_id", "")))), None)
        if row is None:
            row = {k: "" for k in fields}
            row.update(platform=platform, handle=handle)
            rows.append(row)
        row["permission"] = permission
        row["notes"] = (row.get("notes", "") + "; " if row.get("notes") else "") + note
        tmp = str(path) + ".inbox-tmp"
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(tmp, path)


def draft_message(creator, title):
    return hunter.permission_message({"creator": "@" + creator.lstrip("@") if creator else "there",
                                      "title": title or "your video"})


# ---------- download ----------
_TEMP_COOKIES = []


def download_cookies(cfg):
    """Sign-in cookies for yt-dlp: the inbox's own cookies_from_browser, else the hunter's settings
    (hunter\\youtube_cookies.txt if it exists, else its cookies_from_browser). YouTube's bot check needs them."""
    if (cfg.get("cookies_from_browser") or "").strip():
        return ["--cookies-from-browser", cfg["cookies_from_browser"].strip()]
    args, temp = hunter.cookie_args(read_json(ROOT / "hunter" / "config.json", {}))
    if temp:
        _TEMP_COOKIES.append(temp)   # deleted after the download (never pass the export itself: yt-dlp rewrites it)
    return args


def download(item, cfg):
    WORK.mkdir(parents=True, exist_ok=True)
    base = WORK / f"{dt.datetime.now():%Y%m%d-%H%M%S}_{item['id']}"
    cmd = [sys.executable, "-m", "yt_dlp", "-f", "bv*[height<=1920]+ba/b", "--merge-output-format", "mp4",
           "--remux-video", "mp4", "--no-mtime", "--no-playlist", "--write-info-json",
           "--match-filter", f"!is_live & duration <? {MAX_SOURCE_MINUTES * 60}", "-o", str(base) + ".%(ext)s"]
    cmd += download_cookies(cfg)
    try:
        r = subprocess.run(cmd + [item["url"]], capture_output=True, text=True, encoding="utf-8", errors="replace",
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    finally:
        while _TEMP_COOKIES:
            try:
                os.remove(_TEMP_COOKIES.pop())
            except OSError:
                pass
    video = Path(str(base) + ".mp4")
    info_path = Path(str(base) + ".info.json")
    info = read_json(info_path, {})
    info_path.unlink(missing_ok=True)
    if r.returncode != 0 or not video.is_file():
        err = (r.stderr.strip().splitlines() or ["no MP4 was produced"])[-1]
        if "does not pass filter" in r.stdout + r.stderr:
            err = f"longer than {MAX_SOURCE_MINUTES} minutes or a live stream"
        elif "youtu" in item["url"] and re.search(r"Requested format is not available|Only images are available",
                                                    r.stdout + r.stderr):
            err = ("YouTube needs yt-dlp's challenge solver, which isn't installed. In a terminal run: "
                   "python -m pip install -U yt-dlp-ejs   then press Retry")
        elif re.search(r"confirm you.?re not a bot|sign in to confirm", r.stderr, re.I):
            err = ("YouTube's bot check blocked it: the cookies are signed out or expired. Export fresh YouTube cookies from a private window to "
                   "hunter\\youtube_cookies.txt, then press Retry")
        elif re.search(r"login|cookies|rate.?limit|private|empty media", err, re.I):
            err += " (Instagram may want a sign-in: see 'Instagram sign-in' in inbox\\README.md)"
        raise RuntimeError("download failed: " + err[:260])
    handle = (info.get("channel") or info.get("uploader_id") or info.get("uploader") or "").strip().lstrip("@")
    platform = PLATFORM_OF.get((info.get("extractor_key") or "").lower(), platform_from_url(item["url"]))
    title = (info.get("title") or "").strip()
    if not title or title.lower().startswith("video by "):  # instagram's placeholder title: use the caption
        title = (info.get("description") or title).strip()
    return video, platform, handle, " ".join(title.split())[:200]


# ---------- clipping ----------
def render(cmd):
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8", errors="replace",
                          env=dict(os.environ, PYTHONUTF8="1"),
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)) as proc:
        for line in proc.stdout:
            if line.strip() and not line.lstrip().startswith("frame="):
                log("   ", line.rstrip()[:300])
        return proc.wait()


def prepare_ffmpeg():
    """Same lookup the panel uses: find the WinGet FFmpeg if it isn't on PATH."""
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        return
    profile = Path(os.environ.get("USERPROFILE", ""))
    candidates = [profile / "AppData/Local/Microsoft/WinGet/Links"]
    candidates += [p.parent for p in (profile / "AppData/Local/Microsoft/WinGet/Packages").glob("*FFmpeg*/*/bin/ffmpeg.exe")]
    for folder in candidates:
        if (folder / "ffmpeg.exe").is_file() and (folder / "ffprobe.exe").is_file():
            os.environ["PATH"] = str(folder) + os.pathsep + os.environ["PATH"]
            return


def clip(item, video, source):
    cfg = read_json(ROOT / "hunter" / "config.json", {})
    prepare_ffmpeg()
    EDITS.mkdir(parents=True, exist_ok=True)
    before = {p.name for p in EDITS.glob("*.mp4")}
    args = argparse.Namespace(
        hook="", count=int(cfg.get("clips_per_video", 3)), length=float(cfg.get("clip_seconds", 40)),
        preset=cfg.get("clip_preset", "viral"), no_captions=not cfg.get("captions", True),
        whisper_model=cfg.get("whisper_model", "small"), caption_size=cfg.get("caption_size"),
        credit_position=cfg.get("credit_position", "bottom-center"), credit_text=cfg.get("credit_text", ""),
        guide_trim=cfg.get("guide_trim", True), guide=bool(item.get("guide")), run_clip=render)
    total = autoclip.duration(str(video))
    guide = args.guide_trim and (args.guide or autoclip.is_guide(source.get("title", "")))
    if item.get("whole"):
        # "Whole video": no hunting for a moment. Over 90 s it raises autoclip.TooLong so the phone can ask.
        mode = item.get("whole_mode") or "auto"
        log(f"  Whole video ({total:.0f} s, mode {mode}){' with the how-to trim' if args.guide else ''}.")
        autoclip.clip_whole(str(video), source, args, mode)
    elif total <= float(config()["short_clip_max_seconds"]):
        # A Reel-length source is already one moment: keep it whole (the how-to trim still cuts filler).
        cmd = [sys.executable, autoclip.CLIPMAKER, str(video), "--start", "0", "--end", f"{total:.2f}",
               "--permission", source["permission"], "--preset", args.preset, "--out", str(EDITS),
               "--auto-hook", "--source-title", source.get("title", ""),
               "--whisper-model", str(args.whisper_model), "--credit-position", args.credit_position]
        if args.caption_size:
            cmd += ["--caption-size", str(args.caption_size)]
        if source.get("credit"):
            cmd += ["--credit", source["credit"]]
        if args.no_captions:
            cmd.append("--no-captions")
        if guide:
            cmd.append("--guide")
        log(f"  Short source ({total:.0f} s): one Reel from the whole clip{' with the how-to trim' if guide else ''}.")
        if render(cmd) != 0:
            raise RuntimeError("Clip Maker failed. See inbox\\inbox.log.")
    else:
        log(f"  Long source ({total / 60:.1f} min): finding the best moments{' with the how-to trim' if guide else ''}.")
        autoclip.clip_video(str(video), source, args)
    made = sorted(p.name for p in EDITS.glob("*.mp4") if p.name not in before)
    for name in made:  # note the origin and permission in each caption sidecar for review
        side = EDITS / (Path(name).stem + ".txt")
        if side.exists():
            with open(side, "a", encoding="utf-8") as f:
                f.write(f"\nPhone inbox source: {item.get('url') or item.get('note') or 'uploaded file'}\n"
                        f"Permission: {source['permission']} ({source.get('permission_note', '')})\n")
    return made


# ---------- the worker ----------
def cleared(perm):
    return {"own": "own", "yes": "creator-yes", "official": "official"}.get(perm, "")


def hold(video):
    HOLD.mkdir(parents=True, exist_ok=True)
    target = HOLD / video.name
    shutil.move(str(video), target)
    return target


def process(item):
    cfg = config()
    if item["kind"] == "link":
        update(item["id"], status="downloading")
        log(f"Downloading {item['url']}")
        video, platform, handle, title = download(item, cfg)
    else:
        video = Path(item["file"])
        platform, handle, title = item.get("platform") or "upload", item.get("creator", ""), item.get("title", "")
    handle = handle.lstrip("@")
    update(item["id"], kind="file", file=str(video), platform=platform, creator=handle, title=title)

    whose, perm, why = item["whose"], "unknown", ""
    mine = cfg["my_accounts"].get(platform, [])
    if whose == "mine":
        if item["kind"] == "link" and handle and mine and hunter.norm(handle) not in {hunter.norm(h) for h in mine}:
            whose = "other"
            note = f"sent as yours, but it was posted by @{handle}, not {', '.join('@' + h for h in mine)}"
            update(item["id"], whose="other", note=note)
            log("  " + note)
        else:
            if item["kind"] == "link" and handle and not mine and platform in cfg["my_accounts"]:
                with LOCK:
                    saved = read_json(CONFIG, {})
                    saved.setdefault("my_accounts", dict(DEFAULTS["my_accounts"]))[platform] = [handle]
                    write_json(CONFIG, saved)
                record_creator(platform, handle, "own", f"your main account (learned from phone inbox {dt.date.today().isoformat()})")
                log(f"  Learned your main {platform} account: @{handle}")
            perm, why = "own", "your own account" + (f" @{handle}" if handle else ", sent from your phone")
    if whose != "mine":
        perm = creator_permission(platform, handle) if handle else "unknown"
        why = f"creators.csv says '{perm}' for {platform} @{handle}" if handle else "no creator handle"
        if perm == "no":
            update(item["id"], status="skipped: creator said no", file=str(hold(video)))
            log(f"  Skipped: @{handle} said no.")
            return
        if not cleared(perm):
            held = hold(video)
            if handle and perm == "unknown":
                record_creator(platform, handle, "unknown",
                               f"sent from phone inbox {dt.date.today().isoformat()}: waiting on permission, draft message ready")
            update(item["id"], status="waiting permission", file=str(held), message=draft_message(handle, title))
            log(f"  Waiting on permission from {platform} @{handle or '?'}; held in {held}")
            return

    source = {"platform": platform, "creator": handle, "title": title, "url": item.get("url", ""),
              "permission": cleared(perm), "permission_note": why, "via": "phone inbox",
              "credit": brand.credit_for(handle, perm)}
    with open(video.with_suffix(".source.json"), "w", encoding="utf-8") as f:
        json.dump(source, f, indent=2)
    update(item["id"], status="clipping", note=why)
    log(f"  Cleared ({why}). Clipping...")
    try:
        made = clip(item, video, source)
    except autoclip.TooLong as exc:
        total = autoclip.duration(str(video))
        update(item["id"], status="needs choice", message=f"This is {autoclip.mmss_short(total)} long, too long for "
               "one Reel (90 s max). How should it be clipped?", seconds=round(total, 1),
               parts=autoclip.parts_needed(total), part_len=autoclip.mmss_short(total / autoclip.parts_needed(total)))
        log(f"  Whole video is too long ({exc}); asking on the phone.")
        return
    if not made:
        update(item["id"], status="done: no moment strong enough to clip", clips=[])
        log("  No Reels made.")
    else:
        update(item["id"], status=f"done: {len(made)} Reel{'s' if len(made) != 1 else ''} in media\\edits", clips=made)
        log(f"  Made {len(made)} Reel(s): {', '.join(made)}")


def release_cleared():
    """Waiting items whose creator now says yes (creators.csv, the panel, or the phone) go back in the queue."""
    for row in items():
        if row["status"] == "waiting permission" and row.get("creator"):
            if cleared(creator_permission(row["platform"], row["creator"])):
                held = Path(row["file"])
                if held.is_file():
                    WORK.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(held), WORK / held.name)
                    update(row["id"], status="queued", kind="file", file=str(WORK / held.name))
                    log(f"@{row['creator']} is cleared now; re-queued {held.name}")


def worker():
    while True:
        WAKE.clear()
        try:
            release_cleared()
            todo = next((r for r in items() if r["status"] == "queued"), None)
            if todo:
                try:
                    process(todo)
                except Exception as exc:
                    log(f"  Failed: {exc}")
                    update(todo["id"], status=f"failed: {str(exc)[:300]}")
                continue
        except Exception as exc:
            log(f"Worker error: {exc}")
        WAKE.wait(20)


# ---------- review from the phone (never posts or schedules) ----------
def clip_file(name, area="edits"):
    folder = {"edits": EDITS, "ready": READY}.get(area)
    if not folder or not isinstance(name, str) or Path(name).name != name or not name.lower().endswith(".mp4"):
        raise ValueError("Pick a clip from the list.")
    path = folder / name
    if not path.is_file():
        raise ValueError("That clip isn't there anymore. Refresh the page.")
    return path


def clip_state(name):
    if (EDITS / name).is_file():
        return "review"
    if (READY / name).is_file():
        return "approved"
    return "gone"


def clip_caption(path):
    side = path.with_suffix(".txt")
    if not side.exists():
        return ""
    return side.read_text(encoding="utf-8-sig", errors="replace").partition("\n\n---\n")[0].strip()[:600]


def review_clip(action, name):
    """approve: edits to ready (like the panel Keep). skip: to control-panel/deleted (restorable, like Delete)."""
    path = clip_file(name)
    if action == "approve":
        dest = READY / path.name
    else:
        dest = DELETED / uuid.uuid4().hex / path.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() or dest.with_suffix(".txt").exists():
        raise ValueError("A clip with that name is already in media\\ready.")
    side = path.with_suffix(".txt")
    if side.exists():
        side.rename(dest.with_suffix(".txt"))
    try:
        path.rename(dest)
    except OSError:
        if dest.with_suffix(".txt").exists():
            dest.with_suffix(".txt").rename(side)
        raise ValueError("The PC is still using that file. Try again in a moment.")
    log(f"Phone {'approved' if action == 'approve' else 'skipped'} {name} -> {dest.parent}")
    return str(dest)


# ---------- web ----------
URL_RE = re.compile(r"https?://[^\s<>\"']+")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def allowed(self):
        # Only this PC, which includes `tailscale serve` relaying your own tailnet devices (phone).
        return self.client_address[0] in ("127.0.0.1", "::1")

    def send(self, body, kind="application/json", status=200):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def json(self, data, status=200):
        self.send(json.dumps(data), status=status)

    def video(self, path):
        size = path.stat().st_size
        start, end = 0, size - 1
        rng = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
        if rng and (rng.group(1) or rng.group(2)):
            if rng.group(1):
                start = int(rng.group(1))
                end = min(int(rng.group(2)), size - 1) if rng.group(2) else size - 1
            else:
                start = max(0, size - int(rng.group(2)))
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        if self.command == "HEAD":
            return
        with open(path, "rb") as f:
            f.seek(start)
            left = end - start + 1
            try:
                while left:
                    chunk = f.read(min(left, 1 << 20))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
            except (ConnectionError, OSError):
                pass

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self.allowed():
            return self.send("forbidden", "text/plain", 403)
        route = urlsplit(self.path)
        if route.path in ("/", "/index.html") and self.command == "GET":
            log("Phone opened the inbox page.")
            page = PAGE.read_text(encoding="utf-8").replace("__APP__", brand.app())
            return self.send(page.encode(), "text/html; charset=utf-8")
        if route.path == "/manifest.json":
            name = f"{brand.app()} Inbox"
            return self.json({"name": name, "short_name": name, "start_url": "/", "display": "standalone",
                              "background_color": "#111111", "theme_color": "#111111"})
        if route.path == "/api/items":
            rows = [r for r in items() if r["status"] != "removed"]
            rows.sort(key=lambda r: r["added"], reverse=True)
            rows = rows[:40]
            for r in rows:
                r["reels"] = []
                for name in r.get("clips") or []:
                    name, job = reclip.resolve(name)  # a re-cut Reel replaces the one it came from
                    state = clip_state(name)
                    path = EDITS / name if state == "review" else READY / name
                    redo = {}
                    if job and job.get("status") in ("queued", "working"):
                        redo = {"redo": "working", "redo_text": reclip.describe(job.get("earlier", 0), job.get("later", 0))}
                    elif job and job.get("status") == "failed":
                        redo = {"redo": "failed", "redo_text": job.get("error", "")}
                    old = reclip.made_from(name)
                    if old:
                        redo["redo_from"] = reclip.describe(old.get("earlier", 0), old.get("later", 0))
                    r["reels"].append({"name": name, "state": state,
                                       "area": "edits" if state == "review" else "ready",
                                       "caption": clip_caption(path) if state != "gone" else "", **redo})
            return self.json({"items": rows, "mine": config()["my_accounts"]})
        if route.path == "/video":
            q = {k: v[-1] for k, v in parse_qs(route.query).items()}
            try:
                return self.video(clip_file(q.get("name", ""), q.get("area", "edits")))
            except ValueError as exc:
                return self.send(str(exc), "text/plain", 404)
        if route.path == "/health":
            return self.json({"ok": True, "app": "vvp-phone-inbox"})
        self.send("not found", "text/plain", 404)

    def do_POST(self):
        if not self.allowed():
            return self.send("forbidden", "text/plain", 403)
        route = urlsplit(self.path)
        q = {k: v[-1] for k, v in parse_qs(route.query).items()}
        length = int(self.headers.get("Content-Length") or 0)
        try:
            if route.path == "/api/upload":
                return self.json(self.upload(q, length))
            if length > 100_000:
                raise ValueError("Request too large.")
            raw = self.rfile.read(length).decode("utf-8", "replace") if length else ""
            kind = self.headers.get("Content-Type", "")
            if "json" in kind:
                data = json.loads(raw or "{}")
            elif "x-www-form-urlencoded" in kind:
                data = {k: v[-1] for k, v in parse_qs(raw).items()}
            else:  # plain text, e.g. an iOS Shortcut sending the shared link as the body
                data = {"text": raw}
            data = {**q, **data}
            if route.path == "/api/add":
                return self.json(self.add(data))
            if route.path == "/api/yes":
                return self.json(self.said_yes(data))
            if route.path == "/api/reclip":
                name = data.get("name", "")
                clip_file(name)
                message = reclip.start(name, data.get("earlier") or 0, data.get("later") or 0)
                log(f"Phone asked to re-cut {name}: earlier {data.get('earlier') or 0}, later {data.get('later') or 0}")
                return self.json({"ok": True, "message": message})
            if route.path in ("/api/approve", "/api/skip"):
                where = review_clip(route.path.rsplit("/", 1)[1], data.get("name", ""))
                return self.json({"ok": True, "moved_to": where})
            if route.path == "/api/retry":
                row = next((r for r in items() if r["id"] == data.get("id")), None)
                if not row or not row["status"].startswith("failed"):
                    raise ValueError("Only failed items can be retried.")
                if row["kind"] == "file" and not Path(row["file"]).is_file():
                    update(row["id"], kind="link")
                update(row["id"], status="queued")
                WAKE.set()
                return self.json({"ok": True})
            if route.path == "/api/whole":
                return self.json(self.whole_choice(data))
            if route.path == "/api/remove":
                return self.json({"ok": bool(update(data.get("id", ""), status="removed"))})
            self.send("not found", "text/plain", 404)
        except (ValueError, KeyError) as exc:
            log(f"Phone request to {route.path} was refused: {exc}")
            self.json({"ok": False, "error": str(exc)}, 400)
        except (OSError, ConnectionError) as exc:
            log(f"Phone request to {route.path} broke off: {exc}")

    def add(self, data):
        text = " ".join(str(data.get(k, "")) for k in ("url", "text"))
        links = list(dict.fromkeys(u.rstrip(").,]") for u in URL_RE.findall(text)))
        if not links:
            raise ValueError("No link found. Copy the post's link and paste it here.")
        whose = "mine" if str(data.get("whose", "mine")).lower().startswith(("mine", "my", "own")) else "other"
        guide = str(data.get("guide", "")).lower() in ("1", "true", "on", "yes")
        whole = str(data.get("whole", "")).lower() in ("1", "true", "on", "yes")
        added, errors = [], []
        for url in links[:10]:
            try:
                added.append(add_item(kind="link", url=url, whose=whose, guide=guide, whole=whole,
                                      platform=platform_from_url(url))["id"])
            except ValueError as exc:
                errors.append(f"{url} is {exc}")
        log(f"Phone sent {len(added)} link(s) ({whose}{', whole video' if whole else ''}).")
        if not added:
            raise ValueError("; ".join(errors))
        return {"ok": True, "added": added, "errors": errors,
                "message": f"Got it. {len(added)} clip{'s' if len(added) != 1 else ''} queued."}

    def upload(self, q, length):
        if not length or length > MAX_UPLOAD:
            raise ValueError("Send one video file up to 1 GB.")
        whose = "mine" if q.get("whose", "mine").startswith("mine") else "other"
        creator = q.get("creator", "").strip().lstrip("@")
        if whose == "other" and not creator:
            raise ValueError("Whose clip is it? Add their @handle so we can credit and ask them.")
        WORK.mkdir(parents=True, exist_ok=True)
        ext = (Path(q.get("name", "")).suffix or ".mp4").lower()
        if ext not in (".mp4", ".mov", ".m4v", ".webm", ".mkv"):
            ext = ".mp4"
        target = WORK / f"{dt.datetime.now():%Y%m%d-%H%M%S}_{uuid.uuid4().hex[:6]}{ext}"
        with open(target, "wb") as f:
            left = length
            while left:
                chunk = self.rfile.read(min(left, 1 << 20))
                if not chunk:
                    break
                f.write(chunk)
                left -= len(chunk)
        if left:
            target.unlink(missing_ok=True)
            raise ValueError(f"The upload was cut off ({(length - left) / 1e6:.1f} of {length / 1e6:.1f} MB). "
                             "Keep the page open until it says it got the video, then try again.")
        if ext != ".mp4":  # Clip Maker and review expect MP4 (iPhone videos arrive as .mov)
            prepare_ffmpeg()
            mp4 = target.with_suffix(".mp4")
            r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(target), "-c:v", "libx264", "-crf", "18",
                                "-pix_fmt", "yuv420p", "-c:a", "aac", str(mp4)], capture_output=True,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if r.returncode == 0:
                target.unlink(missing_ok=True)
                target = mp4
        row = add_item(kind="file", file=str(target), whose=whose, creator=creator,
                       platform=q.get("platform") or ("instagram" if creator else "upload"),
                       guide=q.get("guide", "") in ("1", "true", "on"), title=q.get("title", ""),
                       whole=q.get("whole", "") in ("1", "true", "on"),
                       note=q.get("name", "uploaded file"))
        log(f"Phone uploaded {q.get('name', 'a video')} ({length / 1e6:.1f} MB, {whose}).")
        return {"ok": True, "added": [row["id"]], "message": "Got the video. It's queued."}

    def whole_choice(self, data):
        """A whole video over 90 s: split into parts, keep the first 90 s, or go back to the best moments."""
        row = next((r for r in items() if r["id"] == data.get("id")), None)
        if not row or row["status"] != "needs choice":
            raise ValueError("That clip isn't waiting on a choice.")
        mode = str(data.get("mode", ""))
        if mode not in ("parts", "cap", "moments"):
            raise ValueError("Pick parts, first 90 s or best moments.")
        if not Path(row.get("file", "")).is_file():
            raise ValueError("The video isn't on the PC anymore. Send it again.")
        if mode == "moments":
            update(row["id"], status="queued", whole=False, whole_mode="")
        else:
            update(row["id"], status="queued", whole_mode=mode)
        log(f"Phone picked '{mode}' for the long whole video {row['id']}.")
        WAKE.set()
        return {"ok": True}

    def said_yes(self, data):
        row = next((r for r in items() if r["id"] == data.get("id")), None)
        if not row or row["status"] != "waiting permission" or not row.get("creator"):
            raise ValueError("That clip isn't waiting on permission.")
        record_creator(row["platform"], row["creator"], "yes", f"approved {dt.date.today().isoformat()} (owner tapped Approved on the phone: they asked the creator)")
        log(f"Marked @{row['creator']} ({row['platform']}) as yes from the phone.")
        WAKE.set()
        return {"ok": True}


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False  # on Windows reuse would let a second copy bind the same port
    allow_reuse_port = False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=config()["port"])
    opts = ap.parse_args()
    for folder in (WORK, HOLD, EDITS):
        folder.mkdir(parents=True, exist_ok=True)
    with LOCK:  # anything interrupted mid-way goes back in the queue
        rows = items()
        for r in rows:
            if r["status"] in ("downloading", "clipping"):
                r["status"] = "queued"
                if r["kind"] == "file" and not Path(r.get("file", "")).is_file():
                    r["kind"] = "link"
        write_json(ITEMS, rows)
    try:
        server = Server(("127.0.0.1", opts.port), Handler)
    except OSError:
        print(f"The phone inbox is already running on port {opts.port}.")
        return
    threading.Thread(target=worker, daemon=True, name="inbox-worker").start()
    log(f"Phone inbox running at http://127.0.0.1:{opts.port}  (phone: use your Tailscale link, see inbox\\README.md)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
