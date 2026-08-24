from __future__ import annotations

import threading
from app import api

def _clear_stale():
    state = api.execution_state
    if state is None:
        return

    wb_id = state.get("workboard_task_id")

    if wb_id:
        task = api.get_task(wb_id)
        status = (task or {}).get("status")

        if status not in ("progress", "testing"):
            stale_id = state.get("id")

            for approval_id, item in list(api.pending_approvals.items()):
                if item.get("execution_id") == stale_id:
                    api.pending_approvals.pop(approval_id, None)

            api.execution_state = None


def _worker(task_id, phase):
    try:
        task = api.get_task(task_id)

        if not task:
            return

        if phase == "validation":
            result = api._validate_workboard_task(task)

            api.workboard_runner["last_result"] = {
                "phase": "validation",
                "validation": api.serialize(result),
            }
            return

        _clear_stale()

        result = api._run_workboard_task(task)

        final = {
            "phase": "execution",
            "execution": api.serialize(result),
        }

        current = api.get_task(task_id)

        if (
            result.get("ok")
            and current
            and current.get("status") == "testing"
        ):
            qa = api._validate_workboard_task(current)

            final = {
                "phase": "complete_pipeline",
                "execution": api.serialize(result),
                "validation": api.serialize(qa),
            }

        api.workboard_runner["last_result"] = final

    except BaseException as exc:
        api.workboard_runner["last_result"] = {
            "phase": "worker_crash",
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }

    finally:
        api.workboard_runner["running"] = False
        api.workboard_runner["current_task_id"] = None
        api.workboard_runner["thread"] = None


def deterministic_start():
    _clear_stale()

    active_id = (
        api.execution_state.get("id")
        if api.execution_state is not None
        else None
    )

    api.recover_orphaned_progress_tasks(
        active_execution_id=active_id
    )

    with api.lock:
        if api.workboard_runner.get("running"):
            return {
                "ok": True,
                "already_running": True,
            }

        testing = api.get_next_testing_task()
        ready = api.get_next_ready_task()

        task = testing or ready

        if task is None:
            return {
                "ok": True,
                "started": False,
                "reason": "no_executable_work",
            }

        phase = "validation" if testing else "execution"

        api.workboard_runner["running"] = True
        api.workboard_runner["stop_requested"] = False
        api.workboard_runner["current_task_id"] = task["id"]

        t = threading.Thread(
            target=_worker,
            args=(task["id"], phase),
            daemon=True,
        )

        api.workboard_runner["thread"] = t
        t.start()

    return {
        "ok": True,
        "started": True,
        "task_id": task["id"],
        "task_title": task.get("title"),
        "phase": phase,
    }


api.workboard_runner_start = deterministic_start

app = api.app
