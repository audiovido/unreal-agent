from __future__ import annotations

import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]

PROJECT = Path(
    r"C:\Users\Shadow\Desktop\app\AudioVidoLivingCity"
)

DATA_DIR = PROJECT / "Saved" / "UnrealAgent" / "Workboard"
DATA_FILE = DATA_DIR / "workboard.json"

router = APIRouter(prefix="/api/workboard")


STATUSES = [
    "planned",
    "approval",
    "ready",
    "progress",
    "testing",
    "tested",
    "finished",
    "blocked",
]


class PlanRequest(BaseModel):
    title: str = ""
    description: str = ""
    start_at: str | None = None
    end_at: str | None = None


class TaskRequest(BaseModel):
    sprint_id: str
    title: str
    description: str = ""
    priority: int = 50
    requires_approval: bool = False
    scheduled_at: str | None = None
    estimate_minutes: int | None = None


class MoveRequest(BaseModel):
    status: str


class ScheduleRequest(BaseModel):
    scheduled_at: str | None = None
    priority: int | None = None


def _default_state():
    return {
        "version": 1,
        "updated_at": time.time(),
        "sprints": [],
        "tasks": [],
        "activity": [],
    }


def _load():
    try:
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except Exception:
        return _default_state()


def _save(data):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = time.time()
    DATA_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return data


def _activity(data, kind, text, task_id=None):
    data.setdefault("activity", []).append({
        "id": str(uuid.uuid4()),
        "kind": kind,
        "text": text,
        "task_id": task_id,
        "at": time.time(),
    })
    data["activity"] = data["activity"][-200:]


def _iso_due(value):
    if not value:
        return True
    try:
        dt = datetime.fromisoformat(value)
        return datetime.now(dt.tzinfo) >= dt
    except Exception:
        return True


def _normalize_task(task):
    status = task.get("status", "planned")

    if status == "planned":
        if task.get("requires_approval") and not task.get("approved"):
            task["status"] = "approval"
        elif _iso_due(task.get("scheduled_at")):
            task["status"] = "ready"

    if status == "approval" and task.get("approved"):
        if _iso_due(task.get("scheduled_at")):
            task["status"] = "ready"

    return task


def _normalize(data):
    for task in data.get("tasks", []):
        _normalize_task(task)
    return data


@router.get("/state")
def state():
    return {
        "ok": True,
        "data": _save(_normalize(_load())),
    }


@router.post("/sprints")
def create_sprint(req: PlanRequest):
    data = _load()

    sprint = {
        "id": str(uuid.uuid4()),
        "title": req.title.strip() or "New Sprint",
        "description": req.description.strip(),
        "start_at": req.start_at,
        "end_at": req.end_at,
        "status": "active",
        "created_at": time.time(),
    }

    data["sprints"].append(sprint)
    _activity(data, "sprint_created", f"Sprint created: {sprint['title']}")

    return {
        "ok": True,
        "sprint": sprint,
        "data": _save(data),
    }


@router.post("/tasks")
def create_task(req: TaskRequest):
    data = _load()

    task = {
        "id": str(uuid.uuid4()),
        "sprint_id": req.sprint_id,
        "title": req.title.strip() or "Untitled Task",
        "description": req.description.strip(),
        "priority": req.priority,
        "requires_approval": req.requires_approval,
        "approved": not req.requires_approval,
        "scheduled_at": req.scheduled_at,
        "estimate_minutes": req.estimate_minutes,
        "status": (
            "approval"
            if req.requires_approval
            else (
                "ready"
                if _iso_due(req.scheduled_at)
                else "planned"
            )
        ),
        "created_at": time.time(),
        "started_at": None,
        "finished_at": None,
        "evidence": [],
    }

    data["tasks"].append(task)
    _activity(data, "task_created", f"Task created: {task['title']}", task["id"])

    return {
        "ok": True,
        "task": task,
        "data": _save(data),
    }


@router.post("/tasks/{task_id}/approve")
def approve_task(task_id: str):
    data = _load()

    for task in data["tasks"]:
        if task["id"] == task_id:
            task["approved"] = True
            task["approved_at"] = time.time()

            if _iso_due(task.get("scheduled_at")):
                task["status"] = "ready"
            else:
                task["status"] = "planned"

            _activity(
                data,
                "approved",
                f"Approved: {task['title']}",
                task_id,
            )

            return {
                "ok": True,
                "task": task,
                "data": _save(data),
            }

    return {"ok": False, "error": "task not found"}


