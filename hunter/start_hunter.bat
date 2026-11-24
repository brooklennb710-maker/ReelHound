@echo off
title ReelHound Hunter (leave this window open)
cd /d "%~dp0"
echo  Hunting for new videos every 45 minutes. Close this window to stop.
echo  Your finds page opens in your browser: http://localhost:8765
echo  (the Yes buttons on it work while this window stays open)
echo.
python hunter.py --loop --open
pause
