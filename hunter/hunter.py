"""
ReelHound Video Hunter
Finds newly posted videos in your niche, ranks them, downloads the ones you're
allowed to use into media/raw, and queues the rest with a ready-to-send
permission message.

  python hunter.py            run once
  python hunter.py --loop     keep running (every N minutes from config.json)
  python hunter.py --loop --open   same, and open the finds page with its Yes buttons

While it runs with --loop, the finds page is served at http://localhost:8765 (this PC only).
Clicking "Yes" there adds the creator to creators.csv and downloads their queued videos.
"""
import argparse, csv, datetime as dt, html, json, math, os, queue, re, secrets, shutil, subprocess, sys, threading, time
import webbrowser
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import xml.etree.ElementTree as ET

try:
    import requests
except ImportError:
    print("[hunter] Missing 'requests'. Run setup.bat in the repo root.")
    sys.exit(1)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, ROOT)
import brand  # noqa: E402  (name, handle, niche label, permission message wording)

RAW = os.path.join(ROOT, "media", "raw")
CONFIG = os.path.join(HERE, "config.json")
CREATORS = os.path.join(HERE, "creators.csv")
STATE = os.path.join(HERE, "seen.json")
FINDS = os.path.join(HERE, "finds.csv")
PAGE = os.path.join(HERE, "finds.html")
UA = f"{brand.app()}/{brand.company()} (personal clipping tool)"
CREATOR_FIELDS = ["platform", "handle", "channel_id", "permission", "contact", "notes"]
TOKEN_SLOT = "__HUNTER_TOKEN__"
FILE_LOCK = threading.RLock()    # finds.csv, finds.html and creators.csv
WORK_LOCK = threading.Lock()     # one download/clip job at a time
DL_QUEUE = queue.Queue()
FIELDS = ["found_at", "score", "platform", "title", "creator", "creator_id", "url", "published",
          "views", "likes", "comments", "duration_s", "permission", "action", "file", "id"]

# Scoring defaults. Every one of these can be replaced in hunter/config.json:
#   "score_words": {...}   word -> points for titles that contain it
#   "block_words": [...]   titles with any of these score 0 and are skipped
#   "must_include": [...]  if set, only titles containing one of these are kept
#   "priority_words": []   titles with any of these get 5 bonus points
SCORE_WORDS = {
    "secret": 7, "hidden": 7, "trick": 7, "tips": 7, "how to": 7, "guide": 6, "tutorial": 6,
    "best": 5, "insane": 5, "crazy": 5, "unbelievable": 6, "shocking": 5, "wtf": 5,
    "funny": 8, "fail": 6, "fails": 6, "lol": 4, "reaction": 4, "prank": 5,
    "before": 4, "after": 4, "vs": 4, "first": 4, "new": 3, "revealed": 5, "explained": 5,
    "clip": 4, "viral": 5, "moment": 4, "highlight": 4,
}
BLOCK_WORDS = ["leak", "leaked", "datamine", "datamined", "free download", "crack", "pirat",
               "mod menu", "early access hack", "play early", "telegram", "giveaway link"]



# ---------- helpers ----------
def now():
    return dt.datetime.now(dt.timezone.utc)


def parse_time(s):
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return now()


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def iso_duration(s):
    m = re.match(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s or "")
    if not m:
        return 0
    d, h, mi, se = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + se


def norm(name):
    """Compare creator names loosely: no @, no case, no '(from caption)'."""
    return re.sub(r"\s*\(from caption\)$", "", (name or "").strip()).strip().lower().lstrip("@")


