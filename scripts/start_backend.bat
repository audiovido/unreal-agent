@echo off
rem Start the Aivido product backend (app.served:app) on 127.0.0.1:8765.
rem app.served mounts the session/projects API, final recovery, and the
rem session runner that app.api:app alone does not serve.
rem Workboard autopilot stays off so background cards never execute
rem unattended; set UA_ENABLE_WORKBOARD_AUTOPILOT=1 to opt in.
cd /d "%~dp0.."
if not exist logs mkdir logs
if not defined UA_DISABLE_WORKBOARD_AUTOPILOT set UA_DISABLE_WORKBOARD_AUTOPILOT=1
".venv\Scripts\python.exe" -m uvicorn app.served:app --host 127.0.0.1 --port 8765 >> logs\backend.log 2>&1
