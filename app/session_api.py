"""session_api.py — multi-client Aivido runtime API (Phases 1-10).

Additive REST surface for the session model, project registry, per-session
bridge allocation, resource supervision and isolated proof serving. All
endpoints are read-only with respect to the canonical single-project runtime
(they never touch the global execution_state / workboard); session work runs
through core.session_execution which reuses the canonical mission machinery.

    /api/sessions/...   session CRUD + start/action/restart/disconnect/cancel
    /api/projects/...   persistent project registry
    /api/resources      resource supervisor snapshot
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from core import project_registry
from core.bridge_allocator import get_default_allocator
from core.proof_store import get_default_store
from core.resource_supervisor import get_default_supervisor, snapshot
from core.session_model import SessionStore
from core.session_execution import (
    get_default_runner,
    session_execution_status,
)

router = APIRouter()

# ---------------------------------------------------------------------------
# Bodies
# ---------------------------------------------------------------------------


class CreateSessionBody(BaseModel):
    project_id: str
    client_id: str = "browser"


class StartBody(BaseModel):
    launch_if_needed: bool = True
    wait_s: float = 600.0


class ActionBody(BaseModel):
    prompt: str
    read_only: Optional[bool] = None
    mode: Optional[str] = None
    execution_id: Optional[str] = None


class RegisterProjectBody(BaseModel):
    uproject_path: str
    display_name: Optional[str] = None
    preferred_engine: Optional[str] = None


# ---------------------------------------------------------------------------
# Session endpoints
# ---------------------------------------------------------------------------


@router.get("/api/sessions")
def list_sessions() -> Dict[str, Any]:
    store = SessionStore()
    sessions = [s.summary() for s in store.list()]
    return {"ok": True, "sessions": sessions}


@router.post("/api/sessions")
def create_session(body: CreateSessionBody) -> Dict[str, Any]:
    reg = project_registry.get_default_registry()
    try:
        rec = reg.require(body.project_id)
    except KeyError:
        raise HTTPException(404, f"unknown project {body.project_id}")
    store = SessionStore()
    session = store.create(
        project_id=rec["project_id"],
        project_path=rec["uproject_path"],
        client_id=body.client_id or "browser",
        project_name=rec["display_name"],
    )
    return {"ok": True, "session": session.summary(),
            "status": "created"}


@router.get("/api/sessions/{session_id}")
def get_session(session_id: str) -> Dict[str, Any]:
    return session_execution_status(session_id, store=SessionStore())


@router.post("/api/sessions/{session_id}/start")
def start_session(session_id: str,
                  body: Optional[StartBody] = None) -> Dict[str, Any]:
    body = body or StartBody()
    runner = get_default_runner()
    store = SessionStore()
    session = store.get(session_id)
    if session is None:
        raise HTTPException(404, f"unknown session {session_id}")
    return runner.start_project(
        session,
        launch_if_needed=body.launch_if_needed,
        wait_s=body.wait_s,
    )


@router.post("/api/sessions/{session_id}/action")
def session_action(session_id: str, body: ActionBody) -> Dict[str, Any]:
    runner = get_default_runner()
    return runner.run_prompt(
        session_id, body.prompt,
        read_only=body.read_only,
        mode=body.mode,
        execution_id=body.execution_id,
    )


@router.post("/api/sessions/{session_id}/async")
def session_async(session_id: str, body: ActionBody) -> Dict[str, Any]:
    """Start a session prompt in the background. Poll
    GET /api/sessions/{sid}/execution/{eid} for the real result."""
    from core.session_execution import _background_results
    runner = get_default_runner()
    store = SessionStore()
    if store.get(session_id) is None:
        raise HTTPException(404, f"unknown session {session_id}")

    import uuid as _uuid
    execution_id = body.execution_id or f"exec_{_uuid.uuid4().hex[:10]}"

    def worker() -> None:
        try:
            result = runner.run_prompt(
                session_id, body.prompt,
                read_only=body.read_only,
                mode=body.mode,
                execution_id=execution_id,
            )
            _background_results[execution_id] = result
        except Exception as exc:
            _background_results[execution_id] = {
                "ok": False, "execution_id": execution_id,
                "error": f"{type(exc).__name__}: {exc}"}

    threading.Thread(target=worker, daemon=True,
                     name=f"session-async-{execution_id}").start()
    return {"ok": True, "execution_id": execution_id,
            "session_id": session_id, "status": "accepted"}


@router.get("/api/sessions/{session_id}/execution/{execution_id}")
def session_execution(session_id: str, execution_id: str) -> Dict[str, Any]:
    from core.session_execution import _background_results
    store = SessionStore()
    session = store.get(session_id)
    if session is None:
        raise HTTPException(404, f"unknown session {session_id}")
    task = session.get_task(execution_id)
    if task is None:
        raise HTTPException(404, f"unknown execution {execution_id}")
    from core.mission import MissionState
    checkpoint = MissionState.load(f"mission_{execution_id}")
    return {
        "ok": True,
        "session_id": session_id,
        "execution": task.to_dict(),
        "checkpoint": checkpoint.to_dict() if checkpoint else None,
        "background": _background_results.get(execution_id),
        "proof": get_default_store().list(session_id, execution_id),
    }


@router.get("/api/sessions/{session_id}/tasks")
def session_tasks(session_id: str) -> Dict[str, Any]:
    store = SessionStore()
    session = store.get(session_id)
    if session is None:
        raise HTTPException(404, f"unknown session {session_id}")
    tasks = [t.to_dict() for t in reversed(session.task_queue)]
    return {"ok": True, "session_id": session_id, "tasks": tasks}


@router.post("/api/sessions/{session_id}/restart")
def session_restart(session_id: str) -> Dict[str, Any]:
    return get_default_runner().restart_project(session_id)


@router.post("/api/sessions/{session_id}/disconnect")
def session_disconnect(session_id: str) -> Dict[str, Any]:
    return get_default_runner().disconnect(session_id)


@router.post("/api/sessions/{session_id}/cancel")
def session_cancel(session_id: str,
                   body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from core.session_execution import _background_results
    store = SessionStore()
    session = store.get(session_id)
    if session is None:
        raise HTTPException(404, f"unknown session {session_id}")
    eid = session.current_execution_id
    if not eid:
        return {"ok": True, "note": "no running execution to cancel"}
    runner = get_default_runner()
    runner.request_cancel(eid)
    return {"ok": True, "execution_id": eid,
            "note": "cancel requested; mission stops at the next step "
                    "boundary"}


# ---------------------------------------------------------------------------
# Isolated proof serving (path-traversal safe, session-bound)
# ---------------------------------------------------------------------------


@router.get("/api/sessions/{session_id}/proof")
def session_proof(session_id: str) -> Dict[str, Any]:
    store = SessionStore()
    if store.get(session_id) is None:
        raise HTTPException(404, f"unknown session {session_id}")
    return {"ok": True, "session_id": session_id,
            "proof": get_default_store().list(session_id)}


@router.get("/api/sessions/{session_id}/proof/{execution_id}/{name}")
def session_proof_file(session_id: str, execution_id: str,
                       name: str) -> FileResponse:
    path = get_default_store().resolve(session_id, execution_id, name)
    if path is None:
        raise HTTPException(404, "proof not found")
    return FileResponse(str(path), media_type="image/png",
                        headers={"Cache-Control": "no-store"})


# ---------------------------------------------------------------------------
# Project registry endpoints (Phase 2)
# ---------------------------------------------------------------------------


@router.get("/api/projects")
def list_projects() -> Dict[str, Any]:
    return {"ok": True, "projects": project_registry.list_projects()}


@router.post("/api/projects/register")
def register_project(body: RegisterProjectBody) -> Dict[str, Any]:
    return project_registry.register_project(
        body.uproject_path,
        display_name=body.display_name,
        preferred_engine=body.preferred_engine,
    )


@router.get("/api/projects/{project_id}")
def get_project(project_id: str) -> Dict[str, Any]:
    rec = project_registry.get_default_registry().get(project_id)
    if rec is None:
        raise HTTPException(404, f"unknown project {project_id}")
    return {"ok": True, "project": rec}


@router.post("/api/projects/{project_id}/inspect")
def inspect_project(project_id: str) -> Dict[str, Any]:
    """Read-only project inspection (registry record + live bridge probe)."""
    return {"ok": True, "project": project_registry.inspect_project(project_id)}


@router.post("/api/projects/{project_id}/connect")
def connect_project(project_id: str) -> Dict[str, Any]:
    """Connect a project: create a session and start its bridge."""
    return project_registry.get_default_registry().start_project_session(
        project_id)


@router.post("/api/projects/{project_id}/disconnect")
def disconnect_project(project_id: str) -> Dict[str, Any]:
    return project_registry.disconnect_project(project_id)


@router.post("/api/projects/{project_id}/start")
def start_project_session(project_id: str,
                          body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    client_id = (body or {}).get("client_id") or "browser"
    return project_registry.get_default_registry().start_project_session(
        project_id, client_id=client_id)


# ---------------------------------------------------------------------------
# Resources (Phase 6)
# ---------------------------------------------------------------------------


@router.get("/api/resources")
def resources() -> Dict[str, Any]:
    return {"ok": True, "supervisor": snapshot()}


@router.get("/api/multiclient/status")
def multiclient_status() -> Dict[str, Any]:
    """One-shot summary for the /app Sessions screen."""
    store = SessionStore()
    sessions = [s.summary() for s in store.list()]
    return {
        "ok": True,
        "sessions": sessions,
        "projects": project_registry.list_projects(),
        "allocator": get_default_allocator().live_bindings(),
        "resources": snapshot(),
    }


def register_session_api(app) -> None:
    """Register the multi-client router on a FastAPI app (composition root)."""
    app.include_router(router)