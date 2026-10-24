@echo off
cd /d "%~dp0"
title Recap Studio - One-time setup
echo.
echo [1/3] Checking Python...
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto nopython
%PY% --version

echo.
echo [2/3] Installing Python packages (requests, edge-tts, yt-dlp)...
%PY% -m pip install --upgrade requests edge-tts yt-dlp
if errorlevel 1 goto pipfail

echo.
echo [3/3] Checking FFmpeg...
where ffmpeg >nul 2>nul
if errorlevel 1 goto noffmpeg
where ffprobe >nul 2>nul
if errorlevel 1 goto noffmpeg
echo FFmpeg OK.
echo.
echo ===== Setup complete. Double-click NEW_PROJECT.bat to start. =====
goto end

:nopython
echo Python not found - installing with winget...
winget install -e --id Python.Python.3.12
echo.
echo Close this window and run SETUP.bat again once the install finishes.
goto end

:pipfail
echo [!] pip failed. Check your internet connection and try again.
goto end

:noffmpeg
echo FFmpeg not found - installing with winget...
winget install -e --id Gyan.FFmpeg
echo.
echo Close this window and run SETUP.bat again so FFmpeg is on PATH.

:end
echo.
pause
