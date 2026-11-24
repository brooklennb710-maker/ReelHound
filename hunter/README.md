# hunter/

Finds new videos in your niche, scores them, downloads the ones you may use, and drafts the permission
message for everyone else.

```
python reelhound.py hunt              one scan
python reelhound.py hunt --loop       keep scanning (every `every_minutes`)
python reelhound.py hunt --loop --open
```

Or double-click `start_hunter.bat`.

## What a scan does

1. **Sources** — YouTube keyword search (Data API key), every channel in `creators.csv` via RSS (no key
   needed), Reddit (`subreddits`, app-only OAuth), Instagram hashtags (`instagram.hashtags`, Graph API).
2. **Score 0–100** — freshness, views/likes per hour, engagement, plus `score_words` found in the title.
   `block_words` zero a title, `must_include` limits the whole scan, `priority_words` add 5.
   Anything under `min_score` is dropped.
3. **Permission** — looked up in `creators.csv`.
   - `own` / `yes` / `official` → downloaded to `media/raw` with a `.source.json` note (permission, creator,
     credit) that the clip maker reads later.
   - anything else → saved to the finds page with a ready-to-send message.
4. **Finds page** — `finds.html`, served at `http://localhost:8765` while `--loop` runs. "Yes, they said ok"
   adds the creator to `creators.csv` and queues their downloads.

## Files

| File | What it is |
|---|---|
| `config.json` | Your settings and keys (git-ignored). Start from `config.example.json`. |
| `creators.csv` | The permission ledger (git-ignored). Start from `creators.sample.csv`. |
| `finds.csv` | Results, one row per find (git-ignored). |
| `finds.html` | The finds page (generated, git-ignored). |
| `seen.json` | IDs already handled (git-ignored). |
| `youtube_cookies.txt` | Optional sign-in cookies for yt-dlp (git-ignored, never share). |

## Settings worth knowing

- `keywords`, `keywords_per_run`, `lookback_hours`, `min_score`, `max_downloads_per_run`, `max_video_minutes`
- `every_minutes`, `sources`, `page_port`
- scoring: `score_words`, `block_words`, `must_include`, `priority_words`
- downloads: `cookies_file`, `cookies_from_browser`
- auto-clip after download: `auto_clip`, `clips_per_video`, `clip_seconds`, `clip_preset`

Full table: [../docs/USER-GUIDE.md](../docs/USER-GUIDE.md#hunterconfigjson--what-to-look-for).
Keys and cookies: [../docs/SETUP.md](../docs/SETUP.md#5-optional-search-sources-and-their-keys).
