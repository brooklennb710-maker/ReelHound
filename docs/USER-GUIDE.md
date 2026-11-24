# ReelHound — user guide

Everything ReelHound can do, in the order you will need it.
New here? Do [docs/SETUP.md](SETUP.md) first.

---

## The shape of a day

```
1. Hunt       find new videos in your niche, score them, download the ones you're cleared to use
2. Clip       best moments (auto) or exact ranges (manual), vertical, captioned, credited
3. Review     watch in the panel, fix the caption, keep or delete
4. Queue      schedule keepers into slots; destinations per clip
5. Pack       one folder + zip with clips, captions, .srt and a manifest
6. Upload     any scheduler; then log the result in the scoreboard
```

You can skip any step. Manual clipping with a single file works with no hunter, no keys and no Ollama.

---

## The control panel

Double-click `Start ReelHound.bat`, or `python reelhound.py panel`.
It opens `http://127.0.0.1:8875` and only listens on your machine.

| Page | What you do there |
|---|---|
| **Overview** | Two workers — **Hunter** and **Clip maker** — with live logs, today's numbers, the latest clip, AI picks, a quick whole-video repost box, and quick file links. Workers start **off**; turn on what you need. |
| **Hunter** | Scan interval, minimum score, search terms, sources, subreddits, hashtags and API keys. Secrets are write-only: the panel shows "saved", never the value. |
| **Creators** | The permission ledger (`hunter/creators.csv`). Add a creator, set `own` / `yes` / `no` / `asked` / `official`, and see everything waiting on a reply with its draft message. |
| **Editing** | Defaults for new clips: length, clips per video, caption style/size, Whisper model, captions on/off, credit text/position, and whole-video reposting. |
| **Clip review** | The board: watch each clip, search and filter by creator, type, verdict, score, length, style and age. Edit the caption inline, **Keep** (moves to `media/ready`), **Delete**, or **Re-clip** wider. |
| **Schedule** | Posting times, posting-day start, posts per day, then add a ready clip to the next free slot per destination. Exports the queue as JSON. |
| **Scoreboard** | Reads `scoreboard.csv` and shows totals, 24-hour views and your best post. |

Tip: the panel is a thin local UI over plain files. Close the browser and everything keeps running;
close the window and the workers stop.

---

## Commands

All commands are available as `python reelhound.py <command>` and as standalone scripts.

### `hunt` — find videos worth clipping

```
python reelhound.py hunt                  one scan
python reelhound.py hunt --loop           keep scanning every N minutes
python reelhound.py hunt --loop --open    same, and open the finds page
```

For every candidate it computes a 0–100 score: recent-ness, views/likes per hour, engagement,
and how many of your `score_words` appear in the title. Anything with a `block_words` term scores 0.
Videos from creators marked `own`, `yes` or `official` in `creators.csv` are downloaded to `media/raw`
and auto-clipped; everyone else is queued on the finds page with a draft permission message.

The finds page (`http://localhost:8765` while the hunter runs) lists finds from the last 48 hours with
**Yes, they said ok** buttons that add the creator to `creators.csv` and start their download.

### `clip` — one clip, exact control

```
python reelhound.py clip VIDEO.mp4 --start 0:12 --end 0:38 --hook "THE TRICK NOBODY SHOWED YOU" --permission creator-yes --credit @creator
```

| Flag | Meaning |
|---|---|
| `--start`, `--end` | Range to cut (`mm:ss` or seconds). Default: 0 → start + 45 s. |
| `--whole` | Use the whole video (over 90 s, split it with `auto --whole parts`). |
| `--keep "41.9-47,50.2-55"` | Keep only these ranges and join them. Overrides start/end. |
| `--guide` / `--max-gap` | How-to trim: cut intros, plugs, repeats and pauses over `--max-gap` seconds; keep the payoff. |
| `--permission own\|official\|creator-yes` | **Required.** Where the footage comes from. |
| `--credit @handle` | **Required** unless `own`. Goes on screen as `via @handle` and in the caption. |
| `--preset viral\|clean\|news` | Caption style (see below). |
| `--hook "TEXT"` | On-screen hook for the first seconds. |
| `--auto-hook` | Let the local AI write the hook and caption from `--source-title` and the transcript. |
| `--title "HEADLINE"` | News preset: the top bar text. |
| `--no-captions` | Skip Whisper entirely. |
| `--whisper-model tiny\|base\|small\|medium\|large-v3` | Accuracy vs speed. Default `small`. |
| `--caption-size 24-160` | Override the preset's caption size. |
| `--credit-position` | `bottom-center` (default), `bottom-left`, `top-left`, `top-center`. |
| `--watermark "TEXT"` / `--no-watermark` | Burn-in text. Default comes from `brand.json`; `--no-watermark` wins. |
| `--fit` | Show the whole frame over the blur instead of zooming (good for tall sources). |
| `--part "1/3"` | Label a part with the hook. |
| `--fps 30\|60` | Output frame rate. |

