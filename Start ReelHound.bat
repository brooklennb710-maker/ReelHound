@echo off
setlocal
title ReelHound by BridgesTech
cd /d "%~dp0"
set "PYTHONUTF8=1"
rem Phone inbox (inbox\README.md): starts minimized, quits by itself if it is already running.
if exist "%~dp0inbox\inbox.py" start "ReelHound Phone Inbox" /min "%~dp0inbox\Open Phone Inbox.bat"
where python >nul 2>&1
if errorlevel 1 (
  py -3 "%~dp0control-panel\panel.py"
) else (
  python "%~dp0control-panel\panel.py"
)
if errorlevel 1 pause
