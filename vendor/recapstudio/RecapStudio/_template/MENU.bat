@echo off
setlocal
cd /d "%~dp0"
title Recap Studio
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
set "MODULE=movie_recap"
if defined PY for /f "delims=" %%m in ('%PY% recap.py module') do set "MODULE=%%m"
set "RECAP=0"
if "%MODULE%"=="movie_recap" set "RECAP=1"
if "%MODULE%"=="show_recap" set "RECAP=1"
:menu
cls
echo ==============================================
echo   RECAP STUDIO      [%MODULE%]
echo ==============================================
echo.
if "%RECAP%"=="1" echo   1  Extract subtitles from video
if "%RECAP%"=="0" echo   13 Collect footage            (guided: paste links / drag files)
if "%RECAP%"=="0" echo   12 Index footage              (contact sheets for every clip)
echo   2  Make contact sheets        (segments marked need_visual)
echo.
echo   15 Export narration sheet     (review / edit text + tags in Excel)
echo   16 Import narration edits
echo   14 Preview voice              (first 3 segments, before spending credits)
echo   3  Generate voice-over        (only new / edited segments are re-voiced)
echo.
echo   4  Build Premiere XML         (also writes .srt, chapters, shot list)
echo   19 Build VideoPad project     (.vpj - same timeline for VideoPad)
echo   20 VideoPad project, simple   (fallback: picture + voice only)
if "%RECAP%"=="1" echo   5  Build FULL VIDEO           (one finished .mp4)
echo   6  Build subtitles only       (.srt for Premiere)
if "%RECAP%"=="1" echo   7  Build TikTok videos        (also writes .srt per part)
echo.
echo   8  Change voice / engine, then generate
echo   9  Redo ALL audio from scratch
echo   10 Status check               (also updates STATE.md)
echo   11 Open this folder
echo   17 Project settings           (module, target length, voice mode)
echo   18 Demo / test media          (use in a FRESH project)
echo   0  Exit
echo.
set "C="
set /p "C=Pick a number: "
if "%C%"=="1" call "%~dp0_run.bat" subs
if "%C%"=="2" call "%~dp0_run.bat" sheets
if "%C%"=="3" call "%~dp0_run.bat" tts
if "%C%"=="4" call "%~dp0_run.bat" premiere
if "%C%"=="5" call "%~dp0_run.bat" video
if "%C%"=="6" call "%~dp0_run.bat" srt
if "%C%"=="7" call "%~dp0_run.bat" tiktok
if "%C%"=="8" call "%~dp0_run.bat" tts --pick
if "%C%"=="9" call "%~dp0_run.bat" tts --force
if "%C%"=="10" call "%~dp0_run.bat" check
if "%C%"=="11" start "" "%~dp0"
if "%C%"=="12" call "%~dp0_run.bat" index
if "%C%"=="13" call "%~dp0_run.bat" collect
if "%C%"=="14" call "%~dp0_run.bat" tts --preview
if "%C%"=="15" call "%~dp0_run.bat" review
if "%C%"=="16" call "%~dp0_run.bat" review --import
if "%C%"=="17" call "%~dp0_run.bat" init
if "%C%"=="18" call "%~dp0_run.bat" demo
if "%C%"=="19" call "%~dp0_run.bat" videopad
if "%C%"=="20" call "%~dp0_run.bat" videopad --simple
if "%C%"=="0" exit /b
goto menu
