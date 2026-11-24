# control-panel/

The local web panel. Double-click `Start ReelHound.bat`, or:

```
python reelhound.py panel
python reelhound.py panel --port 8899 --no-browser
```

It opens `http://127.0.0.1:8875`, binds to loopback only, mints a fresh random token per run, and rejects
cross-site requests. Keep the console window open while the panel is in use; `Ctrl+C` stops the workers
after the current scan or render.

## Pages

| Page | What it does |
|---|---|
| **Overview** | Hunter and Clip maker workers with live logs, today's counts, latest clip, AI picks, quick whole-video repost, file links. Workers start off. |
| **Hunter** | Scan interval, minimum score, search terms, sources, subreddits, hashtags, API keys (write-only). |
| **Creators** | `hunter/creators.csv`: add/edit permissions, see who is waiting on a reply with their draft message. |
| **Editing** | Defaults for new clips + whole-video repost (link or already-downloaded). |
| **Clip review** | Watch, search, filter, fix captions, keep/delete, re-clip. |
| **Schedule** | Posting times, posting-day start, posts per day, add ready clips to the queue, export JSON. |
| **Scoreboard** | `scoreboard.csv` totals and best post. |

## Files

| File | What it is |
|---|---|
| `panel.py` | HTTP server, token check, asset serving, range requests for video scrubbing. |
| `pipeline.py` | All the back end: settings, creators, review, re-clip, whole-video jobs, schedule, workers, AI review. |
| `index.html`, `app.js`, `app.css` | The UI (vanilla JS, no build step). Branding placeholders are filled by `panel.py`. |
| `schedule.json` | Your queue (git-ignored). Start from `schedule.example.json`. |
| `deleted/` | Clips deleted in review, kept for restore (git-ignored). |

## Design notes

- **One writer at a time.** A single lock serialises all mutations; the two workers do downloads and renders
  one at a time on purpose, so FFmpeg and the GPU are never fighting each other.
- **Files, not a database.** Everything the panel shows is a file you can open in Explorer or edit by hand.
- **Fail-soft settings.** A missing or half-written `config.json` falls back to defaults instead of taking
  the panel down.
- **Secrets stay out of the browser.** API keys and tokens are write-only; the UI only learns whether they exist.
