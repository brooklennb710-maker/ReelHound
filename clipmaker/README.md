# clipmaker/

Turns a video into a vertical 1080×1920 clip: 9:16 framing over a blurred copy of the source, on-screen
hook, word-level captions, credit line, optional watermark, loudness-normalised audio, and a caption draft.

| Script | What it does |
|---|---|
| `clipmaker.py` | Renders one clip. Start here. |
| `autoclip.py` | Picks the best moments (or the whole video / parts) and calls the clip maker. |
| `hookwriter.py` | Ollama hook + caption writer, with a rule-based fallback. |
| `reclip.py` | Re-cuts a finished clip earlier/later from its source, redoing captions and credit. |
| `wholejob.py` | Whole-video repost as one clip or numbered parts (used by the panel). |
| `regen_hooks.py` | Re-renders existing clips with new AI hooks/captions. |

## The easy way

- Drag a video onto **`make_clip.bat`** — asks where it is from, credit, start/end, hook, style.
- Drag your own footage onto **`auto_clip.bat`** — best moments, whole video, parts, or first 90 s.

## Command line

```
python reelhound.py clip VIDEO.mp4 --start 0:12 --end 0:38 --hook "THE TRICK NOBODY SHOWED YOU" \
    --permission creator-yes --credit @creator --preset viral
python reelhound.py auto VIDEO.mp4 --count 3 --length 40
python reelhound.py auto VIDEO.mp4 --own --whole            one clip (over 90 s needs parts/cap)
python reelhound.py auto VIDEO.mp4 --own --whole parts      numbered parts of about a minute
python reelhound.py batch "D:\footage"                      every video in a folder
```

Every flag is documented in [../docs/USER-GUIDE.md](../docs/USER-GUIDE.md#clip--one-clip-exact-control).

## Styles

| Preset | Look | Hook | Captions |
|---|---|---|---|
| `viral` | zoomed source | 3.5 s, big | 92 px, 3 words, spoken word highlighted |
| `clean` | full frame | 2.5 s | 60 px, 6 words, plain |
| `news` | full frame + headline bar | none | 66 px, 5 words, plain |

## What each render writes

```
media/edits/<stamp>_<preset>_<slug>.mp4   the clip
media/edits/<stamp>_<preset>_<slug>.txt   caption draft + a "key: value" metadata block
media/edits/<stamp>_<preset>_<slug>.srt   standard captions, when the clip has speech
```

The metadata block (`source:`, `range:`, `permission:`, `credit:`, `preset:`, `watermark:`) is what
re-clip, the review board and `pack` read. Leave it at the bottom of the `.txt`.

## How captioning works

1. FFmpeg decodes the audio range to 16 kHz mono float (no PyAV, so no version conflicts).
2. faster-whisper transcribes with word timestamps and voice-activity filtering, on the GPU when available
   (float16) and on the CPU otherwise (int8).
3. Non-English speech is translated to English.
4. Words are laid out in groups per line; in `viral`, one event per word so the spoken word lights up.

No faster-whisper? Clips still render, just without captions.

## How the best moments are picked

`autoclip.py` reads the audio loudness curve at 0.5 s resolution and FFmpeg scene changes, scores windows
for loudness plus visual change, avoids the first and last seconds, and renders up to `--count` windows.
Guide-like titles (how to, tips, guide, tutorial, secret, location...) also get the `--guide` trim.

## Guide trim

`--guide` keeps the setup, the steps and the payoff, and cuts intros, channel plugs, repeated sentences,
pauses over `--max-gap` seconds, and a sentence the range cut in half. `--keep "a-b,c-d"` overrides it with
exact ranges. It prints what it removed and records it in the caption sidecar.

## Rules built in

- It refuses to run without `--permission own|official|creator-yes`.
- Non-original footage needs `--credit`, which is burned on screen (`via @handle`) and written into the caption.
- Watermark comes from `brand.json`; `--watermark` / `--no-watermark` override it per clip.
