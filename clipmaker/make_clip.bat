@echo off
title ReelHound Clip Maker
cd /d "%~dp0"
set "VIDEO=%~1"
if "%VIDEO%"=="" (
  echo.
  echo  Drag a video file onto make_clip.bat to start.
  echo.
  pause
  exit /b
)
echo.
echo  Video: %VIDEO%
echo.
echo  Where is this footage from?
echo    1 = my own footage
echo    2 = the official source (brand, publisher, studio)
echo    3 = a creator who said yes
set /p SRC=" Pick 1, 2 or 3: "
set "PERM="
if "%SRC%"=="1" set "PERM=own"
if "%SRC%"=="2" set "PERM=official"
if "%SRC%"=="3" set "PERM=creator-yes"
if "%PERM%"=="" (
  echo  Only footage you own, official media, or creators who said yes. Stopping.
  pause
  exit /b
)
set "CREDIT="
if "%PERM%"=="official" set /p CREDIT=" Official handle to credit (e.g. @brand): "
if "%PERM%"=="creator-yes" set /p CREDIT=" Creator handle to credit (e.g. @name): "
set "START="
set "END="
set "WHOLE="
set /p START=" Start time (e.g. 1:05, Enter = 0, W = the whole video): "
if /i "%START%"=="W" (
  set "START="
  set "WHOLE=--whole"
) else (
  set /p END=" End time (e.g. 1:30, Enter = 45 seconds later): "
)
set /p HOOK=" Hook text for the first seconds (Enter = none): "
echo  Style: 1 = Viral (big highlighted words)   2 = Clean (plain captions)   3 = News (headline bar)
set /p STY=" Pick 1, 2 or 3 (Enter = 1): "
set "PRESET=viral"
if "%STY%"=="2" set "PRESET=clean"
if "%STY%"=="3" set "PRESET=news"
set "TITLE="
if "%PRESET%"=="news" set /p TITLE=" Headline for the top bar: "

set "ARGS=--permission %PERM% --preset %PRESET% %WHOLE%"
if not "%START%"=="" set "ARGS=%ARGS% --start %START%"
if not "%END%"=="" set "ARGS=%ARGS% --end %END%"
python clipmaker.py "%VIDEO%" %ARGS% --hook "%HOOK%" --credit "%CREDIT%" --title "%TITLE%"
echo.
echo  Your clip is in media\edits (with a caption draft .txt next to it).
explorer "%~dp0..\media\edits"
pause
