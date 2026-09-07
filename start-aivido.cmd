@echo off
rem AIVIDO V1 — double-click to start (or: start-aivido.cmd status|stop|...)
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-aivido.ps1" %*
exit /b %ERRORLEVEL%