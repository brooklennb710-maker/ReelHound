"""
ReelHound Clip Maker
Turns any video into a 1080x1920 vertical clip with hook text, burned-in
captions, a credit line and an optional watermark.

Usage (or just drag a video onto make_clip.bat):
  python clipmaker.py VIDEO --start 0:12 --end 0:38 --hook "THE TRICK NOBODY SHOWED YOU"
         --credit @creator --permission creator-yes --preset viral
"""
import argparse, json, os, re, shutil, subprocess, sys, tempfile, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import brand  # noqa: E402  (needs the repo root on sys.path)

W, H = 1080, 1920
HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = os.path.normpath(os.path.join(HERE, "..", "media", "edits"))

PRESETS = {
    # zoom = how much the gameplay is scaled up in the middle band (1.0 = full width)
    "viral": dict(zoom=1.35, cap_size=92, words_per_line=3, highlight=True,  hook_secs=3.5, hook_size=96, cap_y=1350),
    "clean": dict(zoom=1.0,  cap_size=60, words_per_line=6, highlight=False, hook_secs=2.5, hook_size=72, cap_y=1450),
    "news":  dict(zoom=1.0,  cap_size=66, words_per_line=5, highlight=False, hook_secs=None, hook_size=78, cap_y=1450),
}
PERMISSIONS = ["own", "official", "creator-yes"]


def die(msg):
    print("\n[clipmaker] " + msg)
    sys.exit(1)


def need(tool):
    if not shutil.which(tool):
        die(f"'{tool}' not found. Run setup.bat first (it installs FFmpeg).")


def to_secs(t):
    if t is None or t == "":
        return None
    parts = [float(p) for p in str(t).split(":")]
    s = 0.0
    for p in parts:
        s = s * 60 + p
    return s