def load_creators():
    """creators.csv: platform,handle,channel_id,permission,contact,notes
    permission: own | yes | asked | no | unknown"""
    out = {}
    if not os.path.exists(CREATORS):
        return out
    with FILE_LOCK, open(CREATORS, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            perm = (row.get("permission") or "unknown").strip().lower()
            for key in (row.get("handle"), row.get("channel_id")):
                if key and key.strip():
                    out[((row.get("platform") or "").strip().lower(), norm(key))] = dict(row, permission=perm)
    return out


def permission_for(item, creators):
    for key in (item["creator_id"], item["creator"]):
        c = creators.get((item["platform"], norm(key)))
        if c:
            return c["permission"]
    return "unknown"


# ---------- sources ----------
def youtube_search(cfg, state):
    key = cfg.get("youtube_api_key", "").strip()
    if not key or key.startswith("PASTE"):
        return []
    kws = cfg["keywords"]
    per_run = max(1, int(cfg.get("keywords_per_run", 2)))
    start = state.get("kw_index", 0) % len(kws)
    picked = [kws[(start + i) % len(kws)] for i in range(per_run)]
    state["kw_index"] = start + per_run
    since = (now() - dt.timedelta(hours=cfg.get("lookback_hours", 12))).strftime("%Y-%m-%dT%H:%M:%SZ")
    ids = []
    for q in picked:
        r = requests.get("https://www.googleapis.com/youtube/v3/search", timeout=20, params=dict(
            key=key, q=q, part="snippet", type="video", order="viewCount", publishedAfter=since,
            maxResults=25, relevanceLanguage="en", safeSearch="none"))
        if r.status_code != 200:
            print(f"[hunter] YouTube search failed ({r.status_code}): {r.text[:200]}")
            continue
        ids += [it["id"]["videoId"] for it in r.json().get("items", [])]
    return youtube_details(key, ids)


def youtube_rss(cfg, creators):
    """Watch creator channels (no API key needed)."""
    out = []
    # Only real channel IDs (UC + 22 chars); skips placeholders like PASTE_YOUR_YOUTUBE_CHANNEL_ID.
    chans = {c["channel_id"].strip() for (p, _), c in creators.items() if p == "youtube"
             and re.fullmatch(r"UC[A-Za-z0-9_-]{22}", (c.get("channel_id") or "").strip())}
    for cid in chans:
        try:
            r = requests.get(f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}", timeout=20, headers={"User-Agent": UA})
            root = ET.fromstring(r.content)
        except Exception as e:
            print(f"[hunter] Couldn't read channel {cid}: {e}")
            continue
        ns = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015",
              "media": "http://search.yahoo.com/mrss/"}
        for e in root.findall("a:entry", ns):
            vid = e.findtext("yt:videoId", namespaces=ns)
            stats = e.find("media:group/media:community/media:statistics", ns)
            out.append(dict(id="yt:" + vid, platform="youtube", title=e.findtext("a:title", namespaces=ns) or "",
                            creator=e.findtext("a:author/a:name", namespaces=ns) or "", creator_id=cid,
                            url=f"https://www.youtube.com/watch?v={vid}", published=e.findtext("a:published", namespaces=ns),
                            views=int(stats.get("views", 0)) if stats is not None else 0, likes=0, comments=0, duration_s=0))
    key = cfg.get("youtube_api_key", "").strip()
    if key and not key.startswith("PASTE") and out:
        # fill in real stats and durations (1 quota unit per 50 videos)
        detailed = {d["id"]: d for d in youtube_details(key, [o["id"][3:] for o in out])}
        out = [detailed.get(o["id"], o) for o in out]
    return out


def youtube_details(key, ids):
    out = []
    for i in range(0, len(ids), 50):
        r = requests.get("https://www.googleapis.com/youtube/v3/videos", timeout=20, params=dict(
            key=key, id=",".join(ids[i:i + 50]), part="snippet,statistics,contentDetails"))
        if r.status_code != 200:
            print(f"[hunter] YouTube details failed ({r.status_code})")
            continue
        for v in r.json().get("items", []):
            sn, st = v["snippet"], v.get("statistics", {})
            out.append(dict(id="yt:" + v["id"], platform="youtube", title=sn["title"], creator=sn["channelTitle"],
                            creator_id=sn["channelId"], url=f"https://www.youtube.com/watch?v={v['id']}",
                            published=sn["publishedAt"], views=int(st.get("viewCount", 0)),
                            likes=int(st.get("likeCount", 0)), comments=int(st.get("commentCount", 0)),
                            duration_s=iso_duration(v["contentDetails"].get("duration"))))
    return out


_REDDIT_TOKEN = {"value": "", "expires": 0.0}
_REDDIT_WARNED = {"done": False}


def reddit_token(rc):
    """App-only OAuth token. Reddit refuses anonymous JSON requests (403) since late 2026."""
    if _REDDIT_TOKEN["value"] and time.time() < _REDDIT_TOKEN["expires"] - 60:
        return _REDDIT_TOKEN["value"]
    r = requests.post("https://www.reddit.com/api/v1/access_token", data={"grant_type": "client_credentials"},
                      auth=(rc["client_id"], rc["client_secret"]), headers={"User-Agent": UA}, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"sign-in refused (HTTP {r.status_code}); check the Reddit app ID and secret")
    d = r.json()
    _REDDIT_TOKEN.update(value=d["access_token"], expires=time.time() + int(d.get("expires_in", 3600)))
    return _REDDIT_TOKEN["value"]


