from __future__ import annotations

import json
import time
import uuid
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]


def _active_project_root():
    """Resolve the active project root through the standard priority chain
    instead of a baked-in legacy demo path. Falls back to the repo workspace
    dir so the workboard keeps working on machines with no Unreal project yet."""
    try:
        from tools.unreal import project_context as _pc
        resolved = _pc.resolve_active_project()
        if resolved and resolved.get("ok") and resolved.get("uproject_path"):
            return Path(resolved["uproject_path"]).resolve().parent
    except Exception:
        pass
    return ROOT / "workspace"


PROJECT = _active_project_root()

DATA_DIR = PROJECT / "Saved" / "UnrealAgent" / "Workboard"
DATA_FILE = DATA_DIR / "workboard.json"

router = APIRouter(prefix="/api/workboard")

WORKBOARD_LOCK = threading.RLock()


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
    depends_on: list[str] = []


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
    with WORKBOARD_LOCK:
        try:
            return json.loads(
                DATA_FILE.read_text(encoding="utf-8")
            )
        except Exception:
            return _default_state()


def _save(data):
    with WORKBOARD_LOCK:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        data["updated_at"] = time.time()

        # Every writer gets its own temp file.
        # A shared workboard.json.tmp caused Windows PermissionError
        # when reload/autopilot threads saved concurrently.
        tmp = DATA_DIR / (
            f"workboard.{uuid.uuid4().hex}.tmp"
        )

        tmp.write_text(
            json.dumps(
                data,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        last_error = None

        for attempt in range(8):
            try:
                tmp.replace(DATA_FILE)
                last_error = None
                break
            except PermissionError as exc:
                last_error = exc
                time.sleep(0.05 * (attempt + 1))

        if last_error is not None:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
            raise last_error

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


def _dependencies_finished(task, data):
    deps = task.get("depends_on") or []

    if not deps:
        return True

    by_id = {
        t.get("id"): t
        for t in data.get("tasks", [])
    }

    return all(
        by_id.get(dep, {}).get("status") == "finished"
        for dep in deps
    )


def _needs_real_human_approval(task):
    """
    Human approval is reserved for genuinely sensitive / irreversible work.
    Routine Unreal planning, coding, builds and validation are autonomous.
    """
    text = (
        str(task.get("title") or "")
        + " "
        + str(task.get("description") or "")
    ).lower()

    sensitive = (
        "delete important",
        "delete production",
        "publish externally",
        "deploy production",
        "spend money",
        "purchase",
        "billing",
        "overwrite external",
        "destructive migration",
        "irreversible",
    )

    return any(x in text for x in sensitive)


def _normalize_task(task, data=None):
    status = task.get("status", "planned")

    # Migrate old generated tasks created under the previous
    # over-cautious approval policy.
    if (
        task.get("requires_approval")
        and not _needs_real_human_approval(task)
    ):
        task["requires_approval"] = False
        task["approved"] = True
        task["approval_migrated"] = True

        if status == "approval":
            status = "planned"
            task["status"] = "planned"

    deps_ready = (
        True
        if data is None
        else _dependencies_finished(task, data)
    )

    if status == "planned":
        if task.get("requires_approval") and not task.get("approved"):
            task["status"] = "approval"

        elif (
            deps_ready
            and _iso_due(task.get("scheduled_at"))
        ):
            task["status"] = "ready"

    elif status == "approval" and task.get("approved"):
        if (
            deps_ready
            and _iso_due(task.get("scheduled_at"))
        ):
            task["status"] = "ready"
        else:
            task["status"] = "planned"

    return task


def _normalize(data):
    # Re-run a few times so a newly finished dependency can unlock
    # the next item in the same scheduler cycle.
    for _ in range(3):
        for task in data.get("tasks", []):
            _normalize_task(task, data)

    return data



def _internal_sprint_ids(data):
    return {
        sprint.get("id")
        for sprint in data.get("sprints", [])
        if str(sprint.get("title") or "").startswith("__SELFTEST__")
    }


def _is_internal_task(task, data):
    return task.get("sprint_id") in _internal_sprint_ids(data)


def _public_state(data):
    internal_ids = _internal_sprint_ids(data)

    return {
        **data,
        "sprints": [
            sprint for sprint in data.get("sprints", [])
            if sprint.get("id") not in internal_ids
        ],
        "tasks": [
            task for task in data.get("tasks", [])
            if task.get("sprint_id") not in internal_ids
        ],
        "activity": [
            item for item in data.get("activity", [])
            if not str(item.get("text") or "").startswith("__SELFTEST__")
        ],
    }


@router.get("/state")
def state(include_internal: bool = False):
    data = _save(_normalize(_load()))

    return {
        "ok": True,
        "data": data if include_internal else _public_state(data),
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
        "depends_on": list(req.depends_on or []),
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

            _normalize_task(task, data)

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


def get_next_testing_task():
    data = _save(_normalize(_load()))

    testing = [
        t for t in data.get("tasks", [])
        if t.get("status") == "testing"
        and not _is_internal_task(t, data)
    ]

    if not testing:
        return None

    testing.sort(
        key=lambda t: (
            -int(t.get("priority") or 0),
            float(t.get("updated_at") or t.get("created_at") or 0),
        )
    )

    return testing[0]

def get_next_ready_task():
    data = _save(_normalize(_load()))

    ready = [
        t for t in data.get("tasks", [])
        if t.get("status") == "ready"
        and not _is_internal_task(t, data)
        and (
            not t.get("requires_approval")
            or t.get("approved")
        )
        and _dependencies_finished(t, data)
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


def recover_orphaned_progress_tasks(active_execution_id=None):
    """
    Any Workboard task left In Progress without the matching live
    Agent execution is stale and must be safely returned to Ready.
    """
    data = _load()
    recovered = []

    for task in data.get("tasks", []):
        if task.get("status") != "progress":
            continue

        execution_id = task.get("execution_id")

        if active_execution_id and execution_id == active_execution_id:
            continue

        task["status"] = "ready"
        task["execution_id"] = None
        task["last_note"] = "Recovered after interrupted Agent execution"
        task["updated_at"] = time.time()

        recovered.append(task["id"])

        _activity(
            data,
            "recovery",
            f"Recovered interrupted task: {task.get('title')} -> ready",
            task["id"],
        )

    if recovered:
        _save(data)

    return recovered


def cleanup_sprint(sprint_id: str):
    """
    Remove only one Sprint and its Tasks.
    Used by autonomous self-test so real user board data is never restored
    from an old snapshot or overwritten.
    """
    with WORKBOARD_LOCK:
        data = _load()

        task_ids = {
            task.get("id")
            for task in data.get("tasks", [])
            if task.get("sprint_id") == sprint_id
        }

        data["tasks"] = [
            task
            for task in data.get("tasks", [])
            if task.get("sprint_id") != sprint_id
        ]

        data["sprints"] = [
            sprint
            for sprint in data.get("sprints", [])
            if sprint.get("id") != sprint_id
        ]

        data["activity"] = [
            item
            for item in data.get("activity", [])
            if item.get("task_id") not in task_ids
        ]

        _save(data)

        return {
            "ok": True,
            "sprint_id": sprint_id,
            "removed_tasks": len(task_ids),
        }


def touch_runtime_task(task_id: str, note: str | None = None):
    """
    Lightweight execution heartbeat.
    Updates liveness without creating noisy activity entries.
    """
    with WORKBOARD_LOCK:
        data = _load()

        for task in data.get("tasks", []):
            if task.get("id") != task_id:
                continue

            task["updated_at"] = time.time()
            task["heartbeat_at"] = time.time()

            if note:
                task["heartbeat_note"] = note

            _save(data)
            return task

    return None


def commit_generated_plan(plan: dict):
    """
    Atomically create one Sprint and its AI-generated task graph.
    Dependency references use temporary task keys in the preview
    and are resolved to real task IDs during commit.
    """
    with WORKBOARD_LOCK:
        data = _load()

        now = time.time()

        sprint = {
            "id": str(uuid.uuid4()),
            "title": str(plan.get("title") or "Generated Sprint").strip(),
            "description": str(plan.get("description") or "").strip(),
            "start_at": plan.get("start_at"),
            "end_at": plan.get("end_at"),
            "status": "active",
            "generated": True,
            "created_at": now,
        }

        data["sprints"].append(sprint)

        raw_tasks = list(plan.get("tasks") or [])
        key_to_id = {}

        # Pass 1: allocate stable IDs.
        for index, item in enumerate(raw_tasks):
            key = str(
                item.get("key")
                or f"task_{index + 1}"
            )

            key_to_id[key] = str(uuid.uuid4())

        # Pass 2: build cards and resolve dependency keys.
        created = []

        for index, item in enumerate(raw_tasks):
            key = str(
                item.get("key")
                or f"task_{index + 1}"
            )

            depends_keys = list(item.get("depends_on") or [])

            depends_ids = [
                key_to_id[x]
                for x in depends_keys
                if x in key_to_id
            ]

            requires_approval = bool(
                item.get("requires_approval", False)
            )

            task = {
                "id": key_to_id[key],
                "sprint_id": sprint["id"],
                "generated_key": key,
                "order": int(item.get("order") or index + 1),
                "title": str(item.get("title") or "Untitled Task").strip(),
                "description": str(item.get("description") or "").strip(),
                "priority": max(
                    1,
                    min(100, int(item.get("priority") or 50)),
                ),
                "requires_approval": requires_approval,
                "approved": not requires_approval,
                "scheduled_at": item.get("scheduled_at"),
                "estimate_minutes": (
                    int(item["estimate_minutes"])
                    if item.get("estimate_minutes") is not None
                    else None
                ),
                "depends_on": depends_ids,
                "depends_on_keys": depends_keys,
                "status": (
                    "approval"
                    if requires_approval
                    else "planned"
                ),
                "created_at": now + (index * 0.001),
                "started_at": None,
                "finished_at": None,
                "evidence": [],
                "generated": True,
            }

            data["tasks"].append(task)
            created.append(task)

        _normalize(data)

        _activity(
            data,
            "plan_generated",
            f"AI plan committed: {sprint['title']} ({len(created)} tasks)",
        )

        _save(data)

        return {
            "ok": True,
            "sprint": sprint,
            "tasks": created,
            "data": data,
        }