def parse_ranges(text):
    """'0:41.9-0:47,50.2-55.1' -> [(41.9, 47.0), (50.2, 55.1)] in source seconds."""
    out = []
    for part in (text or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" not in part:
            die(f"--keep range '{part}' needs a start and an end, like 41.9-47.0")
        a, b = part.split("-", 1)
        s, e = to_secs(a.strip()), to_secs(b.strip())
        if s is None or e is None or e <= s:
            die(f"--keep range '{part}' is backwards or empty.")
        out.append((s, e))
    out.sort()
    for (s1, e1), (s2, e2) in zip(out, out[1:]):
        if s2 < e1:
            die("--keep ranges overlap. List them in order without overlaps.")
    return out


# ---- Guide trim ---------------------------------------------------------------------------------
# Standing rule (playbook section 6): how-to, guide, trick, location and tutorial clips keep the setup
# that makes the goal clear plus the key steps and the payoff. Intros, channel plugs, chatter,
# repeats and detours go, and the clip still ends on a full sentence.
FILLER = re.compile(
    r"(subscrib|like (the|this) video|like button|smash (that|the)|hit (the|that) (like|bell)|follow button|"
    r"click (that|the) follow|comment (below|down)|let me know|link in (the )?description|check out my|"
    r"my other video|on screen for you|what'?s up,? guys|hey,? guys|welcome back|in (today'?s|this) video|"
    r"(a )?like is (really )?appreciated|if you guys enjoy|enjoy this content|without further ado|"
    r"i hope (that|this) helps|see you (in the next|next time)|thanks for watching)", re.I)


STOP = set("a an the and or but so then just you your you'll you're it it's is are be will to of in on at for "
           "with this that there there's here we i i'm me my go get can up out now also if as from".split())


def sentences(words):
    """Group (start, end, text) words into sentences on . ? ! endings."""
    out, cur = [], []
    for w in words:
        cur.append(w)
        if re.search(r"[.?!]$", w[2]):
            out.append(cur); cur = []
    if cur:
        out.append(cur)
    return out


def guide_plan(words, dur, max_gap=2.5, lead=1.0, tail=1.5, min_len=8.0, keep_after=0.8, keep_before=0.5):
    """Return (intervals, notes): the parts of [0, dur] to keep for a guide clip, in clip-relative seconds."""
    notes = []
    if not words:
        return [(0.0, dur)], ["no speech found, kept the full range"]
    sents = sentences(words)
    kept_words, seen = [], []
    for i, s in enumerate(sents):
        text = " ".join(w[2] for w in s)
        short = text if len(text) < 70 else text[:67] + "..."
        if FILLER.search(text):
            if len(s) > 25:  # unpunctuated run-on: the plug is buried in real steps, so cut it by hand
                notes.append("WARNING: chatter inside a long run-on line, cut it with --keep: " + short)
            else:
                notes.append("cut chatter: " + short)
                continue
        content = {x for x in re.findall(r"[a-z0-9']+", text.lower()) if x not in STOP}
        if len(content) >= 4 and any(len(content & old) >= 0.7 * len(content) for old in seen):
            notes.append("cut repeat: " + short)
            continue
        seen.append(content)
        kept_words.extend(s)
    if not kept_words:
        return [(0.0, dur)], ["every sentence looked like chatter, kept the full range"]
    # End on a full sentence: drop the first words of the next line that bleed in at the end of the range.
    # A longer fragment, or one with a number in it (codes, cash), is a sentence the range cut off: keep it
    # and say so, because the fix is a later end time, not losing the payoff.
    if not re.search(r"[.?!]$", kept_words[-1][2]):
        last_full = max((i for i, w in enumerate(kept_words) if re.search(r"[.?!]$", w[2])), default=None)
        frag_words = kept_words[last_full + 1:] if last_full is not None else kept_words
        frag = " ".join(w[2] for w in frag_words)
        if (last_full is not None and kept_words[last_full][1] >= min_len * 0.6 and len(frag_words) <= 3
                and not re.search(r"\d|\b(one|two|three|four|five|six|seven|eight|nine|ten|hundred|thousand|million)\b",
                                  frag, re.I)):
            notes.append("cut the start of the next line: " + frag[:60])
            kept_words = kept_words[:last_full + 1]
        else:
            notes.append("WARNING: ends mid-sentence (" + frag[-50:] + "). Push --end later to finish it.")
    dropped_set = {id(w) for w in words} - {id(w) for w in kept_words}
    # Walk the kept words and build intervals, closing any silence longer than max_gap.
    ivs = []
    s0 = max(0.0, kept_words[0][0] - lead)
    if s0 > 0.3:
        notes.append(f"cut {s0:.1f}s before the first line")
    cur_s, cur_e = s0, kept_words[0][1]
    for prev, w in zip(kept_words, kept_words[1:]):
        gap = w[0] - prev[1]
        removed_between = any(prev[1] <= x[0] < w[0] and id(x) in dropped_set for x in words)
        if gap > max_gap or removed_between:
            ivs.append((cur_s, min(prev[1] + keep_after, w[0])))
            cur_s = max(prev[1] + keep_after, w[0] - keep_before) if not removed_between else max(prev[1], w[0] - 0.35)
            if not removed_between:
                notes.append(f"closed a {gap:.1f}s pause at {prev[1]:.1f}s")
        cur_e = w[1]
    # The payoff is often silent (garage opening, cash counter): keep a little picture after the last line.
    nxt = next((x[0] for x in words if x[0] > kept_words[-1][1] and id(x) in dropped_set), dur)
    end = min(dur, cur_e + tail, nxt - 0.05)
    ivs.append((cur_s, end))
    ivs = [(round(a, 2), round(b, 2)) for a, b in ivs if b - a >= 0.4]
    total = sum(b - a for a, b in ivs)
    if total < min_len:
        return [(0.0, dur)], [f"trim would leave {total:.1f}s, under {min_len:.0f}s, so kept the full range"]
    return ivs, notes


def remap_words(words, ivs):
    """Move clip-relative word times onto the trimmed timeline; words outside the kept parts are dropped."""
    out, offset = [], 0.0
    for a, b in ivs:
        for s, e, t in words:
            if a - 0.05 <= s < b:
                out.append((offset + max(s - a, 0), offset + min(e, b) - a, t))
        offset += b - a
    return out


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
                         capture_output=True, text=True)
    if out.returncode != 0:
        die("Couldn't read that video: " + out.stderr.strip())
    info = json.loads(out.stdout)
    dur = float(info["format"].get("duration", 0))
    has_audio = any(s.get("codec_type") == "audio" for s in info["streams"])
    aspect = 16 / 9
    v = next((s for s in info["streams"] if s.get("codec_type") == "video"), None)
    if v and v.get("width") and v.get("height"):
        w, h = float(v["width"]), float(v["height"])
        sar = v.get("sample_aspect_ratio", "1:1")
        try:
            n, d = (float(x) for x in sar.split(":"))
            if n > 0 and d > 0:
                w *= n / d
        except ValueError:
            pass
        rot = 0
        for sd in v.get("side_data_list", []) or []:
            rot = int(float(sd.get("rotation", 0) or 0))
        rot = int(float((v.get("tags") or {}).get("rotate", rot)))
        if abs(rot) % 180 == 90:
            w, h = h, w
        aspect = w / h
    return dur, has_audio, aspect


