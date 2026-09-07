@echo off
rem AIVIDO V1 — stop the persistent backend (bridge/gateway untouched)
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-aivido.ps1" stop
exit /b %ERRORLEVEL%