def reddit(cfg):
    out = []
    rc = cfg.get("reddit") or {}
    if not ((rc.get("client_id") or "").strip() and (rc.get("client_secret") or "").strip()
            and not rc["client_id"].startswith("PASTE")):
        if not _REDDIT_WARNED["done"]:
            print("[hunter] Reddit skipped: Reddit now needs an app ID and secret (Hunter settings > Reddit app).")
            _REDDIT_WARNED["done"] = True
        return out
    try:
        token = reddit_token(rc)
    except Exception as e:
        print(f"[hunter] Reddit failed: {e}")
        return out
    for sub in cfg.get("subreddits", []):
        try:
            r = requests.get(f"https://oauth.reddit.com/r/{sub}/hot?limit=50&raw_json=1", timeout=20,
                             headers={"User-Agent": UA, "Authorization": "Bearer " + token})
            r.raise_for_status()
            posts = r.json()["data"]["children"]
        except Exception as e:
            print(f"[hunter] Reddit r/{sub} failed: {e}")
            continue
        for p in posts:
            d = p["data"]
            if not d.get("is_video") or d.get("over_18") or d.get("stickied"):
                continue
            out.append(dict(id="rd:" + d["id"], platform="reddit", title=d["title"], creator=d["author"],
                            creator_id=d["author"], url="https://www.reddit.com" + d["permalink"],
                            published=dt.datetime.fromtimestamp(d["created_utc"], dt.timezone.utc).isoformat(),
                            views=0, likes=int(d.get("ups", 0)), comments=int(d.get("num_comments", 0)),
                            duration_s=int(((d.get("media") or {}).get("reddit_video") or {}).get("duration", 0))))
    return out


def instagram(cfg, state):
    """Instagram hashtag search (official Graph API, Business accounts).
    Finds Reels only; never downloads them (always 'ask permission')."""
    ig = cfg.get("instagram", {})
    token, uid = ig.get("access_token", "").strip(), ig.get("ig_user_id", "").strip()
    if not token or not uid or token.startswith("PASTE") or uid.startswith("PASTE"):
        return []
    base = f"https://graph.facebook.com/{ig.get('graph_version', 'v23.0')}"
    tag_ids = state.setdefault("ig_tag_ids", {})
    out = []
    for tag in ig.get("hashtags", []):
        tag = tag.lstrip("#").lower()
        if tag not in tag_ids:  # each new hashtag counts toward Meta's 30-per-week limit, so cache ids
            r = requests.get(base + "/ig_hashtag_search", timeout=20, params=dict(user_id=uid, q=tag, access_token=token))
            if r.status_code != 200:
                print(f"[hunter] Instagram #{tag} lookup failed: {r.text[:200]}")
                continue
            data = r.json().get("data") or []
            if not data:
                continue
            tag_ids[tag] = data[0]["id"]
        for edge in ("top_media", "recent_media"):
            r = requests.get(f"{base}/{tag_ids[tag]}/{edge}", timeout=20, params=dict(
                user_id=uid, access_token=token, limit=50,
                fields="id,caption,media_type,permalink,like_count,comments_count,timestamp"))
            if r.status_code != 200:
                print(f"[hunter] Instagram #{tag} {edge} failed: {r.text[:200]}")
                continue
            for m in r.json().get("data", []):
                if m.get("media_type") != "VIDEO":
                    continue
                cap = (m.get("caption") or "").strip()
                mention = re.search(r"@([A-Za-z0-9_.]{2,30})", cap)
                out.append(dict(id="ig:" + m["id"], platform="instagram",
                                title=(cap.splitlines()[0] if cap else "Instagram Reel")[:140] + f" #{tag}",
                                creator="see post" if not mention else "@" + mention.group(1) + " (from caption)",
                                creator_id="", url=m["permalink"], published=m.get("timestamp") or now().isoformat(),
                                views=0, likes=int(m.get("like_count") or 0), comments=int(m.get("comments_count") or 0),
                                duration_s=0))
    return out


