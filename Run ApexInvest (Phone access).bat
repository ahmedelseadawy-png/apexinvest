@echo off
title ApexInvest - phone access
REM ============================================================
REM  Same app as "Run ApexInvest.bat", but ALSO reachable from your phone
REM  when the phone is on the SAME Wi-Fi as this PC.
REM  On the phone open:   http://<this PC's IPv4 address>:8000/m/
REM  (Windows may ask to allow Python through the firewall - choose "Private networks".)
REM  Tip: add a personal access key so only you can use it - remove REM and edit:
REM      set APEX_ACCESS_KEYS=me:CHOOSE-A-LONG-SECRET
REM ============================================================
REM set APEX_ACCESS_KEYS=me:CHOOSE-A-LONG-SECRET
set APEX_UVICORN_ARGS=--host 0.0.0.0 --port 8000
echo.
echo Your phone address (use the IPv4 line that matches your Wi-Fi):
ipconfig | findstr /c:"IPv4"
echo   -> open  http://THAT-ADDRESS:8000/m/  on the phone
echo.
call "%~dp0start_backend.bat"
