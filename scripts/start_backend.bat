@echo off
rem Start the existing Unreal Agent FastAPI backend (app/api.py) on 0.0.0.0:8765.
cd /d C:\Users\Shadow\Desktop\Unreal-Agent
".venv\Scripts\python.exe" -m uvicorn app.api:app --host 0.0.0.0 --port 8765 >> backend_ui_audit.log 2>&1