**Presets**

| Preset | Look |
|---|---|
| `viral` | Zoomed-in source, huge word-by-word highlighted captions, 3.5 s hook. |
| `clean` | Full frame, smaller plain captions, 2.5 s hook. |
| `news` | Headline bar at the top, hook under it, clean captions. |

Each render writes three files to `media/edits`: the `.mp4`, a `.txt` caption draft (with a metadata
block after `---`), and a `.srt` when there was speech. The metadata block is what re-clip and the panel
read, so leave it in place.

### `auto` — best moments, no watching

```
python reelhound.py auto VIDEO --count 3 --length 40
python reelhound.py auto VIDEO --own --whole            one clip, up to 90 s
python reelhound.py auto VIDEO --own --whole parts      long video → numbered parts
python reelhound.py auto VIDEO --own --whole cap        first 90 s only
```

It reads the audio loudness curve and scene changes, picks the strongest windows, avoids the first and
last few seconds, and renders each one. Parts are cut at the quietest point near each boundary, and the
hook gets `(PART 1/3)`. Guide-style titles automatically get the `--guide` trim unless you pass
`--no-guide-trim` or set `"guide_trim": false`.

New downloads from the hunter are clipped this way automatically when the **Clip maker** worker is on
(or `"auto_clip": true` for the standalone hunter). `clipmaker/autoclip_done.json` remembers what was
already done; delete a line to re-clip that video.

### `batch` — a whole folder

```
python reelhound.py batch "D:\footage"                    best moments, 3 clips per video
python reelhound.py batch "D:\footage" --mode whole       one clip per video
python reelhound.py batch "D:\footage" --recursive --limit 10
python reelhound.py batch "D:\footage" --dry-run          list what would happen
python reelhound.py batch clip1.mp4 clip2.mp4 --count 5 --preset clean
```

Own footage is the default. A video with a `<name>.source.json` note (written by the hunter and the phone
inbox) is clipped with that note's permission and credit instead. Progress is remembered in
`clipmaker/batch_done.json` (`--redo` ignores it) and logged to `clipmaker/batch.log`.

### `pack` — hand off for uploading

```
python reelhound.py pack                  media/ready -> publish_pack/ + publish_pack.zip
python reelhound.py pack --area edits     clips still in review
python reelhound.py pack --limit 5
python reelhound.py pack --out D:\drop
```

The pack contains `clips/`, `captions/` (`.txt` + `.srt`), `manifest.csv` (file, caption, credit, preset,
seconds, permission, destinations, scheduled slot, source) and an `index.html` preview page you can open
to watch everything and copy captions. Files are **copied**, never moved.

### `review` — score clips before you watch them

```
python reelhound.py review                score new/changed clips in media/edits
python reelhound.py review --cpu          processor only, no GPU
python reelhound.py review --top 20 --wait 10
```

Builds a 5-frame contact sheet per clip, asks a local vision model to score hook, payoff, standalone and
phone-readability, applies ffmpeg checks (length, aspect, audio, loudness, black frames) and writes
`reviewer/results.csv` plus `reviewer/top.html`. Results are cached; only new or changed clips are scored.
It is a shortlist, not a decision — it cannot hear audio or see motion.

### `inbox` — clip from your phone

```
python reelhound.py inbox
```

Serves the phone page on `127.0.0.1:8876` (share it with `tailscale serve`, tailnet only). Paste links or
upload a file, mark it **mine** or **someone else's**, tick *whole video* or *it's a guide*, and the PC
downloads, checks permission against `creators.csv`, clips it, and puts the result in `media/edits`.
Unknown creators are held in `media/raw/phone-inbox` with a draft message and nothing is sent.

### `doctor`, `init`, `selftest`

```
python reelhound.py doctor     check the install, with a fix line for every problem
python reelhound.py init       first-run questions (safe to re-run)
python reelhound.py selftest   render a real test clip end to end
```

---

## Settings files

### `brand.json` — your identity

