from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from fastapi import APIRouter

from app.workboard_api import cleanup_sprint

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


def _wait_for(
    task_id,
    wanted,
    timeout=600,
    idle_timeout=150,
):
    started = time.time()
    last_activity = started
    seen = []
    last_fingerprint = None

    while time.time() - started < timeout:
        task = _find_task(task_id)

        if task:
            status = task.get("status")

            fingerprint = (
                status,
                task.get("updated_at"),
                task.get("last_note"),
                len(task.get("evidence") or []),
                task.get("execution_id"),
            )

            if fingerprint != last_fingerprint:
                last_fingerprint = fingerprint
                last_activity = time.time()

            if not seen or seen[-1] != status:
                seen.append(status)

            if status in wanted:
                return task, seen

        if time.time() - last_activity > idle_timeout:
            return None, seen

        time.sleep(1)

    return None, seen


def _run():
    _reset_state()

    sprint_id = None

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
            {"finished", "blocked"},
            timeout=600,
            idle_timeout=150,
        )

        final_status = task.get("status") if task else "timeout"

        saw_progress = "progress" in seen
        reached_testing = any(
            x in seen
            for x in ("testing", "tested", "finished")
        )

        finished = final_status == "finished"

        evidence = (
            task.get("evidence", [])
            if task
            else []
        )

        qa_evidence = [
            x for x in evidence
            if x.get("type") == "qa_validation"
        ]

        qa_passed = bool(
            qa_evidence
            and qa_evidence[-1].get("passed") is True
        )

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
            },
        )

        _record(
            "Independent QA produced evidence",
            qa_passed,
            qa_evidence[-1] if qa_evidence else "missing",
        )

        _record(
            "Verified task reached Finished",
            finished and qa_passed,
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
            if sprint_id:
                cleanup = cleanup_sprint(sprint_id)

                _record(
                    "Self-test cleanup",
                    cleanup.get("ok") is True,
                    cleanup,
                )

        except Exception as exc:
            _record(
                "Self-test cleanup",
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
