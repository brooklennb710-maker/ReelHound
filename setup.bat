@echo off
setlocal
title ReelHound by BridgesTech - Setup
cd /d "%~dp0"
echo.
echo ============================================================
echo   ReelHound by BridgesTech - one-click setup
echo ============================================================
echo  This installs Python packages and FFmpeg if they are missing,
echo  copies the example settings, and asks a few questions.
echo.

where python >nul 2>&1
if errorlevel 1 (
  echo  Python was not found.
  where winget >nul 2>&1
  if errorlevel 1 (
    echo  Install Python 3.10 or newer from https://www.python.org/downloads/
    echo  Tick "Add Python to PATH", then run setup.bat again.
    pause
    exit /b 1
  )
  echo  Installing Python 3.12 with winget...
  winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
  echo.
  echo  Python installed. Close this window, open a new one, and run setup.bat again
  echo  so Windows picks up the new PATH.
  pause
  exit /b 1
)

python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"
if errorlevel 1 (
  echo  ReelHound needs Python 3.10 or newer. Update it from python.org, then run setup.bat again.
  pause
  exit /b 1
)

echo  Installing Python packages (requests, yt-dlp, faster-whisper, numpy)...
python -m pip install --upgrade pip >nul 2>&1
python -m pip install requests yt-dlp faster-whisper numpy
if errorlevel 1 echo  [warn] Some packages did not install. Run setup.bat again, or see docs\SETUP.md.

where ffmpeg >nul 2>&1
if errorlevel 1 (
  where winget >nul 2>&1
  if errorlevel 1 (
    echo  [warn] FFmpeg is missing and winget is not available.
    echo         Install it from https://ffmpeg.org/download.html (put ffmpeg.exe and ffprobe.exe on PATH).
  ) else (
    echo  Installing FFmpeg...
    winget install -e --id Gyan.FFmpeg --accept-package-agreements --accept-source-agreements
    echo  Note: if FFmpeg is still not found, close this window and open a new one.
  )
) else (
  echo  FFmpeg is already installed.
)

echo.
echo  Copying example settings (existing files are left alone)...
if not exist "hunter\config.json" copy "hunter\config.example.json" "hunter\config.json" >nul
if not exist "hunter\creators.csv" copy "hunter\creators.sample.csv" "hunter\creators.csv" >nul
if not exist "hunter\finds.csv" copy "hunter\finds.sample.csv" "hunter\finds.csv" >nul
if not exist "scoreboard.csv" copy "scoreboard.sample.csv" "scoreboard.csv" >nul
if not exist "control-panel\schedule.json" copy "control-panel\schedule.example.json" "control-panel\schedule.json" >nul

echo.
echo  First-run questions (press Enter to keep the default)...
python setup_wizard.py
if errorlevel 1 echo  [warn] The setup questions did not finish. You can run: python reelhound.py init

echo.
python doctor.py

echo.
echo ============================================================
echo  Done. Double-click "Start ReelHound.bat" to open the panel.
echo  Docs: docs\SETUP.md   docs\USER-GUIDE.md   docs\PLAYBOOK.md
echo ============================================================
pause
