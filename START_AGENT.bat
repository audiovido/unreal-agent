@echo off
cd /d "%~dp0"
title Unreal Agent Auto Reload

:restart
echo.
echo [WATCHDOG] Starting Unreal Agent...
".venv\Scripts\python.exe" run_agent.py

echo.
echo [WATCHDOG] Backend exited. Restarting in 2 seconds...
timeout /t 2 /nobreak >nul
goto restart
