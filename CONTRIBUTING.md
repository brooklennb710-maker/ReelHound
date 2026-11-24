# Contributing to ReelHound

Thanks for helping. ReelHound is a small, deliberately plain Python tool: standard library first,
one dependency only where it earns its place, and files on disk instead of a database.
BUG reports, new source integrations, better clip heuristics and documentation fixes are all welcome.

## Ground rules

- **Never commit secrets or media.** `hunter/config.json`, `inbox/config.json`, `brand.json`, cookies and
  everything under `media/` are git-ignored. Check `git status` before you push.
- **Keep the permission gate.** No change may let the tool clip third-party footage without a recorded
  permission and a credit. That is the reason the project can exist.
- **Do not add telemetry, analytics, cloud accounts or "phone home" behaviour.** The tool is local by design.
- **Do not add an API key requirement to a path that has a working keyless alternative.**

## Getting a development copy

```
git clone https://github.com/BridgesTech/reelhound.git
cd reelhound
python setup.bat            REM or: pip install requests yt-dlp faster-whisper numpy
python reelhound.py doctor
python reelhound.py selftest
```

`selftest` renders a real clip with FFmpeg and is the fastest way to know your environment works.

## Where things live

| Path | Responsibility |
|---|---|
| `reelhound.py` | Command dispatch only. Keep it thin. |
| `brand.py`, `brand.json` | Identity and output defaults, read by every module. |
| `hunter/hunter.py` | Sources, scoring, downloads, `creators.csv`, the finds page. |
| `clipmaker/clipmaker.py` | One render: framing, ASS captions, hook, credit, sidecars. |
| `clipmaker/autoclip.py` | Moment picking, whole-video/parts modes, the panel's clip loop. |
| `clipmaker/hookwriter.py` | Ollama hook/caption writer with a rule-based fallback. |
| `clipmaker/reclip.py`, `wholejob.py`, `regen_hooks.py` | Re-cut, whole-video repost, re-render hooks. |
| `control-panel/pipeline.py` | Panel back end: settings, creators, review, queue, workers. |
| `control-panel/panel.py` | HTTP server, token auth, asset serving. |
| `control-panel/app.js`, `index.html`, `app.css` | The UI. No build step, no framework. |
| `reviewer/review_edits.py` | Contact sheets, GPU politeness, vision scoring. |
| `inbox/inbox.py`, `page.html` | Phone inbox server and page. |
| `doctor.py`, `selftest.py`, `pack.py`, `batch_clip.py`, `setup_wizard.py` | Tooling around the edges. |

## Style

- Python 3.10+, standard library first. Keep new dependencies rare and explained in the PR.
- Functions say what they do; comments explain *why*, especially around FFmpeg filters, DST and
  platform quirks. Match the surrounding style: short functions, plain names, no framework.
- Console output is ASCII (`[clipmaker] ...`) so Windows consoles never see mojibake.
- The UI is vanilla JS with no build step. Keep it that way.
- Any user-facing text must come from `brand.json` or config where it describes *who* the user is
  (handle, channel, niche, destinations, time zone). Nothing may be hard-coded to one channel or fandom.

## Tests

There is no unit-test suite yet (a good first contribution). Before a PR:

```
python -m py_compile **/*.py            REM or compile what you touched
python reelhound.py doctor
python reelhound.py selftest
python reelhound.py clip <a short video> --permission own --no-captions --preset clean
python reelhound.py pack --area edits
```

If you touch the panel, open `python reelhound.py panel`, click through every page and check the
browser console for errors. If you touch the inbox, open it at `http://127.0.0.1:8876`.

## Pull requests

1. One topic per PR. Say what changed and why, and mention anything a reviewer should look at closely.
2. Update the docs you invalidate (`README.md`, `docs/*.md`) and add a `CHANGELOG.md` entry under
   **Unreleased**.
3. Screenshots are welcome for panel changes.
4. New behaviour needs a sane default that keeps a fresh clone working with no config at all.

## Reporting a bug

Include: what you ran (exact command), what you expected, what happened, `python reelhound.py doctor`
output, and your Windows/Python/FFmpeg versions. Remove handles, keys and file paths you do not want public.

## Licence

Contributions are accepted under the MIT licence (see `LICENSE`).
