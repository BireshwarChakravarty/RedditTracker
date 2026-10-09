@echo off
title Reddit Alerts
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 -m pip install --quiet --disable-pip-version-check -r requirements.txt >nul 2>nul
  py -3 run.py
  goto end
)
where python >nul 2>nul
if %errorlevel%==0 (
  python -m pip install --quiet --disable-pip-version-check -r requirements.txt >nul 2>nul
  python run.py
  goto end
)
echo.
echo Python is not installed. Opening the download page...
echo Install it (tick "Add Python to PATH"), then double-click this file again.
start https://www.python.org/downloads/
:end
pause
