@echo off
cd /d "%~dp0"
title Unreal Agent Production

echo [START] Checking existing backend...
".venv\Scripts\python.exe" -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/status', timeout=3); print('Backend already healthy; reusing it.')" 2>nul
if not errorlevel 1 goto openui

echo [START] Starting one production backend...
start "Unreal Agent Backend" /b ".venv\Scripts\python.exe" run_agent.py

:wait
".venv\Scripts\python.exe" -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/status', timeout=2)" 2>nul
if errorlevel 1 (
  timeout /t 1 /nobreak >nul
  goto wait
)

:openui
start "" http://127.0.0.1:8765/
exit /b 0
