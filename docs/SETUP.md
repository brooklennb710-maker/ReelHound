# ReelHound — setup guide

This is the complete install guide, from a blank Windows PC to your first finished clip.
Budget about **15 minutes**; most of it is downloads.

- Just want the short version? [Quick start](#quick-start-the-short-version).
- Already installed and want to use it? See [docs/USER-GUIDE.md](USER-GUIDE.md).

---

## 1. What you need

| Requirement | Why | How you get it |
|---|---|---|
| **Windows 10 or 11** | The double-click launchers are `.bat` files. | Already there. |
| **Python 3.10+** | Runs everything. | `setup.bat` installs it if missing. |
| **FFmpeg + FFprobe** | All cutting, cropping, captions and probing. | `setup.bat` installs it with winget. |
| **~2 GB free disk** | Packages, one Whisper model, a few clips. | — |
| **Internet** | Downloads video, checks APIs. | — |

Optional, add later:

| Optional | Adds | Notes |
|---|---|---|
| **Ollama** | AI-written hooks/captions and a vision-model clip pre-score. | Free, local, ~5 GB of models. |
| **YouTube Data API key** | Keyword search on YouTube. | Free; channels in `creators.csv` are watched without it. |
| **Reddit app ID + secret** | Reddit scanning. | Free, 2 minutes to create. |
| **Instagram Graph token** | Instagram hashtag scanning. | Needs an Instagram Business/Creator account. |
| **Tailscale** | The phone inbox over your own tailnet. | Free for personal use. |
| **A scheduler** (Buffer, Later, Metricool, Meta Business Suite, ...) | Actually publishing the queue. | ReelHound never posts for you. |

> **You do not need an account of any kind to use ReelHound.** Everything runs on your machine.
> The optional API keys above are the only external services, and each one is optional.

---

## Quick start (the short version)

1. Download the repo: **Code → Download ZIP**, then unzip it to a short path such as `C:\ReelHound`.
   (Avoid `Program Files` and OneDrive-synced folders: the tool writes next to itself.)
2. Double-click **`setup.bat`** and let it finish.
3. Double-click **`Start ReelHound.bat`** → the panel opens at <http://127.0.0.1:8875>.

If a window flashed and closed, open **Command Prompt**, `cd` into the folder, and run `setup.bat`
from there so you can read the output. The troubleshooting guide covers the rest.

---

## 2. Run the installer

Double-click **`setup.bat`** in the repo folder. It does five things:

1. Checks Python (installs Python 3.12 with winget if it is missing — then tells you to reopen the window).
2. Installs the Python packages: `requests`, `yt-dlp`, `faster-whisper`, `numpy`.
3. Installs FFmpeg with winget if `ffmpeg` is not on your `PATH`.
4. Copies the example settings into place (never overwriting files that already exist):
   `hunter/config.json`, `hunter/creators.csv`, `hunter/finds.csv`,
   `control-panel/schedule.json`, `scoreboard.csv`.
5. Runs the first-run questions, then `doctor.py` to check the result.

### What the questions mean

| Question | Example | Notes |
|---|---|---|
| Your handle | `@yourpage` | Printed on credit lines and used in permission messages. |
| Page/channel name | `Your Page` | What people read in your messages. |
| Niche, a few words | `gaming clips` | Goes into the AI prompts ("a gaming clips page"). |
| Watermark | `@yourpage` | Burned into clips. **Blank = no watermark.** You can also change it per clip. |
| Default hashtags | `#reels #shorts` | Appended to every caption draft. |
| Time zone | blank = this PC's | Only for the posting queue. An IANA name like `Europe/London` also works. |
| Where do you post? | `Instagram Reels, TikTok` | Drives the Destinations checkboxes in the queue. |
| Search terms | `game clips, funny moments` | What the hunter searches for. Editable later on the Hunter page. |
| Subreddits | `gaming, videos` | Reddit scanning. |
| Instagram hashtags | `gaming, gamingclips` | Instagram scanning (needs a token). |

All answers land in two files you can edit by hand at any time: `brand.json` and `hunter/config.json`.
Nothing is hidden in a database.

> **Skipped the questions?** Run `python reelhound.py init` whenever you want.

---

## 3. Check the install (recommended)

Open Command Prompt in the repo folder and run:

```
python reelhound.py doctor
```

You will get a list like this:

```
[OK  ] Python: 3.14.6
[OK  ] FFmpeg: ffmpeg version 9.0.2-full_build
[OK  ] requests / yt-dlp / faster-whisper / numpy: installed
[WARN] brand.json: not set up yet
         fix: Run: python reelhound.py init
[OK  ] folders: all present
[OK  ] Ollama (optional): running, 3 model(s)
...
Ready to use. 2 optional/setup item(s) above (WARN) - see the fix lines.
```

How to read it:

- **`OK`** — nothing to do.
- **`WARN`** — optional or not-configured-yet. The tool still runs, just with fewer features.
- **`FAIL`** — something is genuinely missing. The `fix:` line tells you exactly what to run.

Then prove the renderer works:

```
python reelhound.py selftest
```

It builds a small test video with FFmpeg, renders a real 6-second 1080×1920 clip with the same code
your own clips use, checks the result with ffprobe and cleans up. If that ends with
`Everything works`, you are ready.

---

## 4. Optional: AI hooks and clip scoring (Ollama)

ReelHound writes hooks and captions with a **local** language model, and can pre-score finished clips
with a local vision model. Both are optional — without Ollama the hook writer falls back to a cleaned-up
version of the video title, and clip review is still fully manual.

1. Install Ollama from <https://ollama.com/download> (free, Windows/Mac/Linux).
2. Pull the two default models:

   ```
   ollama pull qwen3.5:9b      REM hook + caption writer
   ollama pull gemma4:12b      REM clip scoring (vision)
   ```

3. That's it — ReelHound talks to `http://127.0.0.1:11434` when it is running.

**Use different models?** Set them in `hunter/config.json`:

```json
"hook_model": "qwen3.5:9b",
"review_model": "gemma4:12b"
```

The reviewer deliberately shares the graphics card: it waits for other GPU programs (ComfyUI on port
8188 by default), waits for enough free graphics memory, and unloads the model when it is done.
Use `--cpu` on `Review Clips (local AI).bat` or `python reelhound.py review --cpu` to keep it on the processor.

---

## 5. Optional: search sources and their keys

The hunter is only as good as its sources. **Channels listed in `hunter/creators.csv` are always
watched without any key.** The keys below add discovery.

### YouTube keyword search (free)

1. Go to <https://console.cloud.google.com/>, create a project.
2. **APIs & Services → Library → YouTube Data API v3 → Enable**.
3. **Credentials → Create credentials → API key**, then copy it.
4. Paste it into `hunter/config.json` as `"youtube_api_key"`, or on the panel's **Hunter** page.
5. Optional: set `"youtube_channel_id"` to your own channel ID (`UC…`) to watch your own uploads.

Free quota is 10,000 units/day; one search costs ~100, so the defaults (one or two searches per scan)
stay comfortably inside it.

### Reddit (free, 2 minutes)

1. While signed in, open <https://www.reddit.com/prefs/apps> → **create another app**.
2. Choose **script**, any name, redirect URL `http://localhost:8080`.
3. Copy the ID (under the app name) and the secret.
4. Paste into `hunter/config.json`: `reddit.client_id` and `reddit.client_secret`.

### Instagram hashtag search (optional, fiddly)

Needs an Instagram **Business or Creator** account linked to a Facebook Page, plus a Facebook app with
the Instagram Graph API. Put `instagram.ig_user_id` and a long-lived `instagram.access_token` in
`hunter/config.json`. Instagram finds are **never auto-downloaded** — they are saved to the finds page for
you to handle by hand.

### When YouTube blocks downloads ("sign in to confirm you're not a bot")

Pick one:

- **Cookies file:** export your own YouTube cookies with a browser extension to
  `hunter/youtube_cookies.txt` (Netscape format). Never share or commit this file.
- **Browser cookies:** set `"cookies_from_browser": "chrome"` (or `firefox`, `edge`, `brave`) in
  `hunter/config.json`.

YouTube's anti-bot challenge sometimes needs yt-dlp's challenge solver:
`python -m pip install -U yt-dlp-ejs`.

---

## 6. Your first clip (three ways)

**A. Drag and drop (simplest).** Drag a video onto `clipmaker\make_clip.bat`. Answer:
where the footage is from (own / official / creator said yes), the credit handle, start and end,
a hook, a style. The finished clip and a caption draft land in `media\edits`.

**B. The panel.** Double-click `Start ReelHound.bat`. On **Overview**, switch **Clip maker** on and it
will render new downloads automatically. The **Editing** page has the settings and a whole-video repost box.

**C. Command line.**

```
python reelhound.py clip "C:\videos\myclip.mp4" --start 0:12 --end 0:38 --permission own --preset viral --hook "THE TRICK NOBODY SHOWED YOU"
python reelhound.py auto "C:\videos\myclip.mp4" --count 3 --length 40
python reelhound.py batch "D:\footage" --mode moments --count 3
```

Every command forwards extra flags, so `python reelhound.py clip --help` shows the full option list.

---

## 7. Optional: the phone inbox

Send a link (or a file) from your phone and have the clip waiting on your PC:

1. Install **Tailscale** on the PC and the phone, signed in to the same tailnet.
2. Create `inbox/config.json` from `inbox/config.example.json`. Put your own handles in `my_accounts`
   so links to your own posts count as *own*. Set `"cookies_from_browser"` if Instagram refuses downloads.
3. Double-click `inbox\Open Phone Inbox.bat` (it runs `tailscale serve` for you, tailnet only).
4. On the phone, open `https://YOUR-PC-NAME.YOUR-TAILNET.ts.net`.

`Start ReelHound.bat` also starts the inbox minimized. If you do not use it, you can ignore this section.

---

## 8. Optional: keep the hunter running

The hunter scans on an interval (`every_minutes`, default 45). Two ways to keep it alive:

- Double-click `hunter\start_hunter.bat`; close the window to stop.
- Or use the panel: **Overview → Hunter** worker on (the panel must stay open).

To start it at logon, create a **Task Scheduler** task with the action
`C:\ReelHound\hunter\start_hunter.bat`, "Start in" `C:\ReelHound\hunter`, and *Run whether user is
logged on or not* off (so you can see the window).

---

## 9. Updating, backup and uninstall

**Update:** download the new release, then copy these over your install — **keep** your data files:
`brand.json`, `hunter/config.json`, `hunter/creators.csv`, `hunter/finds.csv`, `control-panel/schedule.json`,
`scoreboard.csv`, `media/`. Everything else can be replaced.

**Back up:** those same files plus `media/ready`. That is the whole state of the tool.

**Uninstall:** delete the folder. Nothing is installed system-wide except Python and FFmpeg
(remove them normally if you want them gone) and the Whisper model cache in
`%USERPROFILE%\.cache\huggingface`.

---

## 10. Privacy and safety

- The control panel, the finds page and the phone inbox all bind to `127.0.0.1` only.
- Each panel run mints a fresh random token; API calls need it, and the server rejects cross-site requests.
- `hunter/config.json`, `inbox/config.json`, `brand.json`, cookies and all media are in `.gitignore`.
  Check `git status` before pushing your fork.
- ReelHound never posts anything. It only writes files and a local queue.

---

## 11. Setup checklist

- [ ] `setup.bat` finished without a red error
- [ ] `python reelhound.py doctor` shows no `FAIL`
- [ ] `python reelhound.py selftest` says *Everything works*
- [ ] `brand.json` has your handle (or you do not want a watermark)
- [ ] `hunter/creators.csv` lists your own channel and anyone who has said yes
- [ ] `Start ReelHound.bat` opens the panel
- [ ] Optional: Ollama models pulled, API keys pasted in

Next: **[docs/USER-GUIDE.md](USER-GUIDE.md)** for the day-to-day workflow.
