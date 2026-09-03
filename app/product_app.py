"""product_app.py — the one-click Unreal Agent product server (FastAPI).

Serves the minimal end-user UI (ui/product.html) and a small set of
routes over the real product core (core.product_core).  There is no
second execution engine here: every request routes through the same
bridge -> registry -> fresh-capture -> Step-5 release evaluation ->
Step-6/7 autonomous-director machinery that the release missions use.

The developer/advanced console (app/api.py on :8765) is untouched;
this product server is a separate, deliberately small surface.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.product_core import session as product_session
from core.product_core import PROOF_DIR, READY, FAILED, COMPLETE

ROOT = Path(__file__).resolve().parents[1]
UI_DIR = ROOT / "ui"

app = FastAPI(title="Unreal Agent — Product", docs_url=None, redoc_url=None)


class ConnectBody(BaseModel):
    uproject: Optional[str] = None
    launch_if_needed: bool = False


class RunBody(BaseModel):
    prompt: str


class SelectBody(BaseModel):
    uproject: Optional[str] = None


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(UI_DIR / "product.html")


app.mount("/static", StaticFiles(directory=str(UI_DIR)), name="static")


# ---------------------------------------------------------------------------
# Status / projects
# ---------------------------------------------------------------------------

@app.get("/api/ua/status")
def status() -> Dict[str, Any]:
    return product_session.status()


@app.get("/api/ua/projects")
def projects() -> Dict[str, Any]:
    last = (product_session._cfg or {}).get("last_project")
    if not last:
        # Lane-B config fallback so a brand-new user still gets a default
        # (read-only; product.json stays the write-side recent-project store).
        try:
            from core import app_config
            recent = app_config.load_config().recent_project
            if recent:
                last = {"name": Path(recent).stem,
                        "uproject_path": str(Path(recent).resolve())
                        .replace("\\", "/")}
        except Exception:
            pass
    return {"known": product_session.known_projects(), "last": last}


# ---------------------------------------------------------------------------
# Step 9 — environment / first-run / ownership (product integration hooks)
# ---------------------------------------------------------------------------

@app.get("/api/ua/env")
def env() -> Dict[str, Any]:
    """Concise environment state: config model + offline doctor summary +
    persisted first-run snapshot.  Concise for the user, structured for the
    developer view (no raw tracebacks)."""
    from core import app_config, env_doctor, first_run
    cfg = app_config.load_config()
    doctor = env_doctor.run(probe_backend=False, probe_ports=False)
    return {
        "config": cfg.to_dict(),
        "doctor": {"overall": doctor["overall"],
                   "summary": doctor["summary"],
                   "user_error": doctor["user_error"],
                   "checks": doctor["checks"],
                   "failures": doctor["failures"],
                   "warnings": doctor["warnings"]},
        "first_run": first_run.load_snapshot(),
        "unreal_builds": [b for b in app_config.detect_unreal_builds()
                          if b.get("editor_exe")],
    }


@app.get("/api/ua/leases")
def leases() -> Dict[str, Any]:
    """Read-only ownership view (owner/task/expiry).  Never used to mutate
    a lease from the UI; release happens on task terminal paths in core."""
    from core import editor_lease
    reg = editor_lease.LeaseRegistry()
    current = None
    try:
        ident = product_session._lease_identity()
        if ident:
            current = reg.status(ident)
    except Exception:
        pass
    return {"leases": reg.list_leases(),
            "current_project": current,
            "owner": product_session._owner_id}


@app.post("/api/ua/refresh-first-run")
def refresh_first_run() -> Dict[str, Any]:
    """Recompute + persist the first-run snapshot from current reality."""
    product_session._refresh_first_run_snapshot(product_session.state.project)
    from core import first_run
    return {"ok": True, "first_run": first_run.load_snapshot()}


@app.post("/api/ua/select")
def select(body: SelectBody) -> Dict[str, Any]:
    """Remember which project the UI intends to use (no connection yet)."""
    if not body.uproject:
        return {"ok": False, "error": "no project given"}
    from pathlib import Path as _P
    if not _P(body.uproject).exists():
        return {"ok": False, "error": f"project file not found: {body.uproject}"}
    product_session._cfg["last_project"] = {
        "name": _P(body.uproject).stem,
        "uproject_path": str(_P(body.uproject).resolve()).replace("\\", "/")}
    product_session._remember_project(product_session._cfg["last_project"])
    return {"ok": True}


# ---------------------------------------------------------------------------
# Connect / recovery
# ---------------------------------------------------------------------------

@app.post("/api/ua/connect")
def connect(body: ConnectBody) -> Dict[str, Any]:
    """One-click connect: validate -> reuse running editor -> verify -> READY
    (launch only when explicitly allowed; this call is bounded and never
    hangs silently)."""
    return product_session.connect(body.uproject,
                                   launch_if_needed=body.launch_if_needed,
                                   wait_s=25.0)


@app.post("/api/ua/reconnect")
def reconnect() -> Dict[str, Any]:
    return product_session.reconnect()


# ---------------------------------------------------------------------------
# Task lifecycle
# ---------------------------------------------------------------------------

@app.post("/api/ua/run")
def run(body: RunBody) -> JSONResponse:
    prompt = (body.prompt or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="empty prompt")
    r = product_session.run_task(prompt)
    if not r.get("ok"):
        raise HTTPException(status_code=409, detail=r)
    return JSONResponse({"ok": True, "task_id": r.get("task_id")},
                        status_code=202)


@app.post("/api/ua/cancel")
def cancel() -> Dict[str, Any]:
    return product_session.cancel()


# ---------------------------------------------------------------------------
# Evidence / proof serving (path-traversal safe)
# ---------------------------------------------------------------------------

@app.get("/api/ua/proof/{task_id}/{name}")
def proof(task_id: str, name: str) -> FileResponse:
    safe_task = Path(task_id).name
    safe_name = Path(name).name
    p = (PROOF_DIR / safe_task / safe_name).resolve()
    base = PROOF_DIR.resolve()
    if base not in p.parents or not p.exists():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(p)


@app.get("/api/ua/proof-file")
def proof_file(path: str) -> FileResponse:
    """Serve one proof image by absolute path (guard: must be under the
    product proof root; path traversal impossible)."""
    p = Path(path).resolve()
    base = PROOF_DIR.resolve()
    if base not in p.parents or not p.exists() or p.suffix.lower() != ".png":
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(p)


@app.get("/api/ua/evidence")
def evidence() -> Dict[str, Any]:
    out: List[Dict[str, Any]] = []
    if PROOF_DIR.exists():
        for task_dir in sorted(PROOF_DIR.iterdir()):
            if not task_dir.is_dir():
                continue
            for f in sorted(task_dir.glob("*.png")):
                out.append({"task_id": task_dir.name, "name": f.name,
                            "url": f"/api/ua/proof/{task_dir.name}/{f.name}",
                            "size": f.stat().st_size})
    return {"evidence": out}


# ---------------------------------------------------------------------------
# Entry point (product server only; developer console stays on :8765)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    # Step 9 — bind through the product config model; the Lane-B lifecycle
    # (product_launcher) already prevents duplicate backend instances.
    try:
        from core import app_config
        cfg = app_config.load_config()
        host, port = cfg.backend_host, cfg.backend_port
    except Exception:
        host, port = "127.0.0.1", 8799
    uvicorn.run(app, host=host, port=port, log_level="info")
