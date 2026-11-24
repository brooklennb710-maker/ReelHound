"""Local pre-filter for media/edits.

Scores every clip in media/edits on this PC (ffmpeg checks + a local Ollama
vision model looking at a 5-frame contact sheet) so only the strongest few
need a human or Claude look. It never moves, deletes, posts or schedules
anything. Results are cached, so re-running only scores new or changed clips.

Usage:  python review_edits.py [--model gemma4:12b] [--limit N] [--rescore] [--top 12]
                               [--wait 15] [--stop-at 01:45] [--cpu]

GPU sharing: before it starts, and before every clip, it checks that no other GPU-heavy program
(see GPU_RIVALS, e.g. ComfyUI) is running and that enough graphics memory is free. If not, it waits politely
(up to --wait minutes) or stops, keeping every score done so far. The model is unloaded from the GPU
as soon as scoring ends, so nothing sits in graphics memory afterwards.
"""
import argparse
import base64
import csv
import html
import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EDITS = ROOT / "media" / "edits"
OUT = Path(__file__).resolve().parent
SHEETS = OUT / "sheets"
CACHE = OUT / "cache.json"
RESULTS = OUT / "results.csv"
REPORT = OUT / "top.html"
CONFIG = ROOT / "hunter" / "config.json"
OLLAMA = "http://127.0.0.1:11434/api/chat"
VERSION = 4  # bump to invalidate cached scores when the prompt or scoring changes
MODEL_DEFAULT = "gemma4:12b"

sys.path.insert(0, str(ROOT))
import brand  # noqa: E402  (channel name and niche go into the prompt)

FRAME_W, FRAME_H = 270, 480

PROMPT = """You are a strict short-form video editor for {channel}, a {niche} page that posts Instagram and Facebook Reels.
The image is a contact sheet of ONE vertical clip: 5 frames left to right, taken at
{times} seconds of a {dur:.0f}-second clip. Frame 1 is what a viewer sees in the first second.
The editor's working title for the clip is: "{title}" (it may be wrong or vague; judge the frames).
Clip length is checked separately: 15-60 seconds is normal and up to 90 is fine for a guide, chase or story,
so never lower a score or list a problem just because the clip is long.

Score each item from 1 (bad) to 10 (excellent). Be harsh: most clips are average (4-6).
Only give 8+ when the frames clearly show it. A 9 or 10 means a top-1% viral clip.
Note: these clips are often 16:9 gameplay placed in the middle of a 9:16 frame over a blurred copy;
that is acceptable but the gameplay is then small, so phone should be at most 7 in that case.
- hook: does frame 1 already show something interesting, or bold on-screen text that makes the payoff obvious? Talking heads, menus, black or blurry frames, logos and intros score low.
- payoff: does the clip visibly deliver ONE specific thing (a hidden car or location, a useful trick, a surprising detail, a funny failure, a wild chase, a clear before/after)? Vague gameplay or someone just driving scores low.
- standalone: could a stranger understand it without knowing the streamer or the original video? Facecam-dominated or reaction-only frames score low.
- phone: on a phone, is the gameplay big and sharp, is burned-in text large and readable inside the frame, and is the framing clean (no letterbox bars, no cut-off text, no huge facecam covering the action)?

Also list concrete problems you can SEE (e.g. "black first frame", "facecam covers half the screen",
"caption cut off at edge", "letterboxed 16:9 inside 9:16", "menu screen", "possible story spoiler",
"blurry/low resolution", "nothing happens", "hook text cut off or unfinished", "two caption layers overlap"). Keep what_happens to one short sentence about what is
actually visible. verdict: "post" only if you would publish it as-is, "maybe" if it is close, otherwise "skip"."""

SCHEMA = {
    "type": "object",
    "properties": {
        "what_happens": {"type": "string"},
        "category": {"type": "string", "enum": ["hidden car/location", "tip/trick", "surprising detail",
                                                 "funny fail", "chase/action", "before-after", "graphics/map",
                                                 "talking/reaction", "other"]},
        "hook": {"type": "integer"},
        "payoff": {"type": "integer"},
        "standalone": {"type": "integer"},
        "phone": {"type": "integer"},
        "problems": {"type": "array", "items": {"type": "string"}},
        "verdict": {"type": "string", "enum": ["post", "maybe", "skip"]},
    },
    "required": ["what_happens", "category", "hook", "payoff", "standalone", "phone", "problems", "verdict"],
}


