@echo off
title ReelHound Auto-Clip
cd /d "%~dp0"
if "%~1"=="" (
  echo  Drag one of YOUR OWN videos onto auto_clip.bat.
  echo  To clip a folder of videos instead, run:  python reelhound.py batch "C:\path\to\videos"
  pause
  exit /b
)
echo  What should it make?
echo    1 = the best moments (up to 3 clips)
echo    2 = the whole video (one clip, up to 90 s)
echo    3 = the whole video split into parts of about a minute
echo    4 = just the first 90 s
set /p MODE=" Pick 1-4 (Enter = 1): "
set "WHOLE="
if "%MODE%"=="2" set "WHOLE=--whole"
if "%MODE%"=="3" set "WHOLE=--whole parts"
if "%MODE%"=="4" set "WHOLE=--whole cap"
set /p HOOK=" Hook text (Enter = make one from the file name): "
python autoclip.py "%~1" --own --hook "%HOOK%" %WHOLE%
explorer "%~dp0..\media\edits"
pause