# ---------- scoring ----------
def score(item, cfg=None):
    """Rank a find 0-100. Tune it in config.json: see SCORE_WORDS above."""
    cfg = cfg or {}
    title = (item["title"] or "").lower()
    must = [w.strip().lower() for w in cfg.get("must_include", []) if str(w).strip()]
    if must and not any(word in title for word in must):
        return 0
    blocked = cfg.get("block_words") or BLOCK_WORDS
    if any(str(b).lower() in title for b in blocked if str(b)):
        return 0
    age_h = max((now() - parse_time(item["published"])).total_seconds() / 3600, 0.5)
    if item["platform"] in ("reddit", "instagram"):
        heat = (item["likes"] + 3 * item["comments"]) / age_h
        heat_pts = min(45, 9 * math.log10(1 + heat * 10))
    else:
        vph = item["views"] / age_h
        heat_pts = min(45, 9 * math.log10(1 + vph))
        if item["views"] > 0:
            eng = (item["likes"] + 2 * item["comments"]) / item["views"]
            heat_pts += min(10, eng * 200)
    words = dict(SCORE_WORDS)
    for key, value in (cfg.get("score_words") or {}).items():
        try:
            words[str(key).lower()] = float(value)
        except (TypeError, ValueError):
            continue  # a bad number in config.json shouldn't break a scan
    niche = min(25, sum(w for k, w in words.items() if k in title))
    fresh = max(0, 15 - age_h)                  # newer is better
    priority = 0 if not any(str(w).lower() in title for w in cfg.get("priority_words", []) if str(w)) else 5
    length = 0 if not item["duration_s"] else (5 if item["duration_s"] <= 1200 else 0)
    return round(min(100, heat_pts + niche + fresh + priority + length))


def permission_message(item):
    who = item["creator"]
    return (f"Hey {who}! Love your video \"{item['title'][:70]}\". I run {brand.channel()}, "
            f"a {brand.niche()} page. Ok if we cut a short clip from it with full credit to you on screen and in "
            f"the caption? Happy to tag you. No worries if not!")


# ---------- download ----------
def download(item, cfg):
    if not shutil.which("yt-dlp") and not _has_module("yt_dlp"):
        return "", "yt-dlp not installed"
    os.makedirs(RAW, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9]+", "-", item["creator"])[:30].strip("-")
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M")
    base = os.path.join(RAW, f"{stamp}_{item['platform']}_{safe}_{item['id'].split(':')[1]}")
    cmd = [sys.executable, "-m", "yt_dlp", "-f", "bv*[height<=1080]+ba/b[height<=1080]/b", "--merge-output-format", "mp4",
           "--remux-video", "mp4", "--no-mtime", "--no-playlist", "-o", base + ".%(ext)s"]
    extra, temp = cookie_args(cfg)
    cmd += extra
    cmd.append(item["url"])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    finally:
        if temp:
            try:
                os.remove(temp)
            except OSError:
                pass
    if r.returncode != 0:
        return "", "download failed: " + explain_download_error(r.stderr)
    if not os.path.isfile(base + ".mp4"):
        return "", "download failed: no MP4 was produced"
    with open(base + ".source.json", "w", encoding="utf-8") as f:
        json.dump(dict(item, credit="@" + item["creator"].lstrip("@")), f, indent=2)
    return base + ".mp4", "downloaded"


# ---------- YouTube sign-in cookies ----------
SIGNED_IN = ("SAPISID", "__Secure-1PSID", "__Secure-3PSID", "LOGIN_INFO", "SID")


def cookies_path(cfg):
    cfile = (cfg.get("cookies_file") or "").strip()
    if cfile and not os.path.isabs(cfile):
        cfile = os.path.join(os.path.dirname(os.path.abspath(__file__)), cfile)
    return cfile if cfile and os.path.isfile(cfile) else ""


def cookies_signed_in(path):
    """True when the cookies.txt export still holds the sign-in cookies (names only, values never read)."""
    names = set()
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 7 and "youtube.com" in parts[0]:
                    names.add(parts[5])
    except OSError:
        return False
    return {"SAPISID", "LOGIN_INFO"} <= names or {"SAPISID", "__Secure-1PSID"} <= names


def cookie_args(cfg):
    """yt-dlp cookie arguments, and a temp file to delete afterwards.
    YouTube bot check (2026-11-22): cookies_file (a cookies.txt export) wins over cookies_from_browser
    (e.g. "chrome"). yt-dlp writes the cookie jar back into the --cookies file after every run, so when
    YouTube rotates the session it erased the export's sign-in cookies (2026-11-23 08:34). It now gets a
    throwaway copy, so the export you saved is never changed."""
    cfile = cookies_path(cfg)
    if cfile:
        import tempfile
        fd, temp = tempfile.mkstemp(prefix="vvp-cookies-", suffix=".txt")
        os.close(fd)
        shutil.copyfile(cfile, temp)
        return ["--cookies", temp], temp
    if (cfg.get("cookies_from_browser") or "").strip():
        return ["--cookies-from-browser", cfg["cookies_from_browser"].strip()], ""
    return [], ""


