"""Hook and caption writer for the clip maker.

Uses a local Ollama text model to write a short, complete, English on-screen hook
and a 1-2 sentence caption for ONE clip, from the source video title and what is
said in that clip. Falls back to a cleaned-up version of the title if Ollama is
not running. Free and offline.

Pick the model with "hook_model" in hunter/config.json (default qwen3.5:9b).
"""
import json
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import brand  # noqa: E402  (channel name and niche go into the prompt)

OLLAMA = "http://127.0.0.1:11434/api/chat"
MODEL = "qwen3.5:9b"
CONFIG = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "hunter", "config.json"))

# Words a hook should never end on ("5 SECRET WAYS TO", "TIPS I WISH I").
DANGLING = {"in", "to", "a", "an", "the", "of", "you", "i", "get", "never", "not", "most", "wish", "for", "with",
            "and", "on", "at", "your", "my", "about", "this", "that", "can", "is", "are", "be", "from", "&", "+",
            "or", "it", "we", "so", "but", "if", "its", "it's", "s"}

PROMPT = """You write on-screen hooks and captions for {channel}, a {niche} page on Instagram and Facebook Reels.

One vertical clip was cut from a creator's video.
Source video title: "{title}"
What is said in this clip (auto-transcribed, may contain errors; empty if nobody talks):
\"\"\"{transcript}\"\"\"

Write:
1. hook: the on-screen text shown in the first second. 2 to 6 words, plain English, a COMPLETE phrase
   (never ends mid-sentence), punchy, about what THIS clip shows. Use specifics from the transcript when
   they exist (the subject, the number, the trick). Do not name the topic or fandom itself, do not use
   hashtags, emojis, creator names or quotes. Never promise something the clip may not show. No story
   spoilers. Never sound official.
   Style examples only (never copy them; they are about other clips): "THIS CHANGES EVERYTHING",
   "FREE CASH SECRET CODE", "THE PHYSICS ARE UNREAL". If the transcript is empty, base the hook on the title.
2. caption: 1 or 2 short sentences in plain English for the post text: the tip, the trick, or what is funny.
   Only state what the title or transcript actually supports; if unsure, describe it loosely. No hashtags,
   never say "this clip" or "this video", at most one emoji, sentence case."""

EXAMPLES = {"THIS CHANGES EVERYTHING", "FREE CASH SECRET CODE", "THE PHYSICS ARE UNREAL", "WAIT FOR IT"}

SCHEMA = {"type": "object",
          "properties": {"hook": {"type": "string"}, "caption": {"type": "string"}},
          "required": ["hook", "caption"]}


def configured_model():
    try:
        with open(CONFIG, encoding="utf-8-sig") as file:
            return (json.load(file).get("hook_model") or "").strip() or MODEL
    except (OSError, ValueError):
        return MODEL


def clean_title(title):
    """Rule-based fallback hook from a video title: cut at a natural break, never mid-sentence."""
    t = re.sub(r"#\w+", "", title or "")
    t = re.sub(r"[\[\(].*?[\]\)]", "", t)
    t = re.split(r"\s[|–—]\s|:\s|\.\.\.|…", t)[0]
    t = re.sub(r"[^\w\s'!?$%,&+]", " ", t)
    t = re.sub(r"\s+", " ", t).strip(" -|:.,'")
    words = [w for w in t.split() if re.search(r"\w", w)][:6]
    while words and re.sub(r"[!?.,]+$", "", words[-1]).lower() in DANGLING:
        words.pop()
    hook = " ".join(words).upper().rstrip(",")
    return hook if len(words) >= 2 and not SPOILER.search(hook) else "WAIT FOR IT"


def good_hook(h):
    h = (h or "").strip().strip('"').upper()
    words = h.split()
    if not 2 <= len(words) <= 7 or len(h) > 42:
        return ""
    if re.search(r"[^\x20-\x7e]", h) or "#" in h:
        return ""
    if re.sub(r"[!?.,]+$", "", words[-1]).lower() in DANGLING:
        return ""
    if SPOILER.search(h):
        return ""  # no story spoilers in the hook
    return h


SPOILER = re.compile(r"(?i)\b(died|dies|dead|death|killed|kills|ending|finale|final mission|last mission|betray\w*|"
                     r"twist|spoiler|credits)\b")


def good_caption(c):
    c = re.sub(r"#\w+", "", (c or "")).strip()
    if not c or len(c) > 260 or re.search(r"[Ѐ-￿]", re.sub(r"[\U0001F000-\U0001FFFF☀-➿]", "", c)):
        return ""
    return c


def write(title, transcript="", model=None, timeout=120):
    """Returns (hook, caption, source) where source is 'ai' or 'fallback'."""
    model = model or configured_model()
    caption = ""
    try:
        for temp in (0.3, 0.7, 0.9):  # retry when the model breaks the hook rules
            body = {"model": model, "stream": False, "think": False, "format": SCHEMA,
                    "options": {"temperature": temp, "num_ctx": 4096},
                    "messages": [{"role": "user", "content": PROMPT.format(
                        channel=brand.channel(), niche=brand.niche(), title=title or "", transcript=(transcript or "")[:1500])}]}
            req = urllib.request.Request(OLLAMA, json.dumps(body).encode(), {"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                out = json.loads(json.loads(r.read())["message"]["content"])
            hook, caption = good_hook(out.get("hook")), good_caption(out.get("caption")) or caption
            if hook and hook not in EXAMPLES:
                return hook, caption, "ai"
    except Exception as e:
        print(f"[clipmaker] Local hook writer unavailable ({e}); using the cleaned title.")
    return clean_title(title), caption, "fallback"


if __name__ == "__main__":
    for t in sys.argv[1:] or ["THE SECRET EVERYONE MISSED — HIDDEN LEVEL & FREE CASH INSIDE #gaming",
                              "5 SECRET Tricks You Never Noticed", "This Tip Changed Everything..."]:
        print(clean_title(t), "|", write(t))
