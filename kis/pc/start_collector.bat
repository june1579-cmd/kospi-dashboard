@echo off
setlocal
cd /d "%~dp0"
title KIS minute-bar collector setup
echo ==========================================================
echo   KIS minute-bar collector - setup and start
echo   Folder: %~dp0
echo ==========================================================
if not exist state mkdir state
if not exist logs mkdir logs

rem ---- 0. .env must have keys ----
if not exist ".env" (
  echo [ERROR] .env file not found in this folder.
  pause
  exit /b 1
)

rem ---- 1. find Python (install if missing) ----
set "PY="
if exist state\pyexe.txt del state\pyexe.txt
py -3 -c "import sys;open(r'state\pyexe.txt','w').write(sys.executable)" >nul 2>nul
if not exist state\pyexe.txt python -c "import sys;open(r'state\pyexe.txt','w').write(sys.executable)" >nul 2>nul
if exist state\pyexe.txt set /p PY=<state\pyexe.txt
if not defined PY (
  echo [1/5] Python not found - installing Python 3.12 with winget ...
  winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
  if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
)
if not defined PY (
  echo [ERROR] Could not install Python automatically.
  echo         Install Python 3.12 from https://www.python.org/downloads/ and run this file again.
  pause
  exit /b 1
)
echo [1/5] Python: %PY%

rem ---- 2. private environment + packages ----
if not exist ".venv\Scripts\python.exe" (
  echo [2/5] Creating environment ...
  "%PY%" -m venv .venv
)
echo [2/5] Installing packages (requests, pandas, pyarrow) ...
".venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check --upgrade pip
".venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check requests pandas pyarrow
if errorlevel 1 (
  echo [ERROR] Package install failed. Check internet and run again.
  pause
  exit /b 1
)

rem ---- 3. check settings and connection (sends a KakaoTalk test) ----
echo [3/5] Checking KIS connection and KakaoTalk alert ...
".venv\Scripts\python.exe" collector.py --check
if errorlevel 1 (
  echo [ERROR] Check failed. Open .env and fill KIS_REAL_APP_KEY / KIS_REAL_APP_SECRET / GITHUB_TOKEN.
  pause
  exit /b 1
)

rem ---- 4. auto restart every 10 minutes (only starts if not already running) ----
if exist state\STOP del state\STOP
echo [4/5] Registering auto restart (Task Scheduler: KIS_Minute_Collector, every 10 min) ...
schtasks /Create /TN "KIS_Minute_Collector" /TR "wscript.exe \"%~dp0run_hidden.vbs\"" /SC MINUTE /MO 10 /F >nul
if errorlevel 1 echo [WARN] Task Scheduler registration failed - collector will still run now.

rem ---- 5. start now in background (low priority, no window) ----
echo [5/5] Starting collector in background ...
wscript.exe "%~dp0run_hidden.vbs"
echo.
echo ==========================================================
echo   Started. You can close this window.
echo   - Progress: state\status.json  /  Log: logs\collector.log
echo   - KakaoTalk report every day 06:50
echo   - To stop: double-click stop_collector.bat
echo   - Keep the PC on and turn off sleep mode.
echo ==========================================================
pause
