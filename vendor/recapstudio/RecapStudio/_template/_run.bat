@echo off
setlocal
cd /d "%~dp0"
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto nopython

%PY% recap.py %*
if errorlevel 1 goto failed
echo.
echo [DONE]
goto end

:failed
echo.
echo [!] That step stopped with an error - read the message above.
goto end

:nopython
echo [ERROR] Python not found. Run SETUP.bat in the main Recap Studio folder first.

:end
echo.
pause
