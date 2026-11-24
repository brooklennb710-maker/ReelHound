# ReelHound — troubleshooting

Start with:

```
python reelhound.py doctor
```

Every `FAIL` line comes with a `fix:` line. If the doctor is clean and something still misbehaves,
find the symptom below.

---

## Install and startup

### Double-clicking `setup.bat` flashes and closes
Open **Command Prompt**, `cd` into the folder and run `setup.bat` there. You will see the real message.
The usual cause is `winget` missing (Windows Store/App Installer not up to date) or no internet.

### `'python' is not recognized`
Python installed but not on `PATH`. Options:
- Re-run the Python installer → *Modify* → tick **Add Python to PATH**.
- Or use the launcher: `py -3 reelhound.py doctor`.
- `setup.bat` installs Python 3.12 if it cannot find any, but it cannot refresh `PATH` for the window
  that installed it — close that window and open a new one.

### `FFmpeg or FFprobe was not found`
`winget install Gyan.FFmpeg`, then **open a new terminal**. Windows does not pick up the new `PATH` in
windows that were already open. The panel and the clip maker also look in
`%LOCALAPPDATA%\Microsoft\WinGet\Links` automatically.

### `pip` fails with an SSL error or a proxy error
Corporate proxy/VPN. Try `python -m pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org requests yt-dlp faster-whisper numpy`,
or install while off the VPN.

### The panel opens but says "Refresh the panel and try again"
The panel mints a new token every run, and an old tab still holds the previous one. Reload the page
(`Ctrl+R`). If it keeps happening, another copy of the panel is on the port: close its window.

### "Could not open http://127.0.0.1:8875"
Port in use. `python reelhound.py panel --port 8899`, then use that address. Or close the old window.

---

## Hunter and downloads

### The hunter finds nothing
- No **keywords** and no channels: add search terms (`hunter/config.json` → `keywords`) or creators.
- `min_score` too high: lower it to 25–30 for a first run.
- `lookback_hours` too small for a quiet niche.
- YouTube key missing: keyword search is skipped, but channels in `creators.csv` still work.
- Reddit skipped: needs `reddit.client_id` + `client_secret`.

### The finds page has no Yes buttons
Those buttons need the hunter's little web server, which only runs with `--loop`
(`hunter/start_hunter.bat`). If you opened `finds.html` by double-clicking, the page shows a red note
instead. Run `hunter\start_hunter.bat` and use the page it opens.

### "Sign in to confirm you're not a bot"
YouTube's anti-bot check. In order of preference:
1. `python -m pip install -U yt-dlp yt-dlp-ejs` (the challenge solver).
2. Export cookies to `hunter/youtube_cookies.txt`, or set `cookies_from_browser` (see SETUP §5).
3. Slow the hunter down (`every_minutes` up) — fewer requests means fewer challenges.

Never commit or share a cookies file: it is a live login.

### Downloads fail on Instagram
Instagram needs a sign-in: set `cookies_from_browser` (e.g. `"chrome"`) in `hunter/config.json` or
`inbox/config.json`. Instagram finds are never auto-downloaded by the hunter — by design, they are
queued for you to handle.

### Everything is "skipped: creator said no" or "ask permission"
That is the permission gate working. Add the creator to `creators.csv` with `own`/`yes`/`official`
and re-run, or use the **Yes, they said ok** button.

---

## Clipping

### `Clip is too short (0.0s)` or a black result
The range does not exist in that file. Check the duration:

```
ffprobe -v error -show_entries format=duration -of csv=p=0 "video.mp4"
```

### The clip is 9:16 but the source is tiny in the middle
The source is wider or taller than expected. Use `--fit` to show the whole frame, or pick a source that
already fills the frame. Tall sources (phone video) are automatically fitted instead of zoomed.

### Captions are missing
- `python -m pip install faster-whisper` (the doctor will say so).
- Captions turned off in settings (`captions: false`) or `--no-captions`.
- No speech in the range — Whisper finds nothing.
- First run downloads the model; give it a few minutes.

### Captions are wrong words
Use a bigger model: `--whisper-model medium`. Smaller models struggle with accents, music and game audio.

### The AI hook equals the video title
Ollama is not running (`ollama serve`) or the model is not pulled
(`ollama pull qwen3.5:9b`). The cleaned-up title is the designed fallback.

### `guide` mode cut too much or too little
`--max-gap` controls pauses (default 2.5 s). For manual control use `--keep "10-42,50-58"`.
It never guesses a cut sentence: it warns and keeps it.

### A part is labelled `(PART 2/3)` but the order looks off
Parts are cut at the quietest point near each ideal boundary, so lengths vary. That is expected;
names include the part number.

### Rendering is slow
1080×1920 with word-level captions is real work. Tips: `--whisper-model base` for exploration,
render final versions with `small`/`medium`, close other heavy apps, and let the GPU do the Whisper part.
The panel runs one render at a time on purpose.

---

## AI review

### "The model … is not installed"
`ollama pull gemma4:12b` (or whatever `review_model` says).

### "only N GB graphics memory is free…"
The reviewer waits politely. Close other GPU apps, raise `--wait`, or run `--cpu` (slower but always works).
`GPU_RIVALS` in `reviewer/review_edits.py` lists programs it steps aside for.

### Scores look harsh or random
It sees five still frames and no audio. Use it as a shortlist, then watch. Bump `VERSION` in
`reviewer/review_edits.py` to force a re-score after changing the prompt.

---

## Schedule and queue

### "Enter posting times as HH:MM"
One `HH:MM` per line, 24-hour, e.g. `09:00`. `day_start` is also `HH:MM`.

### A clip goes to the wrong day
Anything earlier than `day_start` counts toward the previous posting day. Set `day_start` to whenever
your day really starts (default `04:00`).

### "No upcoming posting slot is available"
Every slot is taken for the next few days. Add times, raise `posts_per_day`, or delete old queue items.

### Times are off by hours
The schedule uses your system time zone unless `brand.json` sets `timezone` to an IANA name
(`America/New_York`, `Europe/London`, `Asia/Tokyo`). Windows Python without IANA data falls back to the
system zone.

---

## Phone inbox

### The phone cannot reach the PC
- Both devices on the same Tailscale tailnet?
- `tailscale serve` running? `inbox\Open Phone Inbox.bat` starts it if Tailscale is installed.
- Use the `*.ts.net` URL, not `127.0.0.1`.
- The inbox only accepts requests from the tailnet and localhost, by design.

### "The phone inbox isn't running, and it does the downloading"
The panel delegates downloads to the inbox. Start `inbox\Open Phone Inbox.bat`, or let
`Start ReelHound.bat` start it minimized.

---

## Files and data

### I lost clips after deleting them in review
They are in `control-panel/deleted/<id>/`; move them back to `media/edits`.

### Re-clip says the source is missing
The original video was deleted from `media/raw` (or `media/official`). Re-clip needs it.

### Nothing is in `media/ready` but I packed and got an empty zip
`pack` reads `media/ready` by default. Use `--area edits` for clips that are still in review.

### Can I move the folder?
Yes, as long as the whole tree moves together. Python files use paths relative to themselves, so a USB
drive works. If you keep videos elsewhere, download to that drive manually and clip by path.

---

## Still stuck?

1. Run `python reelhound.py doctor` and read the `fix:` lines.
2. Run `python reelhound.py selftest` — if that passes, the renderer is fine and the problem is input.
3. Check the window's console output: every worker logs what it is doing and why it stopped.
4. Open an issue with the output of `doctor` (remove any handle or key first) and the exact command you ran.