@router.post("/tasks/{task_id}/reject")
def reject_task(task_id: str):
    data = _load()

    for task in data["tasks"]:
        if task["id"] == task_id:
            task["approved"] = False
            task["status"] = "blocked"
            task["blocked_reason"] = "Approval rejected"

            _activity(
                data,
                "rejected",
                f"Approval rejected: {task['title']}",
                task_id,
            )

            return {
                "ok": True,
                "task": task,
                "data": _save(data),
            }

    return {"ok": False, "error": "task not found"}


@router.post("/tasks/{task_id}/move")
def move_task(task_id: str, req: MoveRequest):
    if req.status not in STATUSES:
        return {"ok": False, "error": "invalid status"}

    data = _load()

    for task in data["tasks"]:
        if task["id"] == task_id:

            if (
                req.status in ("ready", "progress", "testing", "tested", "finished")
                and task.get("requires_approval")
                and not task.get("approved")
            ):
                return {
                    "ok": False,
                    "error": "task requires approval",
                }

            task["status"] = req.status

            if req.status == "progress" and not task.get("started_at"):
                task["started_at"] = time.time()

            if req.status == "finished":
                task["finished_at"] = time.time()

            _activity(
                data,
                "status_changed",
                f"{task['title']} ? {req.status}",
                task_id,
            )

            return {
                "ok": True,
                "task": task,
                "data": _save(data),
            }

    return {"ok": False, "error": "task not found"}


@router.post("/tasks/{task_id}/schedule")
def schedule_task(task_id: str, req: ScheduleRequest):
    data = _load()

    for task in data["tasks"]:
        if task["id"] == task_id:
            if req.scheduled_at is not None:
                task["scheduled_at"] = req.scheduled_at

            if req.priority is not None:
                task["priority"] = req.priority

            _normalize_task(task)

            _activity(
                data,
                "rescheduled",
                f"Schedule updated: {task['title']}",
                task_id,
            )

            return {
                "ok": True,
                "task": task,
                "data": _save(data),
            }

    return {"ok": False, "error": "task not found"}


@router.post("/tick")
def scheduler_tick():
    data = _load()

    before = {
        t["id"]: t.get("status")
        for t in data.get("tasks", [])
    }

    _normalize(data)

    for task in data.get("tasks", []):
        if before.get(task["id"]) != task.get("status"):
            _activity(
                data,
                "scheduler",
                f"Scheduler moved {task['title']} ? {task['status']}",
                task["id"],
            )

    return {
        "ok": True,
        "data": _save(data),
    }


# ============================================================
# WORKBOARD EXECUTION HELPERS
# ============================================================

def get_next_ready_task():
    data = _save(_normalize(_load()))

    ready = [
        t for t in data.get("tasks", [])
        if t.get("status") == "ready"
        and (
            not t.get("requires_approval")
            or t.get("approved")
        )
    ]

    if not ready:
        return None

    ready.sort(
        key=lambda t: (
            -int(t.get("priority") or 0),
            float(t.get("created_at") or 0),
        )
    )

    return ready[0]


def update_runtime_task(
    task_id: str,
    status: str,
    *,
    note: str | None = None,
    evidence=None,
    execution_id: str | None = None,
):
    data = _load()

    for task in data.get("tasks", []):
        if task.get("id") != task_id:
            continue

        task["status"] = status
        task["updated_at"] = time.time()

        if status == "progress" and not task.get("started_at"):
            task["started_at"] = time.time()

        if status == "finished":
            task["finished_at"] = time.time()

        if execution_id is not None:
            task["execution_id"] = execution_id

        if note:
            task["last_note"] = note

        if evidence is not None:
            task.setdefault("evidence", []).append(evidence)

        _activity(
            data,
            "runner",
            f"{task.get('title')} ? {status}"
            + (f" | {note}" if note else ""),
            task_id,
        )

        _save(data)
        return task

    return None


def get_task(task_id: str):
    data = _load()

    for task in data.get("tasks", []):
        if task.get("id") == task_id:
            return task

    return None
