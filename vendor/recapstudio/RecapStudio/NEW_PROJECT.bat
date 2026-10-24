@echo off
setlocal
cd /d "%~dp0"
title Recap Studio - New Project

if not exist "%~dp0_template\recap.py" goto notemplate

rem Dragging a video onto this file uses its name as the project name.
set "VIDEO=%~1"
set "NAME=%~n1"
if defined NAME goto havename

echo.
set /p "NAME=Project name (e.g. Solo Leveling S01E05): "
if not defined NAME goto noname

:havename
set "NAME=%NAME:"=%"
set "DEST=%~dp0Projects\%NAME%"

if exist "%DEST%\" goto exists

mkdir "%DEST%"
xcopy "%~dp0_template\*" "%DEST%\" /E /I /Q /Y >nul

if defined VIDEO (
    echo Moving video into the project...
    move "%VIDEO%" "%DEST%\" >nul
)

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto skipinit
pushd "%DEST%"
%PY% recap.py init
popd
:skipinit
echo.
echo [OK] Created: Projects\%NAME%
echo      Opening it now - start with MENU.bat
start "" "%DEST%"
timeout /t 3 >nul
exit /b 0

:exists
echo.
echo [!] "%NAME%" already exists - opening it instead.
start "" "%DEST%"
pause
exit /b 0

:noname
echo No name entered.
pause
exit /b 1

:notemplate
echo [ERROR] The _template folder is missing. Re-extract Recap Studio.
pause
exit /b 1