def ass_time(t):
    t = max(t, 0)
    h = int(t // 3600); m = int(t % 3600 // 60); s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def ass_escape(text):
    return text.replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", "\\N")


def transcribe(path, start, end, model_size):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("[clipmaker] faster-whisper isn't installed, so no captions. Run setup.bat to add it.")
        return []
    print(f"[clipmaker] Transcribing with Whisper ({model_size}). First run downloads the model...")
    model = None
    for device, ctype in (("cuda", "float16"), ("cpu", "int8")):
        try:
            model = WhisperModel(model_size, device=device, compute_type=ctype)
            break
        except Exception:
            continue
    if model is None:
        print("[clipmaker] Whisper couldn't start, skipping captions.")
        return []
    # Decode audio with ffmpeg ourselves (16 kHz mono float) so faster-whisper never needs PyAV,
    # whose version often doesn't match and crashes ("unexpected keyword argument metadata_errors").
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(start), "-to", str(end), "-i", path,
                          "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"], capture_output=True, check=True).stdout
    audio = np.frombuffer(raw, dtype=np.float32).copy()
    if audio.size == 0:
        return []

    def run(m):
        segments, info = m.transcribe(audio, word_timestamps=True, vad_filter=True)
        if info.language != "en" and info.language_probability > 0.6:
            # Our audience reads English: translate non-English speech instead of burning in Hindi/French/etc.
            print(f"[clipmaker] Speech is '{info.language}', translating captions to English.")
            segments, _ = m.transcribe(audio, word_timestamps=True, vad_filter=True, task="translate")
        out = []
        for seg in segments:
            for w in (seg.words or []):
                txt = w.word.strip()
                if txt:
                    out.append((w.start, w.end, txt))
        return out

    try:
        return run(model)
    except Exception as e:
        print(f"[clipmaker] Whisper failed ({e}); retrying on CPU.")
        try:
            return run(WhisperModel(model_size, device="cpu", compute_type="int8"))
        except Exception as e2:
            print(f"[clipmaker] Whisper failed again ({e2}), skipping captions.")
            return []


