# reviewer/

A local pre-filter for `media/edits`: it looks at every clip so you only have to watch the good ones.

```
python reelhound.py review
```

or double-click `Review Clips (local AI).bat`. Results: `reviewer/results.csv` and a ranked
`reviewer/top.html` that plays each clip.

## What it does per clip

1. Pulls five frames into a contact sheet (one image per clip).
2. Runs ffmpeg checks: length, 9:16 framing, audio present, loudness, black first frame.
3. Asks a local Ollama vision model to score **hook** (first frame), **payoff**, **standalone** and
   **phone readability** from 1–10, name what happens, list visible problems, and give a verdict
   (`post` / `maybe` / `skip`).
4. Combines both into a 0–100 score, ranks the clips, and hides duplicates from the same moment.

It is a shortlist, **not a judgement**: it cannot hear audio and cannot see motion between the frames.
Every clip you keep is watched by you.

## Graphics card etiquette

- Refuses to start while another GPU program from `GPU_RIVALS` is running (ComfyUI on port 8188 by default).
- Waits for free graphics memory (`--wait` minutes), steps aside if a rival appears mid-run.
- Unloads the model from the GPU when it finishes.
- `--cpu` runs entirely on the processor: slower, no graphics memory at all.
- `--stop-at HH:MM` stops cleanly before another scheduled GPU job.

## Options

| Flag | Meaning |
|---|---|
| `--model` | Ollama vision model (default `gemma4:12b`, or `review_model` in `hunter/config.json`). |
| `--limit N` | Score at most N new clips. |
| `--rescore` | Ignore the cache. |
| `--top N` | How many clips the HTML report ranks (default 12). |
| `--wait MIN` | Minutes to wait for the graphics card. |
| `--stop-at HH:MM` | Stop by this local time. |
| `--cpu` / `--cpu-if-busy` | Processor only / if the GPU stays busy. |

Results are cached by file, size, mtime and model, so re-running only scores new or changed clips.
Bump `VERSION` in `review_edits.py` to invalidate everything after a prompt change.

Generated files (`cache.json`, `results.csv`, `top.html`, `sheets/`) are git-ignored.
