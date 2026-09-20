@echo off
setlocal enableextensions
REM ============================================================
REM  ApexInvest - start the backend (the "engine")
REM  Double-click. Leave the window OPEN while you use the app.
REM ============================================================
cd /d "%~dp0apexinvest_backend"

REM ============================================================
REM  OPTIONAL: full EGX coverage (EODHD). Paste key, remove REM.
REM ============================================================
REM set EODHD_API_KEY=PASTE_YOUR_KEY_HERE
REM set EODHD_EGX_SUFFIX=EGX

REM ---- If auto-detect fails, paste your python.exe FILE path here (remove REM):
REM set "PYTHON_HOME=C:\full\path\to\python.exe"

echo.
echo Finding Python...
set "PYEXE="

REM 0) explicit override
if defined PYTHON_HOME if exist "%PYTHON_HOME%" set PYEXE="%PYTHON_HOME%"

REM 1) the 'py' launcher (this is what Python 3.14 / Install Manager provides)
if not defined PYEXE ( py -3 -c "import sys" >nul 2>&1 && set "PYEXE=py -3" )
if not defined PYEXE ( py -c "import sys" >nul 2>&1 && set "PYEXE=py" )

REM 2) python / python3 on PATH (real interpreter, not the Store stub)
if not defined PYEXE ( python -c "import sys" >nul 2>&1 && set "PYEXE=python" )
if not defined PYEXE ( python3 -c "import sys" >nul 2>&1 && set "PYEXE=python3" )

REM 3) scan the usual install locations (3.14 down to 3.11)
if not defined PYEXE ( for %%P in (
  "%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
  "%LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe"
  "%LOCALAPPDATA%\Python\pythoncore-3.13-64\python.exe"
  "%ProgramFiles%\Python314\python.exe"
  "%ProgramFiles%\Python313\python.exe"
  "%ProgramFiles%\Python312\python.exe"
  "C:\Python314\python.exe"
  "C:\Python313\python.exe"
  "C:\Python312\python.exe"
) do ( if not defined PYEXE if exist "%%~P" set PYEXE="%%~P" ) )

if not defined PYEXE (
  echo.
  echo   Could not locate a real Python interpreter automatically.
  echo   Open Command Prompt and run:   py --version
  echo   If that prints a version, tell me; otherwise install Python from
  echo   https://www.python.org/downloads/ and TICK "Add Python to PATH".
  echo   Or paste your python.exe path into the PYTHON_HOME line near the top of this file.
  echo.
  pause
  exit /b 1
)

echo Using interpreter: %PYEXE%
%PYEXE% --version

echo.
echo Installing packages (first run only)...
%PYEXE% -m pip install --upgrade pip >nul 2>&1
%PYEXE% -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo   Package install failed - check your internet connection, then try again.
  echo.
  pause
  exit /b 1
)

echo.
echo Starting ApexInvest backend at http://localhost:8000
echo Leave this window OPEN. Open the app (Open ApexInvest) or refresh your browser.
echo (Ctrl+C or close this window to stop.)
echo.
%PYEXE% -m uvicorn apexinvest.api.main:app --reload

pause
