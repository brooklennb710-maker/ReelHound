@echo off
setlocal
title ReelHound Phone Inbox
cd /d "%~dp0.."
set "PYTHONUTF8=1"
rem Share the inbox with your own Tailscale devices only (tailnet, not the public internet). Safe to repeat.
if exist "C:\Program Files\Tailscale\tailscale.exe" (
  "C:\Program Files\Tailscale\tailscale.exe" serve --bg --https=443 http://127.0.0.1:8876 >nul 2>&1
)
echo Phone inbox: keep this window open. Finished Reels go to media\edits.
where python >nul 2>&1
if errorlevel 1 (
  py -3 "%~dp0inbox.py"
) else (
  python "%~dp0inbox.py"
)
if errorlevel 1 pause
