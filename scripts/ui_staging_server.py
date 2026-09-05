"""ui_staging_server.py — staging server for a canonical Aivido UI build.

Route parity with the product backend (app/api.py), so a staged build is
reviewed exactly as it will be served in production:

    GET /           -> ava.html     (product UI — living AI companion)
    GET /app        -> aivido.html  (Director's Booth)
    GET /dev        -> index.html   (developer console)
    /static/*       -> staged build files (incl. ui-version.json)
    /api/*          -> proxied to the live backend (same-origin, no CORS)
    /healthz        -> {"ok": true}

Cross-platform: pure Python 3 stdlib + fastapi/uvicorn/requests (the same
deps the product backend already uses). No rsync/WSL/Git Bash specifics.

Run standalone:
    .venv/Scripts/python.exe scripts/ui_staging_server.py [--port 8890] [--build-id <id>]

Or through the release CLI:
    .venv/Scripts/python.exe scripts/ui_release.py serve [--port 8890]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

import requests
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
BUILD_ROOT = ROOT / "dist" / "ui-builds"
STAGING_ROOT = ROOT / "dist" / "ui-staging"
DEFAULT_BACKEND = "http://127.0.0.1:8765"

# Route map mirrored from app/api.py (and scripts/ui_release.py).
ROUTE_FILES = {
    "": "ava.html",
    "app": "aivido.html",
    "dev": "index.html",
}


def resolve_build_dir(build_id: Optional[str] = None) -> Path:
    if build_id:
        return BUILD_ROOT / build_id
    f = STAGING_ROOT / "current.txt"
    if f.is_file():
        bid = f.read_text(encoding="utf-8").strip()
        if bid:
            return BUILD_ROOT / bid
    raise SystemExit("no staged build — run 'python scripts/ui_release.py build' first")


MEDIA_TYPES = {
    ".html": "text/html", ".css": "text/css", ".js": "application/javascript",
    ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png",
    ".ico": "image/x-icon", ".woff2": "font/woff2", ".txt": "text/plain",
}


def create_app(build_dir: Optional[Path] = None, backend: str = DEFAULT_BACKEND,
               dynamic: bool = False) -> FastAPI:
    """FastAPI app serving a canonical build with backend route parity.

    dynamic=True resolves the staged build per request (rebuild + restage
    then refresh — no server restart). Otherwise build_dir is pinned.
    """

    def _resolve() -> Path:
        if dynamic or build_dir is None:
            return resolve_build_dir(None)
        resolved = Path(build_dir).resolve()
        if not (resolved / "build-manifest.json").is_file():
            raise SystemExit(f"not a ui build dir: {resolved}")
        return resolved

    app = FastAPI(title="Aivido UI staging", docs_url=None, redoc_url=None)

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> JSONResponse:
        return JSONResponse({"ok": True, "build_dir": str(_resolve())})

    for route, html_name in ROUTE_FILES.items():
        path = "/" if route == "" else f"/{route}"

        def _make(html_name: str = html_name):
            def _handler() -> FileResponse:
                return FileResponse(_resolve() / html_name)
            return _handler

        app.get(path, include_in_schema=False)(_make())

    @app.get("/static/{path:path}", include_in_schema=False)
    def static(path: str) -> Response:
        bd = _resolve()
        p = (bd / path).resolve()
        if not p.is_file() or bd not in p.parents:
            return Response(status_code=404)
        return FileResponse(p, media_type=MEDIA_TYPES.get(p.suffix.lower(), "application/octet-stream"))

    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
    async def proxy(path: str, request: Request) -> Response:
        headers = {k: v for k, v in request.headers.items()
                   if k.lower() in ("authorization", "content-type", "accept", "mcp-session-id")}
        body = await request.body()
        r = requests.request(
            request.method, f"{backend}/api/{path}",
            data=body or None, headers=headers, timeout=30.0)
        return Response(content=r.content, status_code=r.status_code,
                        media_type=r.headers.get("content-type"),
                        headers={k: v for k, v in r.headers.items()
                                 if k.lower() not in ("content-length", "content-encoding")})

    return app


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(prog="ui_staging_server.py", description=__doc__)
    ap.add_argument("--port", type=int, default=8890)
    ap.add_argument("--build-id", default=None, help="build to serve (default: staged)")
    ap.add_argument("--backend", default=DEFAULT_BACKEND, help=f"backend proxy (default {DEFAULT_BACKEND})")
    args = ap.parse_args(argv)

    import uvicorn
    build_dir = resolve_build_dir(args.build_id)
    app = create_app(build_dir, args.backend)
    print(f"Staging server: http://127.0.0.1:{args.port}/  (build {build_dir.name} · /api -> {args.backend})")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))