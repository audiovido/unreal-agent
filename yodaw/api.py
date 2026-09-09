"""YODAW Code Core API control plane."""
from __future__ import annotations

import os
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .commands import CommandRequest
from .missions import MissionStore
from .orchestrator import MissionOrchestrator
from .targets import build_targets
from .workspaces import WorkspaceManager

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = Path(os.environ.get("YODAW_STATE_DIR", str(ROOT / "memory" / "yodaw")))
workspace_manager = WorkspaceManager(STATE_DIR)
mission_store = MissionStore(STATE_DIR, workspace_manager)

def _targets() -> dict[str, Any]:
    return build_targets({"targets": {"local": {"type": "local"}}})

target_adapters = _targets()
active_threads: dict[str, threading.Thread] = {}

app = FastAPI(title="YODAW Code Core", version="0.2.0")


class MissionRequest(BaseModel):
    prompt: str
    repo: str
    target: str = "local"
    max_workers: int = Field(default=4, ge=1, le=16)
    auto_commit: bool = True
    auto_push: bool = False
    remote: str = "origin"
    plan: list[dict[str, Any]] | None = None


class CommandBody(BaseModel):
    target: str = "local"
    cwd: str = "."
    command: str | list[str]
    env: dict[str, str] = Field(default_factory=dict)
    timeout: float = Field(default=120.0, gt=0, le=3600)
    shell: bool = False
    allowed_root: str | None = None


class TargetTestBody(BaseModel):
    target: str


class TargetConfigBody(BaseModel):
    name: str
    type: str = "ssh"
    host: str | None = None
    user: str | None = None
    port: int = 22
    identity_file: str | None = None
    shell: str | None = None


def _mission_runner(mission_id: str) -> None:
    mission = mission_store.get(mission_id)
    if mission is None: return
    if mission.cancel_requested:
        return
    mission_store.update(mission_id, state="RUNNING", stage="planning")
    orchestrator = MissionOrchestrator(
        workspace_manager=workspace_manager,
        max_workers=mission.max_workers,
        cancelled=lambda: bool((mission_store.get(mission_id) or mission).cancel_requested),
        update=lambda **fields: mission_store.update(mission_id, **fields),
    )
    result = orchestrator.run(
        mission_id=mission_id, repo=mission.repo, prompt=mission.prompt,
        raw_plan=mission.plan or None, auto_commit=mission.auto_commit,
        auto_push=mission.auto_push, remote=mission.remote or "origin",
    )
    current = mission_store.get(mission_id)
    if current is None or current.cancel_requested:
        return
    workers = result.get("workers", [])
    files = sorted({f for worker in workers for f in worker.get("changed_files", [])})
    passing = [worker for worker in workers if worker.get("state") == "PASS"]
    commits = [worker.get("commit_sha") for worker in passing if worker.get("commit_sha")]
    mission_store.update(
        mission_id, state=result.get("state", "FAILED"), stage=result.get("stage", "complete"),
        workers=workers, changed_files=files, blockers=result.get("blockers", []),
        push_status=result.get("push_status", "not_requested"),
        commit_sha=commits[-1] if commits else None,
    )
    mission_store.append_evidence(mission_id, {"stage": result.get("stage"), "result": result})


@app.on_event("startup")
def _startup() -> None:
    mission_store.recover()


@app.get("/health")
def health() -> dict[str, str]:
    return {"api": "ready", "workers": "ready", "git": "ready"}


@app.get("/")
def ui() -> FileResponse:
    return FileResponse(Path(__file__).resolve().parent / "ui" / "index.html")


@app.post("/api/code/missions", status_code=202)
def create_mission(body: MissionRequest) -> dict[str, Any]:
    if body.target not in target_adapters:
        raise HTTPException(404, f"unknown target: {body.target}")
    if body.target != "local":
        raise HTTPException(501, "remote mission orchestration is not enabled for this local launcher; use /api/code/command with the SSH target")
    if not Path(body.repo).expanduser().exists():
        raise HTTPException(400, "repo does not exist")
    mission = mission_store.create(
        body.prompt, body.repo, target=body.target, max_workers=body.max_workers,
        auto_commit=body.auto_commit, auto_push=body.auto_push, remote=body.remote,
        plan=body.plan or [], state="RUNNING", stage="queued",
    )
    thread = threading.Thread(target=_mission_runner, args=(mission.mission_id,), daemon=True, name=f"mission-{mission.mission_id}")
    active_threads[mission.mission_id] = thread; thread.start()
    return {"mission_id": mission.mission_id, "status": mission.state}


@app.get("/api/code/missions")
def list_missions() -> dict[str, Any]:
    return {"missions": [asdict(m) for m in mission_store.list()]}


@app.get("/api/code/missions/{mission_id}")
def get_mission(mission_id: str) -> dict[str, Any]:
    mission = mission_store.get(mission_id)
    if mission is None: raise HTTPException(404, "mission not found")
    return asdict(mission)


@app.get("/api/code/missions/{mission_id}/evidence")
def get_evidence(mission_id: str) -> dict[str, Any]:
    try: return {"mission_id": mission_id, "evidence": mission_store.evidence(mission_id)}
    except KeyError: raise HTTPException(404, "mission not found")


@app.post("/api/code/missions/{mission_id}/retry")
def retry_mission(mission_id: str) -> dict[str, Any]:
    mission = mission_store.get(mission_id)
    if mission is None: raise HTTPException(404, "mission not found")
    if mission.state == "RUNNING": raise HTTPException(409, "mission is already running")
    mission = mission_store.update(mission_id, state="RUNNING", stage="retry", blockers=[], cancel_requested=False, current_attempt=mission.current_attempt + 1)
    thread = threading.Thread(target=_mission_runner, args=(mission_id,), daemon=True, name=f"mission-{mission_id}-retry")
    active_threads[mission_id] = thread; thread.start()
    return {"mission_id": mission_id, "status": mission.state, "attempt": mission.current_attempt}


@app.post("/api/code/missions/{mission_id}/cancel")
def cancel_mission(mission_id: str) -> dict[str, Any]:
    try:
        mission = mission_store.request_cancel(mission_id)
        return {"mission_id": mission_id, "status": mission.state}
    except KeyError: raise HTTPException(404, "mission not found")


@app.post("/api/code/command")
def run_command(body: CommandBody) -> dict[str, Any]:
    adapter = target_adapters.get(body.target)
    if adapter is None: raise HTTPException(404, f"unknown target: {body.target}")
    root = body.allowed_root or body.cwd
    result = adapter.run_command(CommandRequest(target=body.target, cwd=body.cwd, command=body.command, env=body.env, timeout=body.timeout, shell=body.shell, allowed_root=root))
    return result.to_dict()


@app.get("/api/code/targets")
def list_targets() -> dict[str, Any]:
    return {"targets": [{"name": name, "type": adapter.config.type, "host": adapter.config.host, "port": adapter.config.port} for name, adapter in target_adapters.items()]}


@app.post("/api/code/targets")
def add_target(body: TargetConfigBody) -> dict[str, Any]:
    global target_adapters
    target_adapters[body.name] = build_targets({"targets": {body.name: body.model_dump(exclude={"name"})}})[body.name]
    return {"ok": True, "target": body.name}


@app.post("/api/code/targets/test")
def test_target(body: TargetTestBody) -> dict[str, Any]:
    adapter = target_adapters.get(body.target)
    if adapter is None: raise HTTPException(404, f"unknown target: {body.target}")
    return adapter.test_connection()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("yodaw.api:app", host="127.0.0.1", port=8790)
