@echo off
rem AIVIDO V1 — one-click installer (double-click me on a fresh clone)
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-aivido.ps1" %*
exit /b %ERRORLEVEL%