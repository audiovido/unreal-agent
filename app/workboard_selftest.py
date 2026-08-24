from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from fastapi import APIRouter

from app.workboard_api import DATA_FILE

router = APIRouter(prefix="/api/workboard/selftest")

BASE = "http://127.0.0.1:8765"

STATE = {
    "running": False,
    "status": "idle",
    "started_at": None,
    "finished_at": None,
    "current_test": None,
    "passed": 0,
    "failed": 0,
    "results": [],
    "error": None,
}


def _reset_state():
    STATE.update({
        "running": True,
        "status": "running",
        "started_at": time.time(),
        "finished_at": None,
        "current_test": None,
        "passed": 0,
        "failed": 0,
        "results": [],
        "error": None,
    })


def _record(name, ok, detail=""):
    STATE["results"].append({
        "name": name,
        "ok": bool(ok),
        "detail": str(detail),
        "at": time.time(),
    })

    if ok:
        STATE["passed"] += 1
    else:
        STATE["failed"] += 1


def _request(path, method="GET", body=None, timeout=15):
    raw = None

    if body is not None:
        raw = json.dumps(body).encode("utf-8")

    req = urllib.request.Request(
        BASE + path,
        data=raw,
        method=method,
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            payload = response.read().decode("utf-8")
            return json.loads(payload) if payload else {}

    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(payload)
        except Exception:
            data = {"detail": payload}

        return {
            "_http_error": exc.code,
            **data,
        }


def _find_task(task_id):
    data = _request("/api/workboard/state")
    board = data.get("data") or {}

    for task in board.get("tasks", []):
        if task.get("id") == task_id:
            return task

    return None


def _wait_for(task_id, wanted, timeout=180):
    deadline = time.time() + timeout
    seen = []

    while time.time() < deadline:
        task = _find_task(task_id)

        if task:
            status = task.get("status")

            if not seen or seen[-1] != status:
                seen.append(status)

            if status in wanted:
                return task, seen

        time.sleep(2)

    return None, seen


def _run():
    _reset_state()

    had_file = DATA_FILE.exists()
    original = DATA_FILE.read_bytes() if had_file else None

    try:
        # ----------------------------------------------------
        # TEST 1: Sprint creation
        # ----------------------------------------------------
        STATE["current_test"] = "Sprint creation"

        sprint_response = _request(
            "/api/workboard/sprints",
            "POST",
            {
                "title": "__SELFTEST__",
                "description": "Temporary automated Agent Board test",
            },
        )

        sprint = sprint_response.get("sprint") or {}
        sprint_id = sprint.get("id")

        ok = bool(sprint_id)
        _record("Sprint creation", ok, sprint_id or sprint_response)

        if not ok:
            raise RuntimeError("Could not create self-test sprint")

        # ----------------------------------------------------
        # TEST 2: Approval gate
        # ----------------------------------------------------
        STATE["current_test"] = "Approval gate"

        approval_response = _request(
            "/api/workboard/tasks",
            "POST",
            {
                "sprint_id": sprint_id,
                "title": "__SELFTEST_APPROVAL__",
                "description": "Approval gate test",
                "priority": 10,
                "requires_approval": True,
            },
        )

        approval_task = approval_response.get("task") or {}
        approval_id = approval_task.get("id")

        gate_initial = approval_task.get("status") == "approval"

        move_before_approval = _request(
            f"/api/workboard/tasks/{approval_id}/move",
            "POST",
            {"status": "progress"},
        )

        blocked_before_approval = (
            move_before_approval.get("ok") is False
            and "approval" in str(move_before_approval.get("error", "")).lower()
        )

        approved = _request(
            f"/api/workboard/tasks/{approval_id}/approve",
            "POST",
        )

        approved_task = approved.get("task") or {}

        approval_ok = (
            gate_initial
            and blocked_before_approval
            and approved_task.get("approved") is True
            and approved_task.get("status") in ("ready", "planned")
        )

        _record(
            "Approval gate",
            approval_ok,
            {
                "initial": approval_task.get("status"),
                "blocked_without_approval": blocked_before_approval,
                "after_approve": approved_task.get("status"),
            },
        )

        # Keep approval test from entering execution queue.
        _request(
            f"/api/workboard/tasks/{approval_id}/move",
            "POST",
            {"status": "finished"},
        )

        # ----------------------------------------------------
        # TEST 3: Real Queue ? Agent execution
        # ----------------------------------------------------
        STATE["current_test"] = "Queue execution"

        execute_response = _request(
            "/api/workboard/tasks",
            "POST",
            {
                "sprint_id": sprint_id,
                "title": "Inspect current level and report actor count",
                "description": (
                    "Read-only self-test. Inspect the current Unreal level "
                    "and report its actor count. Do not modify the project."
                ),
                "priority": 100,
                "requires_approval": False,
            },
        )

        execute_task = execute_response.get("task") or {}
        execute_id = execute_task.get("id")

        created_ready = execute_task.get("status") == "ready"

        _record(
            "Executable task enters Ready",
            created_ready,
            execute_task.get("status"),
        )

        if not execute_id:
            raise RuntimeError("Could not create executable self-test task")

        _request("/api/workboard/runner/start", "POST")

        task, seen = _wait_for(
            execute_id,
            {"testing", "tested", "finished", "blocked"},
            timeout=180,
        )

        final_status = task.get("status") if task else "timeout"

        saw_progress = "progress" in seen
        reached_testing = final_status in ("testing", "tested", "finished")

        _record(
            "Queue moved task to In Progress",
            saw_progress,
            seen,
        )

        _record(
            "Agent completion moved task to Testing",
            reached_testing,
            {
                "seen": seen,
                "final": final_status,
                "note": task.get("last_note") if task else None,
            },
        )

        # ----------------------------------------------------
        # TEST 4: Runner status endpoint
        # ----------------------------------------------------
        STATE["current_test"] = "Runner status"

        runner = _request("/api/workboard/runner/status")

        _record(
            "Runner status API",
            runner.get("ok") is True,
            runner,
        )

        STATE["status"] = (
            "pass"
            if STATE["failed"] == 0
            else "fail"
        )

    except BaseException as exc:
        STATE["error"] = f"{type(exc).__name__}: {exc}"
        STATE["status"] = "fail"
        _record("Self-test runtime", False, STATE["error"])

    finally:
        STATE["current_test"] = "cleanup"

        try:
            _request("/api/workboard/runner/stop", "POST", timeout=5)
        except Exception:
            pass

        # Give cooperative runner a moment to leave its loop.
        time.sleep(2)

        try:
            if had_file and original is not None:
                DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
                DATA_FILE.write_bytes(original)

            elif DATA_FILE.exists():
                DATA_FILE.unlink()

        except Exception as exc:
            _record(
                "Restore board state",
                False,
                f"{type(exc).__name__}: {exc}",
            )
            STATE["status"] = "fail"

        STATE["running"] = False
        STATE["current_test"] = None
        STATE["finished_at"] = time.time()


@router.post("/start")
def start_selftest():
    if STATE["running"]:
        return {
            "ok": True,
            "already_running": True,
            "state": STATE,
        }

    threading.Thread(
        target=_run,
        name="workboard-selftest",
        daemon=True,
    ).start()

    return {
        "ok": True,
        "started": True,
    }


@router.get("/status")
def selftest_status():
    return {
        "ok": True,
        "state": STATE,
    }