def explain_download_error(stderr):
    err = (stderr.strip().splitlines() or ["?"])[-1]
    if re.search(r"confirm you.?re not a bot|sign in to confirm", stderr, re.I):
        return ("YouTube bot check: the cookies are signed out or expired. Export fresh cookies from a "
                "private window to hunter\\youtube_cookies.txt (see hunter\\README)")
    return err[:150]


def _has_module(name):
    try:
        __import__(name)
        return True
    except ImportError:
        return False


# ---------- output ----------
def ago(ts):
    h = (now() - parse_time(ts)).total_seconds() / 3600
    return f"{int(h * 60)} min ago" if h < 1 else f"{h:.0f} h ago" if h < 48 else f"{h / 24:.0f} days ago"


def append_finds(rows):
    new_file = not os.path.exists(FINDS)
    with FILE_LOCK, open(FINDS, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        if new_file:
            w.writeheader()
        w.writerows(rows)


def tiktok_block():
    names = sorted({c["handle"] for (p, _), c in load_creators().items() if p == "tiktok" and c.get("handle")})
    if not names:
        return ""
    links = " ".join(f"<a href='https://www.tiktok.com/@{html.escape(n.lstrip('@'))}' target=_blank>@{html.escape(n.lstrip('@'))}</a>" for n in names)
    return f"<p class=m>TikTok creators to check by hand: {links}</p>"


def read_finds():
    if not os.path.exists(FINDS):
        return []
    with FILE_LOCK, open(FINDS, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_finds(rows):
    with FILE_LOCK:
        tmp = FINDS + ".tmp"
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        os.replace(tmp, FINDS)


def write_page():
    with FILE_LOCK:
        _write_page()


def _write_page():
    rows = read_finds()
    cutoff = now() - dt.timedelta(hours=48)
    rows = [r for r in rows if parse_time(r["found_at"]) > cutoff]
    rows.sort(key=lambda r: int(r["score"] or 0), reverse=True)
    badge = {"downloaded": "#1db954", "ask permission": "#f5a623", "skipped": "#777", "approved": "#7cc4ff",
             "creator said yes": "#7cc4ff"}
    trs = []
    for r in rows[:600]:
        act = r["action"].split(":")[0].split(" (")[0]
        msg = html.escape(permission_message(dict(r)), quote=True)
        if act == "ask permission":
            extra = (f'<button onclick="navigator.clipboard.writeText(this.dataset.m);this.textContent=\'Copied\'" '
                     f'data-m="{msg}">Copy permission message</button>')
            if norm(r["creator"]) and r["creator"] != "see post":
                extra += (f' <button class=yes onclick="sayYes(this)" data-p="{html.escape(r["platform"], quote=True)}" '
                          f'data-c="{html.escape(r["creator"], quote=True)}" data-id="{html.escape(r["creator_id"], quote=True)}">'
                          f'Yes, they said ok</button>')
        else:
            extra = f'<code>{html.escape(os.path.basename(r["file"]))}</code>' if r["file"] else ""
        key = html.escape(r["platform"] + ":" + (r["creator_id"] or norm(r["creator"])), quote=True)
        trs.append(f"<tr data-k=\"{key}\" data-who=\"{html.escape(r['creator'].lower(), quote=True)}\">"
                   f"<td class=s>{r['score']}</td><td>{html.escape(r['platform'])}</td>"
                   f"<td><a href='{html.escape(r['url'])}' target=_blank>{html.escape(r['title'])}</a>"
                   f"<div class=m>{html.escape(r['creator'])} · {int(r['views'] or 0):,} views · {ago(r['published'])}</div></td>"
                   f"<td class=a><span class=b style='background:{badge.get(act, '#777')}'>{html.escape(r['action'])}</span></td><td class=x>{extra}</td></tr>")
    page = f"""<!doctype html><meta charset=utf-8><meta http-equiv=refresh content=300>
<title>{brand.app()} finds</title>
<style>body{{font:14px system-ui;background:#111;color:#eee;margin:24px}}h1{{font-size:20px}}
table{{border-collapse:collapse;width:100%}}td{{padding:8px;border-bottom:1px solid #2a2a2a;vertical-align:top}}
a{{color:#7cc4ff;text-decoration:none}}.m{{color:#999;font-size:12px;margin-top:3px}}.s{{font-weight:700;font-size:18px;color:#ffd166}}
.b{{padding:2px 8px;border-radius:10px;color:#111;font-size:12px;font-weight:600}}button{{background:#333;color:#eee;border:1px solid #555;border-radius:6px;padding:4px 8px;cursor:pointer;margin:2px 0}}
button.yes{{background:#1d5c34;border-color:#1db954}}#q{{background:#222;color:#eee;border:1px solid #555;border-radius:6px;padding:6px 10px;width:260px}}
#warn{{background:#5c1d1d;padding:8px 12px;border-radius:6px;display:none}}</style>
<h1>{brand.app()} video finds (last 48 hours)</h1>
<p class=m>Updated {dt.datetime.now().strftime('%b %d, %I:%M %p')}. Green = downloaded to media/raw. Orange = ask the creator first.
When a creator says ok, click <b>Yes, they said ok</b>: they go on your yes list in creators.csv and their videos download right away.</p>
<p id=warn>The Yes buttons only work while the hunter window is open. Double-click start_hunter.bat, then use the page it opens (http://localhost:8765).</p>
<p><input id=q placeholder="Find a creator..." oninput="filt(this.value)"></p>
{tiktok_block()}<table>{''.join(trs) or '<tr><td>No finds yet.</td></tr>'}</table>
<script>
const TOKEN = "{TOKEN_SLOT}";
const live = location.protocol.startsWith("http") && !TOKEN.startsWith("__");
if (!live) document.getElementById("warn").style.display = "block";
function filt(q) {{
  q = q.trim().toLowerCase();
  document.querySelectorAll("tr[data-who]").forEach(tr => tr.style.display = !q || tr.dataset.who.includes(q) ? "" : "none");
}}
async function sayYes(btn) {{
  if (!live) {{ document.getElementById("warn").style.display = "block"; btn.textContent = "Open the hunter first (see red note)"; return; }}
  btn.disabled = true; btn.textContent = "Saving...";
  try {{
    const r = await fetch("/approve", {{method: "POST", headers: {{"Content-Type": "application/json", "X-Hunter-Token": TOKEN}},
      body: JSON.stringify({{platform: btn.dataset.p, creator: btn.dataset.c, creator_id: btn.dataset.id}})}});
    const d = await r.json();
    if (!d.ok) throw new Error(d.message);
    const k = btn.closest("tr").dataset.k, cell = btn.closest("td");
    document.querySelectorAll("tr[data-k]").forEach(tr => {{
      if (tr.dataset.k !== k) return;
      tr.querySelector("td.a").innerHTML = "<span class=b style='background:#7cc4ff'>" + d.label + "</span>";
      tr.querySelector("td.x").textContent = "";
    }});
    cell.textContent = d.message;
  }} catch (e) {{
    btn.disabled = false; btn.textContent = "Didn't save: " + (e.message || "hunter not running") + ". Try again";
  }}
}}
</script>"""
    with open(PAGE, "w", encoding="utf-8") as f:
        f.write(page)


# ---------- Yes button: approve a creator ----------
def approve_creator(platform, creator, creator_id, defer=False):
    """Put the creator on the yes list in creators.csv (no duplicates), then queue their videos."""
    platform = (platform or "").strip().lower()
    handle = re.sub(r"\s*\(from caption\)$", "", (creator or "").strip()).strip()
    creator_id = (creator_id or "").strip()
    if platform not in ("youtube", "reddit", "instagram", "tiktok") or not norm(handle) or handle == "see post":
        return dict(ok=False, message="couldn't tell who the creator is")
    today = dt.date.today().isoformat()
    keys = {k for k in (norm(handle), norm(creator_id)) if k}
    with FILE_LOCK:
        rows, fields = [], list(CREATOR_FIELDS)
        if os.path.exists(CREATORS):
            with open(CREATORS, encoding="utf-8-sig") as f:
                rd = csv.DictReader(f)
                fields = rd.fieldnames or fields
                rows = list(rd)
        for col in CREATOR_FIELDS:
            if col not in fields:
                fields.append(col)
        match = next((r for r in rows if (r.get("platform") or "").strip().lower() == platform and
                      keys & {norm(r.get("handle")), norm(r.get("channel_id"))}), None)
        was = (match.get("permission") or "").strip().lower() if match else ""
        if match is None:
            rows.append(dict(platform=platform, handle=handle, channel_id=creator_id if platform == "youtube" else "",
                             permission="yes", contact="", notes=f"said yes {today} (Yes button)"))
        elif was not in ("yes", "own", "official"):
            match["permission"] = "yes"
            if platform == "youtube" and not (match.get("channel_id") or "").strip():
                match["channel_id"] = creator_id
            match["notes"] = ((match.get("notes") or "").strip() + f"; said yes {today} (Yes button)").lstrip("; ")
        try:
            tmp = CREATORS + ".tmp"
            with open(tmp, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
                w.writeheader()
                w.writerows(rows)
            os.replace(tmp, CREATORS)
        except PermissionError:
            return dict(ok=False, message="creators.csv is open in another program (like Excel). Close it")

        # their videos already on the list
        finds = read_finds()
        mine = [r for r in finds if r["platform"] == platform and r["action"].startswith("ask permission")
                and keys & {norm(r["creator"]), norm(r["creator_id"])}]
        if platform == "instagram":
            for r in mine:
                r["action"], r["permission"] = "creator said yes: save it by hand", "yes"
            label, msg = "creator said yes", "Saved. Instagram videos can't be downloaded automatically, so save this one by hand."
        else:
            for r in mine:
                r["action"], r["permission"] = "approved: downloading", "yes"
            label = "approved: downloading" if mine else "on your yes list"
            msg = (f"Saved. Queued {len(mine)} video{'s' if len(mine) != 1 else ''} for the hunter." if mine and defer else
                   f"Saved. Downloading {len(mine)} video{'s' if len(mine) != 1 else ''} now." if mine
                   else "Saved. Their new videos will download automatically.")
        if mine:
            save_finds(finds)
            if not defer and platform != "instagram":
                DL_QUEUE.put([r["id"] for r in mine])
        _write_page()
    already = " (they were already on your yes list)" if was in ("yes", "own", "official") else ""
    print(f"[hunter] {handle} added to your yes list{already}. {len(mine)} queued video(s).")
    return dict(ok=True, message=msg + already, label=label)


def download_worker(cfg):
    """Downloads videos of creators you just said yes to, then makes clips."""
    while True:
        ids = set(DL_QUEUE.get())
        with WORK_LOCK:
            todo = [r for r in read_finds() if r["id"] in ids and r["action"] == "approved: downloading"]
            results = {}
            for r in todo:
                item = dict(r, permission="yes", views=int(r["views"] or 0), likes=int(r["likes"] or 0),
                            comments=int(r["comments"] or 0), duration_s=int(r["duration_s"] or 0))
                if item["duration_s"] > cfg.get("max_video_minutes", 30) * 60:
                    results[r["id"]] = ("", "skipped: too long")
                    continue
                print(f"[hunter] Downloading {r['creator']}: {r['title'][:60]}")
                results[r["id"]] = download(item, cfg)
            with FILE_LOCK:
                finds = read_finds()
                for r in finds:
                    if r["id"] in results and r["action"] == "approved: downloading":
                        r["file"], r["action"] = results[r["id"]]
                save_finds(finds)
                _write_page()
            got = sum(1 for f, a in results.values() if a == "downloaded")
            print(f"[hunter] {got} of {len(results)} approved video(s) downloaded to media\\raw.")
            if got and cfg.get("auto_clip", True):
                try:
                    auto_clip(cfg)
                except Exception as e:
                    print(f"[hunter] Auto-clip failed: {e}")


class Page(BaseHTTPRequestHandler):
    token = ""

    def log_message(self, *a):
        pass

    def _local(self):
        host = (self.headers.get("Host") or "").split(":")[0].lower()
        return host in ("localhost", "127.0.0.1")

    def _send(self, code, body, ctype):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self._local() or self.path.split("?")[0] not in ("/", "/finds.html"):
            return self._send(404, "Not found", "text/plain")
        if not os.path.exists(PAGE):
            write_page()
        with FILE_LOCK, open(PAGE, encoding="utf-8") as f:
            page = f.read()
        self._send(200, page.replace(TOKEN_SLOT, self.token), "text/html; charset=utf-8")

    def do_POST(self):
        if not self._local() or self.path != "/approve" or self.headers.get("X-Hunter-Token") != self.token:
            return self._send(403, json.dumps(dict(ok=False, message="not allowed")), "application/json")
        try:
            n = int(self.headers.get("Content-Length") or 0)
            d = json.loads(self.rfile.read(min(n, 10000)) or b"{}")
            res = approve_creator(d.get("platform"), d.get("creator"), d.get("creator_id"))
        except Exception as e:
            res = dict(ok=False, message=f"error: {e}")
        self._send(200, json.dumps(res), "application/json")


def start_page_server(cfg, open_browser):
    port = int(cfg.get("page_port", 8765))
    url = f"http://localhost:{port}/"
    Page.token = secrets.token_urlsafe(16)
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", port), Page)
    except OSError:
        print(f"[hunter] Couldn't open the finds page on {url} (is another hunter window already open?).")
        if open_browser:
            webbrowser.open(url)
        return False
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    threading.Thread(target=download_worker, args=(cfg,), daemon=True).start()
    print(f"[hunter] Your finds page: {url}  (Yes buttons work while this window is open)")
    if open_browser:
        webbrowser.open(url)
    return True


# ---------- main ----------
def run_once(cfg, stopping=lambda: False):
    state = load_json(STATE, {"seen": {}})
    creators = load_creators()
    own_id = cfg.get("youtube_channel_id", "").strip()
    if own_id:
        for lookup, row in list(creators.items()):
            if lookup[0] == "youtube" and row["permission"] == "own" and not row.get("channel_id", "").startswith("UC"):
                creators[lookup] = dict(row, channel_id=own_id)
        creators[("youtube", norm(own_id))] = dict(channel_id=own_id, permission="own")
    sources = cfg.get("sources", {})
    items = []
    for name, fetch in (
        ("youtube", lambda: (youtube_search(cfg, state) if cfg["keywords"] else []) + youtube_rss(cfg, creators)),
        ("reddit", lambda: reddit(cfg)),
        ("instagram", lambda: instagram(cfg, state)),
    ):
        if stopping():
            break
        if sources.get(name, True):
            items.extend(fetch())
    found, dl = [], 0
    stamp = now().isoformat()
    for it in items:
        if stopping():
            break
        if it["id"] in state["seen"]:
            continue
        state["seen"][it["id"]] = stamp
        it["score"] = score(it, cfg)
        if it["score"] < cfg.get("min_score", 40):
            continue
        it["permission"] = permission_for(it, creators)
        it["found_at"], it["file"] = stamp, ""
        if it["platform"] == "instagram":
            it["action"] = "creator said yes: save it by hand" if it["permission"] in ("own", "yes", "official") else "ask permission"
        elif it["permission"] in ("own", "yes", "official"):
            if dl < cfg.get("max_downloads_per_run", 5) and (it["duration_s"] or 0) <= cfg.get("max_video_minutes", 30) * 60:
                it["file"], it["action"] = download(it, cfg)
                if not it["file"]:
                    print(f"[hunter] {it['action']}")
                dl += 1
            else:
                it["action"] = "skipped: too long or download limit reached"
        elif it["permission"] == "no":
            it["action"] = "skipped: creator said no"
        else:
            it["action"] = "ask permission" + (" (asked already)" if it["permission"] == "asked" else "")
        found.append(it)
    # forget items older than 7 days
    cutoff = now() - dt.timedelta(days=7)
    state["seen"] = {k: v for k, v in state["seen"].items() if parse_time(v) > cutoff}
    save_json(STATE, state)
    append_finds(found)
    write_page()
    print(f"[hunter] {dt.datetime.now():%I:%M %p}: checked {len(items)} videos, {len(found)} new finds, "
          f"{sum(1 for f in found if f['action'] == 'downloaded')} downloaded. Open finds.html to see them.")


def auto_clip(cfg):
    """Turn new downloads in media/raw into Reels (see clipmaker/autoclip.py)."""
    sys.path.insert(0, os.path.join(ROOT, "clipmaker"))
    import autoclip
    args = argparse.Namespace(hook="", count=int(cfg.get("clips_per_video", 3)), length=float(cfg.get("clip_seconds", 25)),
                              preset=cfg.get("clip_preset", "viral"), no_captions=False)
    autoclip.process_new(args)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true", help="keep running every N minutes")
    ap.add_argument("--open", action="store_true", help="open the finds page in your browser")
    a = ap.parse_args()
    try:
        with socket.create_connection(("127.0.0.1", 8875), timeout=0.4):
            pass
    except OSError:
        pass
    else:
        print("[hunter] The clip control panel is open. Start the hunter from its Overview page.")
        return
    cfg = load_json(CONFIG, None)
    if cfg is None:
        print("[hunter] config.json is missing or broken.")
        sys.exit(1)
    if a.loop:
        if os.path.exists(FINDS):
            write_page()  # refresh the page so older finds get Yes buttons too
        if not start_page_server(cfg, a.open):
            return
    elif a.open:
        webbrowser.open(PAGE)
    while True:
        with WORK_LOCK:
            try:
                run_once(cfg)
            except Exception as e:
                print(f"[hunter] Run failed: {e}")
            if cfg.get("auto_clip", True):
                try:
                    auto_clip(cfg)
                except Exception as e:
                    print(f"[hunter] Auto-clip failed: {e}")
        if not a.loop:
            break
        time.sleep(int(cfg.get("every_minutes", 45)) * 60)


if __name__ == "__main__":
    main()
