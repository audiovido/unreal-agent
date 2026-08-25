from __future__ import annotations

import threading
import time
import uuid
from app import api

# ============================================================
# WORKBOARD PERSISTENCE HARDENING
# ============================================================

import json
from app import workboard_api as wb

BACKUP_FILE = wb.DATA_DIR / "workboard.last_good.json"
_original_load = wb._load
_original_save = wb._save

def _product_ids(data):
    return {
        x.get("id")
        for x in data.get("sprints", [])
        if x.get("id")
        and not str(x.get("title") or "").startswith("__SELFTEST__")
    }

def _has_product(data):
    return bool(_product_ids(data))

def _read_backup():
    try:
        return json.loads(
            BACKUP_FILE.read_text(encoding="utf-8")
        )
    except Exception:
        return None

def _merge_product(current, backup):
    if not backup or not _has_product(backup):
        return current

    current = dict(current or {})
    current.setdefault("sprints", [])
    current.setdefault("tasks", [])
    current.setdefault("activity", [])

    sprint_ids = {x.get("id") for x in current["sprints"]}
    task_ids = {x.get("id") for x in current["tasks"]}
    product_ids = _product_ids(backup)

    for sprint in backup.get("sprints", []):
        if (
            sprint.get("id") in product_ids
            and sprint.get("id") not in sprint_ids
        ):
            current["sprints"].append(sprint)

    for task in backup.get("tasks", []):
        if (
            task.get("sprint_id") in product_ids
            and task.get("id") not in task_ids
        ):
            current["tasks"].append(task)

    return current

def hardened_load():
    data = _original_load()
    return _merge_product(data, _read_backup())

def hardened_save(data):
    data = _merge_product(data, _read_backup())
    saved = _original_save(data)

    if _has_product(saved):
        wb.DATA_DIR.mkdir(parents=True, exist_ok=True)

        tmp = wb.DATA_DIR / f"workboard.last_good.{uuid.uuid4().hex}.tmp"
        tmp.write_text(
            json.dumps(
                saved,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        for attempt in range(8):
            try:
                tmp.replace(BACKUP_FILE)
                break
            except PermissionError:
                if attempt == 7:
                    raise
                time.sleep(0.05 * (attempt + 1))

    return saved

wb._load = hardened_load
wb._save = hardened_save



def _call_model_once(messages, model, timeout_seconds):
    # Do NOT wrap requests in a daemon thread.
    # Timed-out model threads used to overlap and overload Ollama.
    return api.call_model(
        messages,
        model=model,
        json_mode=True,
        temperature=0.08,
        num_ctx=8192,
        timeout=timeout_seconds,
    )


def resilient_model(messages, timeout_seconds=90):
    errors = []

    # Unreal Coder remains the normal/default execution model.
    try:
        api.emit(
            "thinking",
            "Using unreal-coder:latest",
            {"model": api.HEAVY_MODEL},
            "running",
        )

        return _call_model_once(
            messages,
            api.HEAVY_MODEL,
            180,
        )

    except Exception as exc:
        errors.append(
            f"{api.HEAVY_MODEL}: {type(exc).__name__}: {exc}"
        )

    # One lightweight emergency fallback only.
    try:
        api.emit(
            "thinking",
            "Primary model failed - using fast fallback",
            {"model": api.FAST_MODEL},
            "warning",
        )

        return _call_model_once(
            messages,
            api.FAST_MODEL,
            90,
        )

    except Exception as exc:
        errors.append(
            f"{api.FAST_MODEL}: {type(exc).__name__}: {exc}"
        )

    raise TimeoutError(
        "Model execution failed: " + " | ".join(errors)
    )


api.call_model_hard_timeout = resilient_model


def _recover_transient_blocked():
    data = wb._load()
    changed = False

    markers = (
        "timeout",
        "timed out",
        "permissionerror",
        "permission denied",
        "model request failed",
    )

    for task in data.get("tasks", []):
        if task.get("status") != "blocked":
            continue

        text = (
            str(task.get("blocked_reason") or "")
            + " "
            + str(task.get("last_note") or "")
        ).lower()

        if not any(x in text for x in markers):
            continue

        retries = int(task.get("retry_count") or 0)

        if retries >= 3:
            continue

        task["retry_count"] = retries + 1
        task["status"] = "ready"
        task["blocked_reason"] = None
        task["last_note"] = (
            f"Automatic recovery retry {retries + 1}/3"
        )
        task["updated_at"] = time.time()
        changed = True

    if changed:
        wb._save(data)



# Make the EXISTING api.py autopilot watchdog recovery-aware.
# It calls api.get_next_ready_task() every few seconds, so wrapping that
# function guarantees transient blocked tasks are recovered BEFORE the
# watchdog decides there is no executable work.
_original_get_next_ready_task = api.get_next_ready_task

def recovering_get_next_ready_task():
    _recover_transient_blocked()
    return _original_get_next_ready_task()

api.get_next_ready_task = recovering_get_next_ready_task


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
    _recover_transient_blocked()

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
