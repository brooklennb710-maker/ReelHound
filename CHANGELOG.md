# Changelog

All notable changes to ReelHound are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-11-23

First public release, by BridgesTech.

### Added
- **`reelhound.py`** - one command for every part of the workflow (`init`, `doctor`,
  `panel`, `hunt`, `clip`, `auto`, `batch`, `pack`, `review`, `inbox`, `selftest`).
- **`brand.json`** - one small file for your handle, channel name, niche, watermark,
  time zone, caption hashtags and posting destinations. A fresh clone runs on the
  defaults without editing anything.
- **`doctor.py`** - checks Python, FFmpeg, packages, Ollama models, config files,
  folders and ports, and prints the exact fix for anything missing.
- **`setup_wizard.py`** - first-run questions that write `brand.json` and
  `hunter/config.json` and copy the sample data files.
- **`batch_clip.py`** - clip a whole folder of videos, resumable, with a log.
- **`pack.py`** - publish pack: clips + captions + `.srt` files + `manifest.csv`
  in a folder and a zip, ready for any scheduler.
- **`selftest.py`** - renders a real 1080x1920 test clip to prove the install works.
- **`setup.bat`** - one-click installer (Python packages, FFmpeg, sample files, questions).
- Caption `.srt` sidecars next to every clip that had speech.
- `--watermark` / `--no-watermark` flags for the clip maker.
- Configurable posting-day start time and any time zone in the schedule.
- Configurable destinations (Instagram Reels, Facebook Reels, TikTok, YouTube Shorts).
- Configurable scoring: `score_words`, `block_words`, `must_include`, `priority_words`.
- Configurable AI models: `hook_model` and `review_model` in `hunter/config.json`.
- Documentation: `docs/SETUP.md`, `docs/USER-GUIDE.md`, `docs/PLAYBOOK.md`,
  `docs/TROUBLESHOOTING.md`.

### Changed
- The tool is now niche-agnostic: nothing is hard-coded to one game, channel or
  platform. Search terms, scoring words and prompts all come from config.
- The permission message, hooks, review prompt and panel text use your channel
  name and niche from `brand.json`.
- The schedule works in your own time zone, with a configurable posting-day start.
- Watermark defaults to off until you set one in `brand.json`.

### Fixed
- A missing or half-written `hunter/config.json` no longer takes the panel down.
- `slot_utc` handles any time zone and DST fall-back.
