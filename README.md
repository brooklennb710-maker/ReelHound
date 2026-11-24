# ReelHound 🎬

**Find it. Clip it. Post it.** — a free, local, open-source clipping pipeline by [BridgesTech](https://github.com/BridgesTech).

ReelHound watches the places your niche is discussed (YouTube, Reddit, Instagram hashtags), ranks
what it finds, downloads the videos you are allowed to use, cuts them into vertical 1080×1920 clips
with burned-in captions, and keeps a review board plus a posting queue — all on your own PC, with no
accounts, no cloud and no subscriptions.

It does one job well: **get a good clip from "found" to "ready to upload" in as few clicks as possible.**

```
Hunter  ──▶  media/raw  ──▶  Auto-clip  ──▶  media/edits  ──▶  Review  ──▶  media/ready  ──▶  Queue  ──▶  Upload
(find)       (download)      (verticals)      (your board)     (keep)       (approved)      (schedule)
```

## Quick start (Windows)

1. **[Download the repo](https://github.com/BridgesTech/reelhound/archive/refs/heads/main.zip)** and unzip it anywhere (e.g. `C:\ReelHound`).
2. Double-click **`setup.bat`**. It installs Python packages and FFmpeg, copies the sample settings and asks a few questions.
3. Double-click **`Start ReelHound.bat`**. The control panel opens at `http://127.0.0.1:8875`.

That's the whole install. The full walkthrough is in **[docs/SETUP.md](docs/SETUP.md)**.

Unsure whether everything works? `python reelhound.py doctor` checks every dependency and prints the
exact fix, and `python reelhound.py selftest` renders a real test clip end to end.

## What's inside

| Command | What it does |
|---|---|
| `python reelhound.py panel` | The local control panel: workers, settings, creators, clip review, schedule (also `Start ReelHound.bat`). |
| `python reelhound.py hunt` | Scans your sources, scores finds 0–100, downloads cleared creators, drafts permission DMs (`--loop` to keep scanning). |
| `python reelhound.py clip VIDEO` | Cuts one vertical clip: hook text, Whisper captions, credit, watermark, caption draft (`drag onto make_clip.bat`). |
| `python reelhound.py auto VIDEO` | Finds the best moments automatically and renders up to N clips (`drag onto auto_clip.bat`). |
| `python reelhound.py batch DIR` | Clips every video in a folder, resumable, one bad file never stops the run. |
| `python reelhound.py pack` | Bundles ready clips + captions + `.srt` + `manifest.csv` into a folder and zip for uploading. |
| `python reelhound.py review` | Scores finished clips with a local vision model so you only watch the good ones. |
| `python reelhound.py inbox` | Phone inbox: paste links or drop videos from your phone over your own tailnet. |
| `python reelhound.py doctor` | Checks Python, FFmpeg, packages, models, config and ports. |
| `python reelhound.py init` | First-run questions (handle, niche, watermark, search terms). |
| `python reelhound.py selftest` | Proves the install renders a real 1080×1920 clip. |

## Features

- **Vertical clips from any video** — 9:16 frame over a blurred copy of the source, capped so tall sources never lose the top or bottom. `--fit` shows the whole frame instead.
- **Captions that follow the voice** — word-level Whisper transcription, highlighted word by word in the *Viral* style, plain in *Clean*, headline bar in *News*. Auto-translates non-English speech to English. Writes a companion `.srt` too.
- **Hooks and captions** — a local Ollama model writes the hook and post text from the title and what is said in the clip, with strict rules (complete phrases, no clickbait, no spoilers). Falls back to a cleaned-up title when Ollama is off.
- **Guide trim** — for how-to clips, `--guide` drops intros, channel plugs, repeated lines and long pauses, keeps the steps and the payoff, and ends on a full sentence. `--keep` cuts exact ranges by hand.
- **Whole-video reposts** — one clip up to 90 s, or split a long video into numbered parts at the quietest moment near each boundary.
- **Re-clip** — a finished clip starts too late? Re-cut it 5 seconds earlier from the original with all captions and credit redone.
- **Permission-first** — nothing is clipped without `own`, `official` or a recorded yes in `creators.csv`. Non-original footage always carries an on-screen credit and a caption credit. Ready-to-send permission messages are drafted for everything else.
- **Clip review board** — watch, filter, search, fix the caption, keep or delete. A local vision model can pre-score everything from five frames.
- **Posting queue** — slots in your time zone, a configurable posting day, per-destination targeting, and a JSON export for any scheduler.
- **Publish pack** — one command to hand off a batch of clips with everything the uploader needs.
- **Batch mode** — point it at a folder of footage and walk away.
- **Your branding, one file** — `brand.json` holds your handle, channel, niche, watermark, hashtags and destinations. A fresh clone runs on neutral defaults.

## Requirements

- **Windows 10/11** (the launchers are `.bat` files; the Python itself runs on macOS/Linux with small changes).
- **Python 3.10+** and **FFmpeg** — `setup.bat` installs both for you.
- Optional: **Ollama** for AI hooks and clip scoring (free, runs locally), **Tailscale** for the phone inbox.

Nothing is uploaded anywhere. The panel listens on `127.0.0.1` and uses a fresh token each run.

## Repository layout

```
reelhound.py          one command for everything          brand.json / brand.example.json   your identity
doctor.py             environment check                   setup_wizard.py  setup.bat        first run
selftest.py           end-to-end proof                    batch_clip.py / pack.py          bulk + handoff
hunter/               search, score, download, permissions, find page
clipmaker/            clip renderer, auto-clipper, hook writer, re-clip, whole-video repost
control-panel/        local web panel + its server
reviewer/             local vision-model pre-filter
inbox/                phone inbox server and page
media/                raw → edits → ready (git-ignored, only the empty skeleton ships)
docs/                 SETUP, USER-GUIDE, PLAYBOOK, TROUBLESHOOTING
```

## Documentation

- **[Setup guide](docs/SETUP.md)** — install, API keys, AI models, phone inbox, first clip.
- **[User guide](docs/USER-GUIDE.md)** — every command and setting, in order of a normal day.
- **[Playbook](docs/PLAYBOOK.md)** — permission, credit, what earns a post, posting rhythm.
- **[Troubleshooting](docs/TROUBLESHOOTING.md)** — when something says no.

## Use it responsibly

ReelHound is a tool for **clipping content you own or have permission to use**. It does not download
around logins, bypass paywalls, or strip credit — it refuses to render a third-party clip without a
recorded permission and a credit. Read [docs/PLAYBOOK.md](docs/PLAYBOOK.md) before your first post:
permission, credit and attribution are not optional extras, they are the licence to publish.

You are responsible for what you publish and for the terms of the platforms you publish to.

## Licence

MIT — see [LICENSE](LICENSE). Use it, fork it, ship it; a link back is appreciated.