def build_ass(p, words, hook, credit, dur, news_title, credit_position="bottom-center", watermark=None):
    watermark = brand.watermark() if watermark is None else watermark
    cap_y = p["cap_y"]
    credit_align, credit_margin = {"bottom-center": (2, 230), "bottom-left": (1, 230),
                                  "top-left": (7, 90), "top-center": (8, 90)}[credit_position]
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 0", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Cap,Arial Black,{p['cap_size']},&H00FFFFFF,&H0000E5FF,&H00000000,&H64000000,1,0,0,0,100,100,0,0,1,6,2,5,60,60,0,1",
        f"Style: Hook,Arial Black,{p['hook_size']},&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,1,0,0,0,100,100,0,0,3,18,0,8,70,70,170,1",
        f"Style: Credit,Arial,44,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,3,1,{credit_align},60,60,{credit_margin},1",
        "Style: Mark,Arial,38,&H66FFFFFF,&H66FFFFFF,&H66000000,&H00000000,1,0,0,0,100,100,0,0,1,2,0,9,40,50,60,1",
        "Style: News,Arial Black,58,&H00FFFFFF,&H00FFFFFF,&H00B03A1E,&H00B03A1E,1,0,0,0,100,100,0,0,3,24,0,8,50,50,120,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    end = ass_time(dur)
    if watermark:
        lines.append(f"Dialogue: 0,{ass_time(0)},{end},Mark,,0,0,0,,{ass_escape(watermark)}")
    if credit:
        lines.append(f"Dialogue: 0,{ass_time(0)},{end},Credit,,0,0,0,,{ass_escape('via ' + credit)}")
    if news_title:
        lines.append(f"Dialogue: 1,{ass_time(0)},{end},News,,0,0,0,,{ass_escape(news_title.upper())}")
    if hook:
        hook_end = dur if p["hook_secs"] is None else min(p["hook_secs"], dur)
        lines.append(f"Dialogue: 2,{ass_time(0)},{ass_time(hook_end)},Hook,,0,0,0,,"
                     + ("{\\an8\\pos(540,290)}" if news_title else "") + f"{{\\fad(120,200)}}{ass_escape(hook.upper())}")
    n = p["words_per_line"]
    for i in range(0, len(words), n):
        chunk = words[i:i + n]
        c_start, c_end = chunk[0][0], chunk[-1][1]
        if i + n < len(words):
            c_end = min(max(c_end, c_start + 0.3), words[i + n][0])
        texts = [ass_escape(w[2].upper() if p["highlight"] else w[2]) for w in chunk]
        pos = f"{{\\an5\\pos({W // 2},{cap_y})}}"
        if p["highlight"]:
            # one event per word so the spoken word lights up yellow with a small pop
            for j, (ws, we, _) in enumerate(chunk):
                we2 = chunk[j + 1][0] if j + 1 < len(chunk) else c_end
                parts = [("{\\c&H0000E5FF&\\fscx110\\fscy110}" + t + "{\\c&H00FFFFFF&\\fscx100\\fscy100}") if k == j else t
                         for k, t in enumerate(texts)]
                lines.append(f"Dialogue: 3,{ass_time(ws)},{ass_time(max(we2, ws + 0.05))},Cap,,0,0,0,,{pos}{' '.join(parts)}")
        else:
            lines.append(f"Dialogue: 3,{ass_time(c_start)},{ass_time(c_end)},Cap,,0,0,0,,{pos}{' '.join(texts)}")
    return "\n".join(lines) + "\n"


def slug(text):
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text or "clip").strip("-").lower()
    return s[:40] or "clip"


# Acronyms and short terms that should stay upper-case in a caption line.
KEEP_UPPER = {"npc", "fps", "gpu", "cpu", "ai", "vr", "atm", "ufo", "dlc", "rpg", "hud", "pov", "vs", "tv"}


def capitalize_terms(text):
    """Sentence case the hook for the caption, but leave acronyms alone."""
    return re.sub(r"(?i)\b(" + "|".join(sorted(KEEP_UPPER)) + r")\b",
                  lambda m: m.group(1).upper(), (text or "").capitalize())


