"""
ReelHound Auto-Clip
Finds the best moments in a video and renders vertical Reels automatically.

  python autoclip.py                 clip every new download in media/raw
  python autoclip.py VIDEO --own     clip one of your own gameplay videos
  python autoclip.py VIDEO --own --whole          the whole video as one Reel (up to 90 s)
  python autoclip.py VIDEO --own --whole parts    a longer video split into parts of about a minute
  python autoclip.py VIDEO --own --whole cap      just the first ~90 s
Finished Reels go to media/edits. Watch them, delete the bad ones, and move the
keepers to media/ready.
"""
import argparse, array, json, math, os, re, subprocess, sys, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, ROOT)
import brand  # noqa: E402  (watermark, credits, hashtags)

RAW = os.path.join(ROOT, "media", "raw")
EDITS = os.path.join(ROOT, "media", "edits")
STATE = os.path.join(HERE, "autoclip_done.json")
CLIPMAKER = os.path.join(HERE, "clipmaker.py")
RATE = 4000      # audio samples per second used for analysis
STEP = 0.5       # analysis resolution in seconds


def log(msg):
    print(f"[autoclip] {msg}", flush=True)


def duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def loudness_curve(path):
    """RMS loudness per STEP seconds (pure Python, no extra installs)."""
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(RATE), "-f", "s16le", "-"],
                       capture_output=True)
    a = array.array("h")
    a.frombytes(p.stdout[: len(p.stdout) // 2 * 2])
    n = int(RATE * STEP)
    out = []
    for i in range(0, len(a) - n + 1, n):
        chunk = a[i:i + n:4]  # every 4th sample is plenty for loudness
        out.append(math.sqrt(sum(x * x for x in chunk) / len(chunk)) if chunk else 0.0)
    return out


def scene_changes(path):
    """Times (s) where the picture changes a lot: cuts, explosions, crashes."""
    p = subprocess.run(["ffmpeg", "-v", "info", "-i", path, "-an", "-vf",
                        "fps=4,scale=160:-2,select='gt(scene,0.30)',showinfo", "-f", "null", "-"],
                       capture_output=True, text=True)
    return [float(m) for m in re.findall(r"pts_time:([0-9.]+)", p.stderr)]


def best_windows(loud, scenes, total, length, count, skip_edges=8.0):
    if not loud:
        return []
    mean = sum(loud) / len(loud)
    sd = math.sqrt(sum((x - mean) ** 2 for x in loud) / len(loud)) or 1.0
    z = [(x - mean) / sd for x in loud]
    scene_bins = [0] * len(loud)
    for t in scenes:
        i = int(t / STEP)
        if 0 <= i < len(scene_bins):
            scene_bins[i] += 1
    win = max(1, int(length / STEP))
    first = int(min(skip_edges, total * 0.1) / STEP)
    last = len(loud) - int(min(skip_edges, total * 0.1) / STEP) - win
    cands = []
    for s in range(first, max(first + 1, last), 2):  # every 1 s
        seg = z[s:s + win]
        if len(seg) < win:
            break
        hook = sum(seg[: int(3 / STEP)]) / int(3 / STEP)           # strong first 3 seconds
        energy = sum(seg) / len(seg)
        peak = max(seg)
        cuts = sum(scene_bins[s:s + win])
        score = 1.2 * energy + 0.8 * hook + 0.5 * min(peak, 4) + 0.15 * min(cuts, 12)
        cands.append((score, s * STEP))
    cands.sort(reverse=True)
    picked = []
    for sc, start in cands:
        if picked and sc <= 0:   # after the best moment, only keep clearly above-average ones
            break
        if all(abs(start - p) >= length for _, p in picked):
            picked.append((sc, start))
        if len(picked) == count:
            break
    return sorted(picked, key=lambda x: x[1])


# How-to / guide / trick / location / tutorial videos get the Clip Maker's --guide trim (playbook section 6):
# keep the setup, steps and payoff, cut intros, plugs, chatter, repeats and long pauses.
GUIDE_TITLE = re.compile(
    r"\b(how to|guides?|tutorials?|walkthrough|locations?|where to|where is|secrets?|hidden|tricks?|tips?|"
    r"codes?|safe|easter eggs?|free|unlock|find|get (?:the|a|an|every|all|this)|best .{0,20}(?:cars?|weapons?|guns?)|"
    r"money|cash|don'?t miss|you need|early)\b", re.I)


def is_guide(title):
    return bool(GUIDE_TITLE.search(title or ""))


def make_hook(title):
    # Fallback only: clipmaker --auto-hook writes a per-clip hook with the local AI.
    sys.path.insert(0, HERE)
    from hookwriter import clean_title
    return clean_title(title)


def mmss(sec):
    return f"{int(sec // 60)}:{sec % 60:05.2f}"


def clip_video(path, source, args, finished=None, checkpoint=None):
    total = duration(path)
    if total < 10:
        log(f"Skipping {os.path.basename(path)} (too short).")
        return 0
    # Playbook section 6: 15-60 s normal, up to about 90 s when a guide, chase or story needs it.
    length = min(max(15.0, min(float(args.length), 90.0)), max(8.0, total - 2))
    log(f"Analyzing {os.path.basename(path)} ({total / 60:.1f} min)...")
    loud = loudness_curve(path)
    scenes = scene_changes(path)
    picks = best_windows(loud, scenes, total, length, args.count)
    if not picks:
        log("No good moments found.")
        return 0
    hook = args.hook or make_hook(source.get("title", ""))
    made = 0
    for i, (score, start) in enumerate(picks, 1):
        window = f"{start:.2f}-{start + length:.2f}"
        if finished is not None and window in finished:
            continue
        log(f"  Moment {i}: {mmss(start)} to {mmss(start + length)} (score {score:.1f})")
        cmd = [sys.executable, CLIPMAKER, path, "--start", f"{start:.2f}", "--end", f"{start + length:.2f}",
               "--hook", hook, "--permission", source["permission"], "--preset", args.preset, "--out", EDITS]
        if args.preset == "news":
            cmd += ["--title", hook]
        elif not args.hook:
            cmd += ["--auto-hook", "--source-title", source.get("title", "")]
        credit = getattr(args, "credit_text", "")
        if source.get("credit") or credit:
            cmd += ["--credit", credit.replace("{creator}", source.get("credit", "")) if credit else source["credit"]]
        for flag, setting in (("--whisper-model", "whisper_model"), ("--caption-size", "caption_size"),
                              ("--credit-position", "credit_position")):
            value = getattr(args, setting, None)
            if value is not None:
                cmd += [flag, str(value)]
        if args.no_captions:
            cmd.append("--no-captions")
        if getattr(args, "guide_trim", True) and (getattr(args, "guide", False) or is_guide(source.get("title", ""))):
            cmd.append("--guide")
        run = getattr(args, "run_clip", None)
        if (run(cmd) if run else subprocess.run(cmd).returncode) == 0:
            made += 1
            if checkpoint:
                checkpoint(window)
        elif run:
            raise RuntimeError("Clip render failed. See the log above.")
    return made


# ---------- whole video ----------
WHOLE_MAX = 90.0   # playbook section 6: 15-60 s normal, up to about 90 s
PART_TARGET = 60.0 # split longer videos into parts of about a minute
MAX_PARTS = 8


class TooLong(ValueError):
    """The whole video doesn't fit one Reel: the caller should ask (split into parts, first 90 s, or best moments)."""


def _quiet_point(loud, ideal, lo, hi):
    """The quietest 0.5 s step between lo and hi, nearest ideal on ties: a cut there is less likely mid-sentence."""
    if not loud:
        return ideal
    first, last = max(0, int(lo / STEP)), min(len(loud) - 1, int(hi / STEP))
    if first > last:
        return ideal
    best = min(range(first, last + 1), key=lambda i: (loud[i], abs(i * STEP - ideal)))
    return best * STEP + STEP / 2


def parts_needed(total):
    return max(1, math.ceil(total / PART_TARGET))


def whole_plan(path, total, mode="auto", loud=None):
    """Ranges [(start, end), ...] that cover the video. mode: auto (one Reel, up to 90 s), parts, cap."""
    if total < 3:
        raise ValueError("the video is too short to clip")
    if total <= WHOLE_MAX or mode == "auto":
        if total > WHOLE_MAX:
            n = parts_needed(total)
            raise TooLong(f"the whole video is {mmss_short(total)}, over the 90 s Reel limit. Split it into {n} parts "
                          f"of about {mmss_short(total / n)}, keep the first 90 s, or use the best moments instead")
        return [(0.0, total)]
    loud = loudness_curve(path) if loud is None else loud
    if mode == "cap":
        end = _quiet_point(loud, WHOLE_MAX - 1, WHOLE_MAX - 12, WHOLE_MAX - 0.5)
        return [(0.0, round(end, 2))]
    if mode != "parts":
        raise ValueError(f"unknown whole-video mode: {mode}")
    n = parts_needed(total)
    if n > MAX_PARTS:
        raise ValueError(f"the video is {mmss_short(total)}, which would be {n} parts. Up to {MAX_PARTS} parts "
                         f"(about {MAX_PARTS} minutes) is the limit; use the best moments instead")
    size = total / n
    cuts = [0.0]
    for k in range(1, n):
        ideal = k * size
        cuts.append(round(_quiet_point(loud, ideal, ideal - 5, ideal + 5), 2))
    cuts.append(total)
    return list(zip(cuts, cuts[1:]))


def mmss_short(sec):
    sec = int(round(sec))
    return f"{sec // 60}:{sec % 60:02d}" if sec >= 60 else f"{sec} s"


def clip_whole(path, source, args, mode="auto"):
    """Render the whole video: one Reel, or numbered parts. Raises TooLong when it needs a choice."""
    total = duration(path)
    ranges = whole_plan(path, total, mode)
    hook = args.hook or ""
    # The whole video was asked for, so the how-to trim only runs when it's ticked/forced, not from the title.
    guide = getattr(args, "guide_trim", True) and getattr(args, "guide", False)
    run = getattr(args, "run_clip", None)
    made = 0
    for i, (start, end) in enumerate(ranges, 1):
        label = f"{i}/{len(ranges)}" if len(ranges) > 1 else ""
        log(f"  Whole video{' part ' + label if label else ''}: {mmss(start)} to {mmss(end)}"
            + (" (first 90 s)" if mode == "cap" and total > WHOLE_MAX else ""))
        cmd = [sys.executable, CLIPMAKER, path, "--start", f"{start:.2f}", "--end", f"{end:.2f}",
               "--permission", source["permission"], "--preset", args.preset, "--out", EDITS]
        if hook:
            cmd += ["--hook", hook]
            if args.preset == "news":
                cmd += ["--title", hook]
        else:
            cmd += ["--auto-hook", "--source-title", source.get("title", "")]
        if label:
            cmd += ["--part", label]
        credit = getattr(args, "credit_text", "")
        if source.get("credit") or credit:
            cmd += ["--credit", credit.replace("{creator}", source.get("credit", "")) if credit else source["credit"]]
        for flag, setting in (("--whisper-model", "whisper_model"), ("--caption-size", "caption_size"),
                              ("--credit-position", "credit_position")):
            value = getattr(args, setting, None)
            if value is not None:
                cmd += [flag, str(value)]
        if args.no_captions:
            cmd.append("--no-captions")
        if guide:
            cmd.append("--guide")
        if (run(cmd) if run else subprocess.run(cmd).returncode) == 0:
            made += 1
        elif run:
            raise RuntimeError("Clip render failed. See the log above.")
    return made


def load_source(video):
    side = os.path.splitext(video)[0] + ".source.json"
    if not os.path.exists(side):
        return None
    with open(side, encoding="utf-8") as f:
        s = json.load(f)
    perm = (s.get("permission") or "").lower()
    s["permission"] = {"yes": "creator-yes", "own": "own", "official": "official"}.get(perm, "")
    if s["permission"] == "official" and not (s.get("credit") or "").strip():
        s["credit"] = brand.credit_for(s.get("creator"), "official")
    return s


def process_new(args, stopping=lambda: False):
    done = {}
    if os.path.exists(STATE):
        with open(STATE, encoding="utf-8") as f:
            done = json.load(f)
    if not os.path.isdir(RAW):
        return 0

    def save():
        tmp = STATE + ".panel-tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(done, f, indent=2)
        os.replace(tmp, STATE)

    total = 0
    for name in sorted(os.listdir(RAW)):
        if stopping():
            break
        progress = done.get(name, [])
        if not name.lower().endswith(".mp4") or isinstance(progress, str):
            continue
        path = os.path.join(RAW, name)
        src = load_source(path)
        if not src:
            continue  # files without a source note are left for you to clip by hand
        if not src["permission"]:
            log(f"Skipping {name}: no permission on record.")
            done[name] = "skipped: no permission"
            save()
            continue

        def checkpoint(window):
            progress.append(window)
            done[name] = progress
            save()

        try:
            n = clip_video(path, src, args, progress, checkpoint if getattr(args, "run_clip", None) else None)
        except (RuntimeError, OSError) as error:
            if not getattr(args, "run_clip", None):
                raise
            log(f"Error processing {name}: {error}")
            continue
        count = len(progress) if progress else n
        done[name] = f"{count} clips {datetime.datetime.now():%Y-%m-%d %H:%M}"
        total += n
        save()
    if total:
        log(f"Made {total} new Reels in media\\edits. Watch them and move the keepers to media\\ready.")
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video", nargs="?")
    ap.add_argument("--own", action="store_true", help="the video is your own gameplay")
    ap.add_argument("--hook", default="")
    ap.add_argument("--count", type=int, default=3, help="Reels per video")
    ap.add_argument("--length", type=float, default=40.0,
                    help="seconds per Reel (playbook: 15-60 normal, up to 90 for guides, chases, stories)")
    ap.add_argument("--preset", default="viral", choices=["viral", "clean", "news"])
    ap.add_argument("--no-captions", action="store_true")
    ap.add_argument("--guide", action="store_true", help="force the how-to trim even if the title doesn't look like a guide")
    ap.add_argument("--no-guide-trim", dest="guide_trim", action="store_false", help="never apply the how-to trim")
    ap.add_argument("--whole", nargs="?", const="auto", choices=["auto", "parts", "cap"],
                    help="clip the whole video instead of the best moments: one Reel up to 90 s; longer videos need "
                         "'parts' (split into ~1 min parts) or 'cap' (first ~90 s)")
    a = ap.parse_args()
    os.makedirs(EDITS, exist_ok=True)
    os.makedirs(os.path.join(ROOT, "media", "ready"), exist_ok=True)
    if a.video:
        src = load_source(a.video) or {}
        if a.own:
            src.update(permission="own", credit=src.get("credit", ""))
        if not src.get("permission"):
            log("Only clip your own gameplay (--own) or downloads that came with a permission note.")
            sys.exit(1)
        src.setdefault("title", os.path.splitext(os.path.basename(a.video))[0])
        if a.whole:
            try:
                clip_whole(a.video, src, a, a.whole)
            except TooLong as exc:
                log(f"Not clipped: {exc}. Run again with --whole parts or --whole cap.")
                sys.exit(2)
            except ValueError as exc:
                log(f"Not clipped: {exc}.")
                sys.exit(2)
        else:
            clip_video(a.video, src, a)
        log("Done. Check media\\edits.")
    else:
        process_new(a)


if __name__ == "__main__":
    main()