def run(cmd, timeout=180):
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)


def sidecar(path):
    side = path.with_suffix(".txt")
    text = side.read_text(encoding="utf-8-sig", errors="replace") if side.exists() else ""
    meta = dict(re.findall(r"^(source|range|permission|credit|preset):\s*(.+)$", text, re.M))
    caption = text.split("\n---\n", 1)[0]
    title = next((l.strip() for l in caption.splitlines() if l.strip()), path.stem)
    start = end = None
    m = re.match(r"([\d.]+)\s*to\s*([\d.]+)", meta.get("range", ""))
    if m:
        start, end = float(m.group(1)), float(m.group(2))
    return dict(title=title, caption=caption, source=meta.get("source", ""), start=start, end=end,
                permission=meta.get("permission", ""), credit=meta.get("credit", ""),
                placeholder="[1-2 sentences" in caption)


def probe(path):
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height",
             "-of", "json", str(path)])
    info = json.loads(r.stdout or "{}")
    streams = info.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    return dict(duration=float(info.get("format", {}).get("duration", 0) or 0),
                width=video.get("width", 0), height=video.get("height", 0),
                has_audio=any(s.get("codec_type") == "audio" for s in streams))


def tech_checks(path, dur):
    """One decode pass: black frames, frozen video, loudness, long silences."""
    r = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
             "-vf", f"scale={FRAME_W}:-2,blackdetect=d=0.25:pix_th=0.10,freezedetect=n=0.003:d=1.5",
             "-af", "volumedetect,silencedetect=n=-45dB:d=2", "-f", "null", "-"], timeout=300)
    err = r.stderr
    blacks = [(float(a), float(b)) for a, b in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", err)]
    freezes = [float(x) for x in re.findall(r"freeze_duration: ([\d.]+)", err)]
    silences = [float(x) for x in re.findall(r"silence_duration: ([\d.]+)", err)]
    mean = re.search(r"mean_volume: (-?[\d.]+) dB", err)
    return dict(black_start=any(a < 0.5 for a, _ in blacks),
                black_total=round(sum(b - a for a, b in blacks), 1),
                frozen_total=round(sum(freezes), 1),
                silence_total=round(sum(silences), 1),
                mean_db=float(mean.group(1)) if mean else None)


def contact_sheet(path, dur, dest):
    times = [min(0.3, dur / 10), dur * 0.25, dur * 0.5, dur * 0.75, max(dur - 0.6, 0)]
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    for t in times:
        cmd += ["-ss", f"{t:.2f}", "-i", str(path)]
    chains = "".join(f"[{i}:v]scale={FRAME_W}:{FRAME_H}:force_original_aspect_ratio=decrease,"
                     f"pad={FRAME_W}:{FRAME_H}:(ow-iw)/2:(oh-ih)/2,setsar=1[v{i}];" for i in range(5))
    cmd += ["-filter_complex", chains + "".join(f"[v{i}]" for i in range(5)) + "hstack=5",
            "-frames:v", "1", "-q:v", "3", str(dest)]
    run(cmd)
    return [round(t, 1) for t in times]


def ollama_ready(model):
    """Make sure Ollama is running (start it if it is installed) and the model is pulled.
    Returns an error message, or "" when ready."""
    import os, shutil
    tags = OLLAMA.replace("/api/chat", "/api/tags")

    def models():
        with urllib.request.urlopen(tags, timeout=5) as r:
            return [m["name"] for m in json.loads(r.read()).get("models", [])]

    try:
        names = models()
    except OSError:
        exe = shutil.which("ollama") or str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Ollama/ollama.exe")
        if not Path(exe).exists():
            return "Ollama is not installed. Install it from https://ollama.com, then run this again."
        print("Ollama is not running. Starting it...")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen([exe, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
        names = None
        for _ in range(30):
            time.sleep(1)
            try:
                names = models()
                break
            except OSError:
                pass
        if names is None:
            return "Ollama would not start. Open the Ollama app from the Start menu, wait for its icon in the tray, then run this again."
    if model not in names and f"{model}:latest" not in names:
        return f"The model {model} is not installed. Run:  ollama pull {model}   then run this again."
    return ""


# ---------- sharing the graphics card ----------
# Other GPU-hungry programs on this PC that must have the card to themselves.
# Each entry: (text to look for in a process command line, friendly name). Add your own.
GPU_RIVALS = [("--port 8188", "ComfyUI")]
COMFY = "http://127.0.0.1:8188/system_stats"
HEADROOM_GB = 1.5  # leave this much free for Windows, the browser and games
NUM_CTX = 4096  # prompt + 1 image is about 1.5k tokens; the old 8k context only wasted graphics memory


def _ps(script, timeout=30):
    return run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], timeout=timeout).stdout.strip()


def gpu_total_gb():
    try:
        import winreg
        base = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
        best = 0
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as k:
            for i in range(winreg.QueryInfoKey(k)[0]):
                try:
                    with winreg.OpenKey(k, winreg.EnumKey(k, i)) as sub:
                        v = winreg.QueryValueEx(sub, "HardwareInformation.qwMemorySize")[0]
                        best = max(best, int.from_bytes(v, "little") if isinstance(v, bytes) else int(v))
                except OSError:
                    pass
        return best / 2**30 if best else 16.0
    except Exception:
        return 16.0


def gpu_used_gb():
    """Graphics memory in use by everything on the PC (Windows' own GPU counter, works on AMD and NVIDIA)."""
    out = _ps(r"(Get-Counter '\GPU Adapter Memory(*)\Dedicated Usage').CounterSamples | "
              r"Measure-Object -Property CookedValue -Maximum | ForEach-Object { $_.Maximum }")
    try:
        return float(out) / 2**30
    except ValueError:
        return None


def rival_running(quick=False):
    """Name of a GPU-hungry program that must have the card to itself, or "".
    quick=True only pings ComfyUI (instant); the full check also reads the process list (~3 s)."""
    try:
        with urllib.request.urlopen(COMFY, timeout=2):
            return "ComfyUI"
    except OSError:
        pass
    if quick:
        return ""
    out = _ps("Get-CimInstance Win32_Process | ForEach-Object { $_.CommandLine }").lower()
    for needle, name in GPU_RIVALS:
        if needle in out:
            return name
    return ""


def ollama_loaded():
    try:
        with urllib.request.urlopen(OLLAMA.replace("/api/chat", "/api/ps"), timeout=5) as r:
            return {m["name"]: m.get("size_vram", m.get("size", 0)) / 2**30 for m in json.loads(r.read()).get("models", [])}
    except OSError:
        return {}


def model_need_gb(model):
    """Rough graphics memory the model needs once loaded (weights + vision part + 4k context)."""
    try:
        with urllib.request.urlopen(OLLAMA.replace("/api/chat", "/api/tags"), timeout=5) as r:
            for m in json.loads(r.read()).get("models", []):
                if m["name"] in (model, f"{model}:latest"):
                    return m.get("size", 8 * 2**30) / 2**30 + 1.0
    except OSError:
        pass
    return 9.0


def gpu_busy(model, cpu):
    """Why the scorer should not start now, or ""."""
    rival = rival_running()
    if rival:
        return f"{rival} is running and needs the graphics card"
    if cpu:
        return ""
    loaded = ollama_loaded()
    if model in loaded or f"{model}:latest" in loaded:
        return ""
    used, total = gpu_used_gb(), gpu_total_gb()
    if used is None:
        return ""
    need, free = model_need_gb(model), total - used
    if free < need + HEADROOM_GB:
        others = ", ".join(f"{n} {g:.1f} GB" for n, g in loaded.items())
        return (f"only {free:.1f} of {total:.0f} GB graphics memory is free and {model} needs about {need:.1f} GB"
                + (f" (Ollama is holding {others} for another app)" if others else ""))
    return ""


def wait_for_gpu(model, cpu, minutes, deadline):
    """Wait politely until the card is free. Returns "" when OK to go, else the reason it gave up."""
    end = time.time() + minutes * 60
    reason = gpu_busy(model, cpu)
    while reason:
        if time.time() >= end or (deadline and time.time() >= deadline):
            return reason
        print(f"Waiting for the graphics card: {reason}. Checking again in 30 s...", flush=True)
        time.sleep(30)
        reason = gpu_busy(model, cpu)
    return ""


def unload(model):
    """Free the graphics memory right away instead of letting Ollama keep the model loaded."""
    try:
        body = json.dumps({"model": model, "keep_alive": 0}).encode()
        req = urllib.request.Request(OLLAMA.replace("/api/chat", "/api/generate"), body,
                                     {"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=60).read()
        print(f"Unloaded {model} from the graphics card.")
    except OSError:
        pass


def deadline_from(hhmm):
    if not hhmm:
        return None
    h, m = map(int, hhmm.split(":"))
    now = time.localtime()
    t = time.mktime((now.tm_year, now.tm_mon, now.tm_mday, h, m, 0, 0, 0, -1))
    return t + 86400 if t <= time.time() else t


def ask_model(model, sheet, title, times, dur, cpu=False):
    opts = {"temperature": 0, "num_ctx": NUM_CTX}
    if cpu:
        opts["num_gpu"] = 0  # processor only: slower, but uses no graphics memory
    body = {
        "model": model, "stream": False, "think": False, "format": SCHEMA, "keep_alive": "2m",
        "options": opts,
        "messages": [{"role": "user", "content": PROMPT.format(times=times, dur=dur, title=title,
                                                              channel=brand.channel(), niche=brand.niche()),
                      "images": [base64.b64encode(sheet.read_bytes()).decode()]}],
    }
    req = urllib.request.Request(OLLAMA, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as resp:
        out = json.loads(resp.read())
    data = json.loads(out["message"]["content"])
    for k in ("hook", "payoff", "standalone", "phone"):
        data[k] = max(1, min(10, int(data.get(k, 1))))
    return data


def flags_and_penalty(p, t, s):
    flags, pen = [], 0
    # Playbook section 6: 15-60 s normal, up to about 90 s for a guide, chase or story. Only penalise outside that.
    if p["duration"] < 8:
        flags.append(f"very short ({p['duration']:.0f}s)"); pen += 15
    elif p["duration"] > 92:
        flags.append(f"length {p['duration']:.0f}s over 90s: trim it or split into parts"); pen += 15
    elif p["duration"] > 61:
        flags.append(f"long ({p['duration']:.0f}s): check it is a guide, chase or story that needs it")
    if p["width"] and p["height"] and abs(p["width"] / p["height"] - 9 / 16) > 0.02:
        flags.append(f"not 9:16 ({p['width']}x{p['height']})"); pen += 20
    if not p["has_audio"]:
        flags.append("no audio track"); pen += 25
    elif t["mean_db"] is not None and t["mean_db"] < -35:
        flags.append(f"very quiet ({t['mean_db']:.0f} dB)"); pen += 10
    if t["black_start"]:
        flags.append("opens on black"); pen += 20
    if t["black_total"] > 1:
        flags.append(f"{t['black_total']}s of black"); pen += 10
    if t["frozen_total"] > 2:
        flags.append(f"{t['frozen_total']}s frozen picture"); pen += 10
    if t["silence_total"] > 4:
        flags.append(f"{t['silence_total']}s silence"); pen += 5
    if s["permission"] not in ("creator-yes", "official"):
        flags.append(f"permission: {s['permission'] or 'none'}"); pen += 100
    if s["placeholder"]:
        flags.append("caption still has template placeholder")  # fixable, no penalty
    hook = s["title"].strip()
    words = re.sub(r"[!?.\s]+$", "", hook).lower().split()
    if words and words[-1] in DANGLING:
        flags.append("hook text cut off mid-sentence"); pen += 8
    if re.search(r"[^\x00-ɏ‘-‟…]", hook) or re.search(r"\b(tem|est|pas|voici|pourquoi|normale)\b", hook.lower()):
        flags.append("hook not in English"); pen += 10
    return flags, pen


DANGLING = {"in", "to", "a", "an", "the", "of", "you", "i", "get", "never", "not", "most", "easter", "wish",
            "for", "with", "and", "on", "at", "your", "my", "grand", "theft", "auto", "about", "this", "that"}


def score(m, pen):
    base = (0.35 * m["hook"] + 0.30 * m["payoff"] + 0.15 * m["standalone"] + 0.20 * m["phone"]) * 10
    if m["verdict"] == "post":
        base += 5
    elif m["verdict"] == "skip":
        base -= 5
    return max(0, round(base - pen))


def mark_duplicates(rows):
    """Clips cut from overlapping ranges of the same source: keep the best, flag the rest."""
    best = {}
    for r in sorted(rows, key=lambda r: -r["score"]):
        r["duplicate_of"] = ""
        if not r["source"] or r["start"] is None:
            continue
        for other in best.get(r["source"], []):
            overlap = min(r["end"], other["end"]) - max(r["start"], other["start"])
            if overlap > 0.5 * min(r["end"] - r["start"], other["end"] - other["start"]):
                r["duplicate_of"] = other["file"]
                break
        if not r["duplicate_of"]:
            best.setdefault(r["source"], []).append(r)


def write_outputs(rows, top_n):
    cols = ["rank", "score", "verdict", "file", "title", "category", "what_happens", "hook", "payoff",
            "standalone", "phone", "duration", "flags", "problems", "duplicate_of", "source", "start", "end",
            "credit", "permission"]
    with RESULTS.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({**r, "flags": "; ".join(r["flags"]), "problems": "; ".join(r["problems"])})

    picks = [r for r in rows if not r["duplicate_of"]][:top_n]
    cards = []
    for r in picks:
        video = (EDITS / r["file"]).as_uri()
        sheet = (SHEETS / (Path(r["file"]).stem + ".jpg")).as_uri()
        issues = r["flags"] + r["problems"]
        cards.append(f"""<div class=card><div class=head><b>#{r['rank']} &middot; {r['score']}</b>
<span class="v {r['verdict']}">{r['verdict']}</span> <span class=cat>{html.escape(r['category'])}</span></div>
<div class=t>{html.escape(r['title'])}</div><div>{html.escape(r['what_happens'])}</div>
<div class=s>hook {r['hook']} &middot; payoff {r['payoff']} &middot; standalone {r['standalone']} &middot; phone {r['phone']} &middot; {r['duration']:.0f}s &middot; {html.escape(r['credit'])}</div>
<div class=i>{html.escape('; '.join(issues)) or 'no issues spotted'}</div>
<a href="{video}"><img src="{sheet}"></a><div class=f>{html.escape(r['file'])}</div></div>""")
    REPORT.write_text(f"""<!doctype html><meta charset=utf-8><title>Edits pre-filter: top {len(picks)}</title>
<style>body{{font:14px system-ui;background:#111;color:#eee;margin:20px}}.card{{background:#1c1c1c;border-radius:8px;padding:12px;margin:0 0 16px}}
img{{width:100%;max-width:1350px;border-radius:4px;margin-top:8px}}.t{{font-size:16px;font-weight:600;margin:4px 0}}.s,.f{{color:#999;font-size:12px}}
.i{{color:#f6b26b;font-size:12px;margin-top:4px}}.v{{padding:1px 6px;border-radius:4px}}.post{{background:#2e7d32}}.maybe{{background:#8d6e00}}.skip{{background:#7a2a2a}}
.cat{{color:#8ab4f8}}a{{color:inherit}}</style>
<h2>Top {len(picks)} of {len(rows)} edits (local pre-filter, rough)</h2>
<p>Scored by a local vision model from 5 still frames plus ffmpeg checks. It cannot hear audio or see motion between frames,
so treat this as a shortlist to watch, not a decision. Click a strip to play the clip. Duplicates from the same moment are hidden; see results.csv.</p>
{''.join(cards)}""", encoding="utf-8")


def default_model():
    """The vision model to use: "review_model" in hunter/config.json, else a local vision model."""
    try:
        return str(json.loads(CONFIG.read_text(encoding="utf-8-sig")).get("review_model") or "").strip() or MODEL_DEFAULT
    except (OSError, ValueError):
        return MODEL_DEFAULT


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None, help=f"Ollama vision model (default {MODEL_DEFAULT}, or review_model in hunter/config.json)")
    ap.add_argument("--limit", type=int, default=0, help="score at most N new clips (0 = all)")
    ap.add_argument("--rescore", action="store_true", help="ignore the cache")
    ap.add_argument("--top", type=int, default=12)
    ap.add_argument("--wait", type=float, default=15, help="minutes to wait for the graphics card before giving up")
    ap.add_argument("--stop-at", default="", help="HH:MM local time to stop scoring (e.g. before another GPU job at 2 AM)")
    ap.add_argument("--cpu", action="store_true", help="run the model on the processor only (no graphics memory, slower)")
    ap.add_argument("--cpu-if-busy", action="store_true",
                    help="if graphics memory is still short after --wait (and no GPU rival is running), use --cpu")
    a = ap.parse_args()
    a.model = a.model or default_model()

    problem = ollama_ready(a.model)
    if problem:
        print(f"\nAI review did not run: {problem}\nYour previous results were left as they were.")
        return 2
    deadline = deadline_from(a.stop_at)
    busy = wait_for_gpu(a.model, a.cpu, a.wait, deadline)
    if busy and a.cpu_if_busy and not rival_running():
        print(f"\n{busy}, so scoring on the processor instead (no graphics memory, about 80 s a clip).")
        a.cpu, busy = True, ""
    if busy:
        print(f"\nAI review did not run: {busy}.\nNothing was changed. Run it again when that is finished.")
        return 3
    try:
        return score_all(a, deadline)
    finally:
        unload(a.model)


def score_all(a, deadline):
    SHEETS.mkdir(parents=True, exist_ok=True)
    cache = {} if a.rescore or not CACHE.exists() else json.loads(CACHE.read_text(encoding="utf-8"))
    files = sorted(p for p in EDITS.glob("*.mp4") if not p.name.endswith(".part.mp4"))
    done_new = failed = 0
    for i, path in enumerate(files, 1):
        st = path.stat()
        key = f"{path.name}|{st.st_size}|{int(st.st_mtime)}|{a.model}|{VERSION}"
        if key in cache:
            continue
        if a.limit and done_new >= a.limit:
            break
        if deadline and time.time() >= deadline:
            print(f"\nReached the stop time {a.stop_at}; the remaining clips will be scored next run.")
            break
        rival = rival_running(quick=done_new % 5 != 0)
        if rival:
            print(f"\n{rival} started, so the AI review is stepping aside. Scores so far are saved;"
                  " the rest will be scored next run.")
            break
        t0 = time.time()
        try:
            s = sidecar(path)
            p = probe(path)
            t = tech_checks(path, p["duration"])
            sheet = SHEETS / (path.stem + ".jpg")
            times = contact_sheet(path, p["duration"], sheet)
            m = ask_model(a.model, sheet, s["title"], times, p["duration"], a.cpu)
        except Exception as e:  # keep going; one bad clip shouldn't stop the batch
            print(f"[{i}/{len(files)}] {path.name}: FAILED ({e})")
            failed += 1
            if failed >= 3 and done_new == 0:
                print("\nThe first clips all failed, so stopping here. Your previous results were left as they were.")
                return 1
            continue
        flags, pen = flags_and_penalty(p, t, s)
        cache[key] = dict(file=path.name, title=s["title"], source=s["source"], start=s["start"], end=s["end"],
                          credit=s["credit"], permission=s["permission"], duration=p["duration"],
                          flags=flags, score=score(m, pen), **m)
        CACHE.write_text(json.dumps(cache, indent=1), encoding="utf-8")
        done_new += 1
        c = cache[key]
        print(f"[{i}/{len(files)}] {c['score']:3d} {c['verdict']:5s} {path.name}  ({time.time() - t0:.0f}s)")

    present = {p.name for p in files}
    rows = [dict(v) for k, v in cache.items() if v["file"] in present and k.endswith(f"|{a.model}|{VERSION}")]
    rows.sort(key=lambda r: -r["score"])
    mark_duplicates(rows)
    rows.sort(key=lambda r: (bool(r["duplicate_of"]), -r["score"]))
    for n, r in enumerate(rows, 1):
        r["rank"] = n
    write_outputs(rows, a.top)
    print(f"\nScored {len(rows)} clips ({done_new} new). Top list: {REPORT}\nFull table: {RESULTS}")


if __name__ == "__main__":
    sys.exit(main())