def build_srt(words):
    """A standard .srt caption file (5 words per cue) for platforms that take an upload."""
    def stamp(t):
        ms = max(int(round(float(t) * 1000)), 0)
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"

    cues = []
    for i in range(0, len(words), 5):
        chunk = words[i:i + 5]
        if not chunk:
            continue
        start = chunk[0][0]
        end = max(chunk[-1][1], start + 0.8)
        cues.append(f"{len(cues) + 1}\n{stamp(start)} --> {stamp(end)}\n"
                    + " ".join(w[2] for w in chunk) + "\n")
    return "\n".join(cues)


def main():
    ap = argparse.ArgumentParser(description="Make a vertical 9:16 clip from any video.")
    ap.add_argument("video")
    ap.add_argument("--start", help="start time, e.g. 1:05 (default 0)")
    ap.add_argument("--end", help="end time, e.g. 1:30 (default start + 45s)")
    ap.add_argument("--hook", default="", help="on-screen hook text for the first seconds")
    ap.add_argument("--auto-hook", action="store_true",
                    help="write the hook and caption with the local AI from --source-title and what is said in the clip")
    ap.add_argument("--source-title", default="", help="title of the original video (used by --auto-hook)")
    ap.add_argument("--credit", default="", help="who made the footage, e.g. @creator")
    ap.add_argument("--permission", choices=PERMISSIONS,
                    help="own = your footage, official = the publisher's own channel, creator-yes = creator said yes")
    ap.add_argument("--preset", choices=list(PRESETS), default="viral")
    ap.add_argument("--title", default="", help="news preset: headline bar at the top")
    ap.add_argument("--no-captions", action="store_true")
    ap.add_argument("--whisper-model", default="small", help="tiny, base, small, medium (bigger = slower, better)")
    ap.add_argument("--caption-size", type=int, choices=range(24, 161), metavar="24–160")
    ap.add_argument("--credit-position", choices=("bottom-center", "bottom-left", "top-left", "top-center"),
                    default="bottom-center")
    ap.add_argument("--watermark", default=None,
                    help="burn-in text, e.g. @yourhandle (default: brand.json, blank = none)")
    ap.add_argument("--no-watermark", action="store_true", help="turn the watermark off for this clip")
    ap.add_argument("--fit", action="store_true",
                    help="show the whole frame (no zoom, nothing trimmed off the sides) over the blurred background")
    ap.add_argument("--keep", default="",
                    help="only keep these parts of the source, e.g. '41.9-47.0,50.2-55.1' (overrides --start/--end)")
    ap.add_argument("--guide", action="store_true",
                    help="how-to / guide / trick / location clip: keep the setup, steps and payoff; cut intros, "
                         "channel plugs, chatter, long pauses and an unfinished last sentence")
    ap.add_argument("--max-gap", type=float, default=2.5, help="--guide: pauses longer than this get shortened")
    ap.add_argument("--whole", action="store_true",
                    help="use the whole video from start to finish (overrides --start/--end; over 90 s, split it "
                         "with autoclip.py --whole parts)")
    ap.add_argument("--part", default="", help="part label for a video split into parts, e.g. 1/3 (shown with the hook)")
    ap.add_argument("--fps", type=int, default=30, choices=[30, 60])
    ap.add_argument("--out", default=DEFAULT_OUT)
    a = ap.parse_args()

    need("ffmpeg"); need("ffprobe")
    if not os.path.isfile(a.video):
        die(f"Video not found: {a.video}")
    if not a.permission:
        die("Say where the footage comes from with --permission own | official | creator-yes.\n"
            "Credit is not permission. Only clip footage you own, the publisher's official media, or creators who said yes.")
    if a.permission != "own" and not a.credit:
        die("Add --credit (for example @creator, or the publisher's handle). Every non-original clip needs a credit line.")

    p = dict(PRESETS[a.preset])
    if a.caption_size is not None:
        p["cap_size"] = a.caption_size
    dur_total, has_audio, aspect = probe(a.video)
    keep = parse_ranges(a.keep) if a.keep else []
    if keep:
        start, end = keep[0][0], min(keep[-1][1], dur_total)
    elif a.whole:
        start, end = 0.0, dur_total
        print(f"[clipmaker] Whole video: 0 to {dur_total:.1f}s")
    else:
        start = to_secs(a.start) or 0.0
        end = to_secs(a.end) or min(start + 45, dur_total)
        end = min(end, dur_total)
    if end - start < 3:
        die(f"Clip is too short ({end - start:.1f}s). Check --start and --end.")
    span = end - start
    # ivs = the parts of [start, end] that make the final clip, in seconds from start
    ivs = [(max(s - start, 0), min(e, end) - start) for s, e in keep] if keep else [(0.0, span)]

    # Guide trim needs the words even when we don't burn captions (vertical Shorts with their own captions).
    want_words = has_audio and (not a.no_captions or a.guide)
    words = transcribe(a.video, start, end, a.whisper_model) if want_words else []
    words = [(max(s, 0), min(e, span), t) for s, e, t in words if s < span]
    trim_notes = []
    if a.guide and not keep:
        ivs, trim_notes = guide_plan(words, span, max_gap=a.max_gap)
        for n in trim_notes:
            print("[clipmaker] Guide trim: " + n)
    if len(ivs) > 1 or ivs[0] != (0.0, span):
        words = remap_words(words, ivs)
    dur = sum(b - a_ for a_, b in ivs)
    kept_txt = ", ".join(f"{start + a_:.2f}-{start + b:.2f}" for a_, b in ivs)
    if len(ivs) > 1 or ivs[0] != (0.0, span):
        print(f"[clipmaker] Keeping {kept_txt} ({dur:.1f}s of {span:.1f}s)")
    if dur > 90:
        print(f"[clipmaker] Heads up: {dur:.0f}s is long for a Reel. 15 to 60 seconds is the normal range, "
              "up to about 90 for a guide, chase or story. Trim it or split it into parts.")
    elif dur > 60:
        print(f"[clipmaker] Note: {dur:.0f}s is over 60. Fine for a guide, chase or story moment that needs it.")
    spoken_words = words
    if a.no_captions:
        words = []

    value = ""
    if a.auto_hook:
        import hookwriter
        spoken = " ".join(w[2] for w in spoken_words)
        hook, value, how = hookwriter.write(a.source_title or a.hook, spoken)
        a.hook = hook
        print(f"[clipmaker] Hook ({how}): {hook}")
    if a.part:
        a.hook = (a.hook + " " if a.hook else "") + f"(PART {a.part})"

    os.makedirs(a.out, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S%f")
    base = f"{stamp}_{a.preset}_{slug(a.hook or a.title or os.path.splitext(os.path.basename(a.video))[0])}"
    out_mp4 = os.path.join(a.out, base + ".mp4")

    work = tempfile.mkdtemp(prefix="reelhound_")
    watermark = "" if a.no_watermark else a.watermark
    with open(os.path.join(work, "subs.ass"), "w", encoding="utf-8") as f:
        f.write(build_ass(p, words, a.hook, a.credit, dur,
                          a.title if a.preset == "news" else "", a.credit_position,
                          watermark))

    # Size the sharp foreground. The preset zoom widens it past the frame (sides get trimmed), but it must
    # never get taller than the 1920 px frame: vertical Shorts (608x1080) zoomed 1.35x used to overflow and
    # lose ~13% off the top and bottom (HUD, titles, heads). Cap the width so the whole height always fits.
    zoom = 1.0 if a.fit else p["zoom"]
    fg_w = min(W * zoom, H * aspect)
    if fg_w < W * zoom:
        print(f"[clipmaker] Tall source (aspect {aspect:.2f}): fitting the full height instead of zooming.")
    fg_w = max(2, int(fg_w) // 2 * 2)
    loudnorm = "loudnorm=I=-14:TP=-1.5:LRA=11"
    segmented = len(ivs) > 1 or ivs[0] != (0.0, span)
    if segmented:
        # Cut out the removed parts and join the kept ones. Tiny audio fades stop clicks at each join.
        parts, labels = [], ""
        for i, (s, e) in enumerate(ivs):
            parts.append(f"[0:v]trim=start={s:.3f}:end={e:.3f},setpts=PTS-STARTPTS[v{i}]")
            labels += f"[v{i}]"
            if has_audio:
                fo = max(e - s - 0.04, 0)
                parts.append(f"[0:a]atrim=start={s:.3f}:end={e:.3f},asetpts=PTS-STARTPTS,"
                             f"afade=t=in:d=0.03,afade=t=out:st={fo:.3f}:d=0.04[a{i}]")
                labels += f"[a{i}]"
        parts.append(f"{labels}concat=n={len(ivs)}:v=1:a={1 if has_audio else 0}[vcat]" + ("[acat]" if has_audio else ""))
        if has_audio:
            parts.append(f"[acat]{loudnorm}[aout]")
        vin = ";".join(parts) + ";[vcat]"
    else:
        vin = "[0:v]"
    vf = (f"{vin}split=2[bgsrc][fgsrc];"
          f"[bgsrc]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=30:3,eq=brightness=-0.12[bg];"
          f"[fgsrc]scale={fg_w}:-2,crop='min(iw,{W})':'min(ih,{H})'[fg];"
          f"[bg][fg]overlay=(W-w)/2:(H-h)/2,fps={a.fps},format=yuv420p,subtitles=subs.ass[v]")
    cmd = ["ffmpeg", "-y", "-v", "error", "-stats", "-ss", str(start), "-to", str(end), "-i", os.path.abspath(a.video),
           "-filter_complex", vf, "-map", "[v]"]
    if has_audio and segmented:
        cmd += ["-map", "[aout]", "-c:a", "aac", "-b:a", "192k", "-ar", "48000"]
    elif has_audio:
        cmd += ["-map", "0:a:0", "-af", loudnorm, "-c:a", "aac", "-b:a", "192k", "-ar", "48000"]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-profile:v", "high", "-movflags", "+faststart",
            os.path.abspath(out_mp4 + ".part.mp4")]
    print(f"[clipmaker] Rendering {dur:.1f}s {a.preset} clip...")
    r = subprocess.run(cmd, cwd=work)
    shutil.rmtree(work, ignore_errors=True)
    if r.returncode != 0:
        if os.path.exists(out_mp4 + ".part.mp4"):
            os.remove(out_mp4 + ".part.mp4")
        die("FFmpeg failed. Scroll up for the error.")

    caption = "\n".join(x for x in [
        capitalize_terms(a.hook) if a.hook else "[One-line hook]",
        "",
        value or "[1-2 sentences of value: the tip, the trick, what's funny]",
        "",
        f"🎥 {a.credit}" if a.credit else "",
        "",
        brand.hashtags(),
    ] if x)
    with open(os.path.join(a.out, base + ".txt"), "w", encoding="utf-8") as f:
        f.write(caption + "\n\n---\n"
                f"source: {os.path.basename(a.video)}\nrange: {start:.2f} to {end:.2f}\n"
                + (f"kept: {kept_txt} ({dur:.1f}s)\n" if segmented else "")
                + "".join(f"guide trim: {n}\n" for n in trim_notes)
                + f"permission: {a.permission}\ncredit: {a.credit}\npreset: {a.preset}\n"
                + (f"watermark: {watermark}\n" if watermark else "watermark: (none)\n"))
    if words:
        srt = os.path.join(a.out, base + ".srt")
        with open(srt, "w", encoding="utf-8") as f:
            f.write(build_srt(words))
        print(f"[clipmaker] Captions (.srt for uploads): {srt}")
    os.replace(out_mp4 + ".part.mp4", out_mp4)
    print(f"\n[clipmaker] Done: {out_mp4}")
    print(f"[clipmaker] Caption draft: {os.path.join(a.out, base + '.txt')}")


if __name__ == "__main__":
    main()
