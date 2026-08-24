@echo off
cd /d "%~dp0"
title Unreal Agent Auto Reload
".venv\Scripts\python.exe" run_agent.py
pause