Copy `brand.example.json` to `brand.json` (the setup wizard does it). Git-ignored.

| Key | Used for |
|---|---|
| `app`, `company`, `tagline` | Window titles, panel header, docs. Keep defaults to stay "ReelHound by BridgesTech". |
| `handle` | Your @handle in messages and credits. |
| `channel` | Page/channel name in permission messages. Falls back to `handle`, then `app`. |
| `niche` | A few words about the channel; goes into AI prompts. |
| `watermark` | Burn-in text on clips. **Blank = none.** |
| `accent` | Theme accent colour for the panel. |
| `timezone` | IANA name (`Europe/London`) or blank for this PC's zone. |
| `destinations` | Checkboxes in the posting queue. |
| `caption_hashtags` | Appended to caption drafts (list or space-separated string). |

### `hunter/config.json` — what to look for

Copy `hunter/config.example.json` to `hunter/config.json`. Git-ignored.

| Group | Keys |
|---|---|
| **Sources** | `sources.youtube`, `sources.reddit`, `sources.instagram`, `youtube_api_key`, `youtube_channel_id`, `subreddits`, `instagram.*`, `reddit.*`, `cookies_file`, `cookies_from_browser`, `page_port` |
| **Search** | `keywords`, `keywords_per_run`, `lookback_hours`, `every_minutes`, `min_score`, `max_downloads_per_run`, `max_video_minutes` |
| **Scoring** | `score_words` (word → points), `block_words` (score 0), `must_include` (only titles containing one of these), `priority_words` (+5) |
| **Clipping** | `auto_clip`, `clips_per_video`, `clip_seconds`, `clip_preset`, `captions`, `whisper_model`, `caption_size`, `credit_text`, `credit_position`, `guide_trim` |
| **AI** | `hook_model`, `review_model` |
| **Panel** | `page_port` (finds page) |

`credit_text` supports `{creator}` — e.g. `"reposted with permission · {creator}"`.

### `hunter/creators.csv` — the permission ledger

```
platform,handle,channel_id,permission,contact,notes
youtube,yourchannel,PASTE_YOUR_CHANNEL_ID,own,,your own channel
youtube,Some Creator,UCxxxxxxxxxxxxxxxxxxxxxx,yes,creator@example.com,said yes 2026-01-01
```

| Permission | Clips allowed? |
|---|---|
| `own` | Yes, and no credit required. |
| `yes` | Yes, credit required. |
| `official` | Yes (the brand's own uploads), credit required. |
| `asked` | No — waiting. Shows on the waiting list with a message. |
| `no` | Never. Skipped everywhere. |
| `unknown` / missing | No. Queued for a permission message. |

### `control-panel/schedule.json` — the posting queue

`times` (HH:MM), `posts_per_day`, `day_start` (anything earlier counts toward the previous posting day),
and `items` with `name`, `channels`, `utc`, `posting_day`. The panel writes it; you can edit it.

### `scoreboard.csv` — results

Free-form CSV read by the Scoreboard page. The sample header is a good starting point:
`date, clip, hook, platform, destinations, views_12h, views_24h, views_72h, likes, comments, shares, saves, note`.

---

## Folders

```
media/raw/            downloads (the hunter, the panel, the phone inbox)
media/raw/phone-inbox/ links that came from your phone
media/official/       the publisher's own media
media/edits/          finished clips waiting for review (+ .txt and .srt sidecars)
media/ready/          approved clips, the ones the queue and `pack` use
media/_not-cleared/   held until permission arrives
control-panel/deleted/  clips you deleted in review (restorable)
```

---

## When something looks wrong

| Symptom | Try |
|---|---|
| Clip is black or empty | `python reelhound.py doctor`; check `--start`/`--end` with `ffprobe -v error -show_entries format=duration -of csv=p=0 video.mp4`. |
| No captions | `faster-whisper` missing (`doctor`), or `--no-captions` left on in settings. First run downloads the model. |
| Captions in the wrong language | It translates non-English speech to English automatically; for other behaviour pick `whisper_model` `base` or bigger. |
| Download fails | YouTube bot check → cookies (see SETUP §5); check `yt-dlp` is current: `python -m pip install -U yt-dlp`. |
| Hook is just the title | Ollama is not running; that is the built-in fallback. |
| Panel port busy | Another copy is open. Close the other window, or `python reelhound.py panel --port 8899`. |
| Everything else | [docs/TROUBLESHOOTING.md](TROUBLESHOOTING.md). |
