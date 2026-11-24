@echo off
rem Scores every clip in media\edits with a local Ollama vision model. Free, runs on this PC.
rem Only new or changed clips are scored; results go to reviewer\results.csv and reviewer\top.html.
rem It shares the graphics card politely: it will not start while another GPU program (e.g. ComfyUI) is running
rem or while too little graphics memory is free (waits up to 15 minutes), steps aside if one
rem starts mid-run, and unloads the model from the graphics card as soon as it finishes.
rem Add --cpu to run on the processor only (no graphics memory at all, several times slower).
rem The model comes from "review_model" in hunter\config.json (default llava:7b).
cd /d "%~dp0reviewer"
python review_edits.py --top 12 --wait 15 %*
if exist top.html start "" top.html
pause
