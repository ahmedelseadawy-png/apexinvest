@echo off
REM ================================================================
REM  Double-click this ONCE to put an "ApexInvest" icon on your Desktop.
REM  The icon starts the app (engine + browser) with a single click.
REM ================================================================
setlocal
set "PROJ=%~dp0"
set "TARGET=%~dp0Run ApexInvest.bat"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$W=New-Object -ComObject WScript.Shell; $lnk=Join-Path $W.SpecialFolders('Desktop') 'ApexInvest.lnk'; $s=$W.CreateShortcut($lnk); $s.TargetPath=$env:TARGET; $s.WorkingDirectory=$env:PROJ; $s.IconLocation='%SystemRoot%\System32\SHELL32.dll,13'; $s.Description='Launch ApexInvest'; $s.Save()"
if errorlevel 1 (
  echo.
  echo Could not create the shortcut automatically.
  echo You can right-click "Run ApexInvest.bat" -^> Send to -^> Desktop ^(create shortcut^) instead.
) else (
  echo.
  echo Done!  An "ApexInvest" shortcut is now on your Desktop.
  echo Double-click it any time to start the app.
)
echo.
pause
