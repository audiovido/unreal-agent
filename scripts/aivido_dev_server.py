"""aivido_dev_server.py — DEV ONLY, never deployed.

Serves the Aivido Phase-1 UI from this worktree's ui/ directory and
proxies /api/* to the live Aivido backend (127.0.0.1:8765) so the SPA
is fully functional in a same-origin browser without touching CORS.
The live backend and its behavior are not modified in any way.

Run (from the main repo venv, pointing at this worktree):
  .venv/Scripts/python.exe C:/Users/Shadow/Desktop/Unreal-Agent-uiux-phase1/scripts/aivido_dev_server.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import requests
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

WORKTREE = Path(__file__).resolve().parents[1]
UI_DIR = WORKTREE / "ui"
BACKEND = "http://127.0.0.1:8765"

app = FastAPI(title="Aivido Phase 1 dev server", docs_url=None, redoc_url=None)


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(UI_DIR / "aivido.html")


app.mount("/static", StaticFiles(directory=str(UI_DIR)), name="static")


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy(path: str, request: Request):
    headers = {k: v for k, v in request.headers.items() if k.lower() in
               ("authorization", "content-type", "accept", "mcp-session-id")}
    body = await request.body()
    r = requests.request(
        request.method, f"{BACKEND}/api/{path}",
        data=body or None,
        headers=headers, timeout=30.0)
    return Response(content=r.content, status_code=r.status_code,
                    media_type=r.headers.get("content-type"),
                    headers={k: v for k, v in r.headers.items()
                             if k.lower() not in ("content-length", "content-encoding")})


if __name__ == "__main__":
    import uvicorn
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8866
    print(f"Aivido Phase-1 dev server: http://127.0.0.1:{port}/ "
          f"(ui from {UI_DIR}, /api -> {BACKEND})")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")