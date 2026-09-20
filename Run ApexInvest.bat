@echo off
title ApexInvest
cd /d "%~dp0"
echo Starting ApexInvest...
echo A browser tab will open automatically in a few seconds.
echo Leave THIS window open while you use the app (it is the engine).
echo.
REM Open the app in the default browser a few seconds after the engine starts
start "" /min cmd /c "ping -n 10 127.0.0.1 >nul & explorer http://localhost:8000/"
REM Start the backend (installs packages on first run, then serves the app)
call "%~dp0start_backend.bat"
