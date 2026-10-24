@echo off
cd /d "%~dp0"
title Recap Studio - UI
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
    echo Python not found. Run SETUP.bat first.
    pause
    exit /b 1
)
echo Starting Recap Studio... your browser should open automatically.
%PY% studio.py
pause
