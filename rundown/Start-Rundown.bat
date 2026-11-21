@echo off
cd /d "%~dp0"
title The Rundown
echo.
echo  THE RUNDOWN
echo  -----------
set "PY="
where py >nul 2>nul && set "PY=py"
if not defined PY (where python >nul 2>nul && set "PY=python")
if not defined PY goto nopython

echo  Getting ready (first time takes a minute)...
%PY% -m pip install --quiet --disable-pip-version-check -r requirements.txt

echo.
echo  The Rundown is starting. Your browser will open in a few seconds.
echo  KEEP THIS WINDOW OPEN while you use it. Close this window to stop.
echo.
start "" cmd /c "timeout /t 4 >nul & start http://localhost:8080"
%PY% server.py
echo.
echo  The Rundown stopped. If you see an error above, take a screenshot of this window.
pause
exit /b

:nopython
echo.
echo  Python is not installed yet.
echo  Your browser will open the Python download page.
echo  1. Click the yellow "Download Python" button and run the installer.
echo  2. IMPORTANT: tick the box "Add python.exe to PATH" at the bottom of the first screen.
echo  3. Click "Install Now". When it finishes, double-click Start-Rundown again.
echo.
start "" https://www.python.org/downloads/
pause
