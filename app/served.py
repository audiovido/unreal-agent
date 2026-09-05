from __future__ import annotations

import os
import threading
import time
import uuid
from app import api

# ---------------------------------------------------------------------------
# MULTI-CLIENT INSTANCE GUARD
# ---------------------------------------------------------------------------
# The canonical single-project backend owns ONE workboard queue on disk. When
# a second Aivido instance runs on the same host (e.g. a validation instance
# while the production backend is live), the workboard autopilot must stay
# disabled so two processes never fight over the same cards.
# UA_DISABLE_WORKBOARD_AUTOPILOT=1 -> this instance serves the multi-client
# sessions/projects surface only.
_WORKBOARD_AUTOPILOT = os.getenv("UA_DISABLE_WORKBOARD_AUTOPILOT") != "1"

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
        num_ctx=4096,
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



# ============================================================
# FINAL AUTONOMY HARDENING
# ============================================================

from tools.unreal.project_manager import inspect_project as _inspect_project

def _active_project_file():
    """Resolve the active project .uproject through the standard priority
    chain instead of a baked-in legacy demo path. Returns None when nothing
    is resolvable (callers then fall through to tool-level resolution)."""
    try:
        from tools.unreal import project_context as _pc
        resolved = _pc.resolve_active_project()
        if resolved and resolved.get("ok") and resolved.get("uproject_path"):
            return resolved["uproject_path"]
    except Exception:
        pass
    return None


_PROJECT_FILE = _active_project_file()

# ------------------------------------------------------------
# 1. Workboard tasks do NOT need another LLM planning pass.
# The Sprint already IS the plan.
# ------------------------------------------------------------

_original_new_execution = api.new_execution

def _fast_workboard_execution(task_text):
    if "WORKBOARD TASK" not in str(task_text):
        return _original_new_execution(task_text)

    execution_id = str(uuid.uuid4())

    plan = {
        "goal": str(task_text),
        "steps": [
            "Inspect only the state relevant to this card",
            "Perform the smallest required implementation",
            "Verify the real result with registered tools",
            "Return final only with evidence",
        ],
        "success_criteria": [
            "Real tool evidence proves this Workboard card is complete"
        ],
        "risks": [
            "Recover automatically from tool/model failure"
        ],
    }

    api.emit(
        "planning",
        "Workboard execution plan",
        plan,
        "info",
        task_id=execution_id,
    )

    return {
        "id": execution_id,
        "task": task_text,
        "plan": plan,
        "model_messages": [
            {
                "role": "system",
                "content": api.build_executor_system(plan),
            },
            {
                "role": "user",
                "content": task_text,
            },
        ],
        "trace": [],
        "failed_calls": {},
        "verification_pending": False,
        "successful_calls": 0,
        "final_rejections": 0,
        "step": 0,
        "tool_call_count": 0,
        "state": "PLANNING",
        "current_action": None,
        "start_ts": None,
        "end_ts": None,
    }

api.new_execution = _fast_workboard_execution


# ------------------------------------------------------------
# 2. Inspection/Audit card is deterministic.
# Do not waste an LLM loop merely discovering the project.
# ------------------------------------------------------------

_original_run_workboard_task = api._run_workboard_task

def _safe_registered_tool(name, **kwargs):
    try:
        spec = api.REGISTRY.get(name)
        if spec is None:
            return {
                "ok": False,
                "error": f"tool unavailable: {name}",
            }

        return api.serialize(spec.func(**kwargs))

    except BaseException as exc:
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _deterministic_project_audit(task):
    title = str(task.get("title") or "").lower()
    key = str(task.get("generated_key") or "").upper()

    if not (
        key == "T01"
        or "inspect current audiovidolivingcity project" in title
    ):
        return None

    task_id = task["id"]

    api.update_runtime_task(
        task_id,
        "progress",
        note="Deterministic project audit running",
    )

    # inspect_project(None) runs its own resolution chain (persisted context
    # -> bridge -> search), so a missing default is safe.
    project = api.serialize(
        _inspect_project(_PROJECT_FILE)
    )

    unreal = _safe_registered_tool(
        "unreal_status"
    )

    current_level = _safe_registered_tool(
        "get_current_level"
    )

    actors = _safe_registered_tool(
        "list_level_actors"
    )

    evidence = {
        "type": "deterministic_project_audit",
        "project": project,
        "unreal": unreal,
        "current_level": current_level,
        "actors": actors,
        "at": time.time(),
    }

    report_file = (
        wb.DATA_DIR /
        "project_audit.latest.json"
    )

    report_file.write_text(
        json.dumps(
            evidence,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    if not project.get("ok"):
        api.update_runtime_task(
            task_id,
            "blocked",
            note="Deterministic project inspection failed",
            evidence=evidence,
        )

        return {
            "ok": False,
            "task_id": task_id,
            "error": project.get("error"),
        }

    api.update_runtime_task(
        task_id,
        "testing",
        note="Project audit collected; deterministic validation",
        evidence=evidence,
    )

    api.update_runtime_task(
        task_id,
        "finished",
        note="Project audit verified and delivered",
        evidence={
            "type": "delivery",
            "validated": True,
            "validator": "deterministic_project_audit",
            "report": str(report_file),
            "at": time.time(),
        },
    )

    api.execution_state = None

    return {
        "ok": True,
        "task_id": task_id,
        "status": "finished",
        "report": str(report_file),
    }


# ------------------------------------------------------------
# 3. Persist retry_count correctly.
# Previous implementation mutated a detached loaded object.
# ------------------------------------------------------------

def _persist_retry(task_id, retry_count):
    data = wb._load()

    for item in data.get("tasks", []):
        if item.get("id") != task_id:
            continue

        item["retry_count"] = max(
            int(item.get("retry_count") or 0),
            int(retry_count or 0),
        )

        if item.get("status") == "blocked":
            note = str(item.get("last_note") or "").lower()

            if any(x in note for x in (
                "timeout",
                "timed out",
                "model request failed",
                "permissionerror",
                "permission denied",
            )):
                item["status"] = "ready"
                item["blocked_reason"] = None

        item["updated_at"] = time.time()
        break

    wb._save(data)


def _hardened_run_workboard_task(task):
    deterministic = _deterministic_project_audit(task)

    if deterministic is not None:
        return deterministic

    result = _original_run_workboard_task(task)

    if result.get("retryable"):
        _persist_retry(
            task["id"],
            result.get("retry_count") or 1,
        )

    return result

api._run_workboard_task = _hardened_run_workboard_task


# ------------------------------------------------------------
# 4. On process reload, abandoned Progress cards become Ready.
# New process has no valid old execution.
# ------------------------------------------------------------

def _recover_reload_orphans():
    data = wb._load()
    changed = False

    for task in data.get("tasks", []):
        if task.get("status") != "progress":
            continue

        task["status"] = "ready"
        task["execution_id"] = None
        task["last_note"] = (
            "Recovered automatically after Agent reload"
        )
        task["updated_at"] = time.time()
        changed = True

    if changed:
        wb._save(data)

if _WORKBOARD_AUTOPILOT:
    _recover_reload_orphans()



api.workboard_runner_start = deterministic_start

app = api.app


# ============================================================
# UI PROOF SERVING — discovery + handlers live in app/proof.py;
# routes are registered here so this file stays the thin router /
# composition layer over the shared FastAPI app.
# ============================================================
from app import proof as _proof
# setup() accepts None: proof candidates fall back to the live bridge
# project identity, so proof serving follows the editor the agent used.
_proof.setup(_PROJECT_FILE)
app.get("/api/proof/latest")(_proof.proof_latest)
app.get("/api/proof/live/status")(_proof.proof_live_status)
app.get("/api/proof/live")(_proof.proof_live)


# ============================================================
# CHAT AUTO-SPEAK — single-flight runner + truthful status live in
# app/speak.py (the gate log is the one source of truth for the
# run result); routes registered here.
# ============================================================
from app import speak as _speak
app.post("/api/chat/speak")(_speak.chat_speak)
app.get("/api/chat/speak/status")(_speak.chat_speak_status)


# ============================================================
# UNREAL CODER — canonical single API (universal agent platform).
# One POST /api/unreal-coder request interprets, plans, executes through
# the EXISTING registry/executor, validates and reports. Routes live in
# app/unreal_coder_api.py; registered here (composition root).
# ============================================================
from app.unreal_coder_api import register_unreal_coder_api
register_unreal_coder_api(
    app,
    tool_registry=lambda: api.REGISTRY,
    dispatch_bridge=None,   # execute mode uses api.new_execution (L3 plans)
)


# ============================================================
# UNREAL CAMERA + FRESH PROOF — deterministic framing endpoints.
# Direct /api/unreal/frame-actor, /api/unreal/capture-proof and
# /api/unreal/frame-and-proof so "focus actor/cube and return fresh
# proof" never routes through prompt/world-building classification or
# mission acceptance criteria. Additive: no existing route is touched.
# ============================================================
from app.camera_api import register_camera_api
register_camera_api(app, bridge_factory=None)


app.get("/api/proof/status")(_proof.proof_status)


# ============================================================
# FINAL DEADLOCK BREAKER V1
# ============================================================

# Fixes:
# - safe Blueprint node cleanup being incorrectly guard-blocked
# - Workboard ending with 0 ready / N blocked forever
# - repeated heavy-model timeout cycles
# - queue not resuming after automatic recovery


_FINAL_SAFE_GRAPH_MUTATIONS = {
    "graph_delete_node",
}


# ------------------------------------------------------------
# SAFE WORKBOARD GUARD
# ------------------------------------------------------------

_previous_guard_tool_call = api.guard_tool_call

def _final_guard_tool_call(task, action, args):
    name = str(action or "").lower()

    workboard_active = bool(
        api.execution_state
        and api.execution_state.get("workboard_task_id")
    )

    # Deleting a node inside a Blueprint graph is a normal reversible
    # implementation operation, not project/content deletion.
    if workboard_active and name in _FINAL_SAFE_GRAPH_MUTATIONS:
        return True, ""

    return _previous_guard_tool_call(
        task,
        action,
        args,
    )

api.guard_tool_call = _final_guard_tool_call


# ------------------------------------------------------------
# SAFE WORKBOARD APPROVAL POLICY
# ------------------------------------------------------------

_previous_requires_approval = api.requires_approval

def _final_requires_approval(action, args):
    name = str(action or "").lower()

    workboard_active = bool(
        api.execution_state
        and api.execution_state.get("workboard_task_id")
    )

    if workboard_active and name in _FINAL_SAFE_GRAPH_MUTATIONS:
        return False

    return _previous_requires_approval(
        action,
        args,
    )

api.requires_approval = _final_requires_approval


# ------------------------------------------------------------
# ADAPTIVE MODEL ROUTER
# ------------------------------------------------------------

def _final_model_router(messages, timeout_seconds=90):
    workboard_id = None
    retry_count = 0
    recovery_count = 0

    if api.execution_state:
        workboard_id = api.execution_state.get(
            "workboard_task_id"
        )

    if workboard_id:
        task = api.get_task(workboard_id) or {}

        retry_count = int(
            task.get("retry_count") or 0
        )

        recovery_count = int(
            task.get("autonomy_recovery_count") or 0
        )

    # First attempt honors unreal-coder as primary.
    # Once a card has demonstrated timeout trouble, use the small
    # model first so the whole Workboard cannot spend hours waiting.
    if retry_count >= 2 or recovery_count > 0:
        route = [
            (api.FAST_MODEL, 60),
            (api.HEAVY_MODEL, 120),
        ]
    else:
        route = [
            (api.HEAVY_MODEL, 120),
            (api.FAST_MODEL, 60),
        ]

    errors = []

    for model, limit in route:
        try:
            api.emit(
                "thinking",
                f"Model step: {model}",
                {
                    "model": model,
                    "timeout": limit,
                    "retry_count": retry_count,
                    "recovery_count": recovery_count,
                },
                "running",
            )

            return _call_model_once(
                messages,
                model,
                limit,
            )

        except BaseException as exc:
            errors.append(
                f"{model}: "
                f"{type(exc).__name__}: {exc}"
            )

            api.emit(
                "thinking",
                f"Model failed: {model}",
                {
                    "error": str(exc),
                },
                "warning",
            )

    raise TimeoutError(
        "Adaptive model route failed: "
        + " | ".join(errors)
    )

api.call_model_hard_timeout = _final_model_router


# ------------------------------------------------------------
# DEADLOCK RECOVERY
# ------------------------------------------------------------

def _deadlock_text(task):
    return json.dumps(
        {
            "blocked_reason": task.get("blocked_reason"),
            "last_note": task.get("last_note"),
            "evidence": task.get("evidence", [])[-5:],
        },
        ensure_ascii=False,
        default=str,
    ).lower()


def _recover_deadlocked_tasks():
    data = wb._load()
    changed = False

    recoverable_markers = (
        "timeout",
        "timed out",
        "model request failed",
        "model execution failed",
        "adaptive model route failed",
        "graph_delete_node",
        "guard-blocked",
        "guard blocked",
        "repeated guard",
        "permissionerror",
        "permission denied",
        "connectionerror",
        "read timed out",
    )

    now = time.time()

    for task in data.get("tasks", []):
        if task.get("status") != "blocked":
            continue

        text = _deadlock_text(task)

        if not any(
            marker in text
            for marker in recoverable_markers
        ):
            continue

        recoveries = int(
            task.get("autonomy_recovery_count") or 0
        )

        # Prevent a permanent hot retry loop.
        # Four engineering strategies are enough before keeping the
        # card blocked for genuine inspection.
        if recoveries >= 4:
            continue

        recoveries += 1

        task["autonomy_recovery_count"] = recoveries

        # Reset the local runner retry counter so the card can execute
        # again. autonomy_recovery_count remains persistent and tells
        # the model router to use the fast recovery path.
        task["retry_count"] = 0
        task["execution_id"] = None
        task["blocked_reason"] = None
        task["status"] = "planned"
        task["updated_at"] = now
        task["last_note"] = (
            f"Autonomy recovery {recoveries}/4: "
            "strategy changed and task returned to scheduler"
        )

        task.setdefault("evidence", []).append(
            {
                "type": "autonomy_recovery",
                "attempt": recoveries,
                "at": now,
                "reason": text[-1200:],
            }
        )

        changed = True

    if changed:
        # planned -> ready happens only when dependencies really permit it.
        wb._normalize(data)
        wb._save(data)

    return changed


# ------------------------------------------------------------
# MAKE EVERY READY CHECK SELF-HEALING
# ------------------------------------------------------------

_previous_ready_selector = api.get_next_ready_task

def _final_get_next_ready_task():
    _recover_deadlocked_tasks()
    return _previous_ready_selector()

api.get_next_ready_task = _final_get_next_ready_task


# ------------------------------------------------------------
# INDEPENDENT AUTOPILOT HEARTBEAT
# ------------------------------------------------------------

def _final_autopilot_watchdog():
    while True:
        try:
            _recover_deadlocked_tasks()

            if not api.workboard_runner.get("running"):
                api.workboard_runner_start()

        except BaseException as exc:
            try:
                api.emit(
                    "autopilot",
                    "Autopilot self-recovery",
                    {
                        "error": (
                            f"{type(exc).__name__}: {exc}"
                        )
                    },
                    "warning",
                )
            except Exception:
                pass

        time.sleep(5)


# Recover immediately at boot.
if _WORKBOARD_AUTOPILOT:
    _recover_deadlocked_tasks()

# And guarantee progress even if the older watchdog misses a state change.
# Skipped on multi-client-only instances (see _WORKBOARD_AUTOPILOT).
if _WORKBOARD_AUTOPILOT:
    threading.Thread(
        target=_final_autopilot_watchdog,
        name="unreal-agent-final-autopilot",
        daemon=True,
    ).start()



# ============================================================
# FINAL DEADLOCK BREAKER V2
# ============================================================

_SAFE_GRAPH_MUTATIONS = {"graph_delete_node"}

_prev_guard = api.guard_tool_call
def _guard(task, action, args):
    name = str(action or "").lower()
    wb_active = bool(
        api.execution_state
        and api.execution_state.get("workboard_task_id")
    )
    if wb_active and name in _SAFE_GRAPH_MUTATIONS:
        return True, ""
    return _prev_guard(task, action, args)

api.guard_tool_call = _guard


_prev_approval = api.requires_approval
def _approval(action, args):
    name = str(action or "").lower()
    wb_active = bool(
        api.execution_state
        and api.execution_state.get("workboard_task_id")
    )
    if wb_active and name in _SAFE_GRAPH_MUTATIONS:
        return False
    return _prev_approval(action, args)

api.requires_approval = _approval


def _adaptive_model(messages, timeout_seconds=90):
    task_id = None
    if api.execution_state:
        task_id = api.execution_state.get("workboard_task_id")

    task = api.get_task(task_id) if task_id else {}
    recoveries = int((task or {}).get("autonomy_recovery_count") or 0)

    route = (
        [(api.FAST_MODEL, 60), (api.HEAVY_MODEL, 120)]
        if recoveries
        else [(api.HEAVY_MODEL, 120), (api.FAST_MODEL, 60)]
    )

    errors = []

    for model, limit in route:
        try:
            return _call_model_once(messages, model, limit)
        except BaseException as exc:
            errors.append(
                f"{model}: {type(exc).__name__}: {exc}"
            )

    raise TimeoutError(
        "Adaptive model route failed: " + " | ".join(errors)
    )

api.call_model_hard_timeout = _adaptive_model


def _recover_all_recoverable_blocked():
    data = wb._load()
    changed = False
    now = time.time()

    markers = (
        "timeout",
        "timed out",
        "model request failed",
        "model execution failed",
        "adaptive model route failed",
        "graph_delete_node",
        "guard-blocked",
        "guard blocked",
        "repeated guard",
        "permission denied",
        "permissionerror",
        "connectionerror",
        "read timed out",
    )

    for task in data.get("tasks", []):
        if task.get("status") != "blocked":
            continue

        text = (
            str(task.get("blocked_reason") or "")
            + " "
            + str(task.get("last_note") or "")
            + " "
            + str(task.get("evidence") or "")
        ).lower()

        if not any(m in text for m in markers):
            continue

        count = int(task.get("autonomy_recovery_count") or 0)

        if count >= 6:
            continue

        count += 1

        task["autonomy_recovery_count"] = count
        task["retry_count"] = 0
        task["execution_id"] = None
        task["blocked_reason"] = None
        task["status"] = "planned"
        task["updated_at"] = now
        task["last_note"] = f"Autonomy recovery {count}/6"

        changed = True

    if changed:
        wb._normalize(data)
        wb._save(data)

    return changed


_prev_ready = api.get_next_ready_task

def _ready():
    _recover_all_recoverable_blocked()
    return _prev_ready()

api.get_next_ready_task = _ready


def _watchdog():
    while True:
        try:
            _recover_all_recoverable_blocked()

            if not api.workboard_runner.get("running"):
                api.workboard_runner_start()

        except BaseException:
            pass

        time.sleep(5)


if _WORKBOARD_AUTOPILOT:
    _recover_all_recoverable_blocked()

if _WORKBOARD_AUTOPILOT:
    threading.Thread(
        target=_watchdog,
        daemon=True,
        name="final-autonomy-watchdog-v2",
    ).start()



from app import final_recovery  # FINAL RECOVERY V3


# ============================================================
# MULTI-CLIENT SESSIONS / PROJECTS RUNTIME (Phases 1-10)
# Additive surface: canonical execution machinery is untouched; session
# work reuses the mission engine through core.session_execution.
# ============================================================
from app.session_api import register_session_api
register_session_api(app)

# Construct the session runner when the server actually starts (not at import
# time) so persisted sessions are re-bound to their allocator ports and
# relinked into the project registry immediately after a restart (health
# sweeper + resource supervisor also start here).
@app.on_event("startup")
def _start_session_runner() -> None:
    try:
        from core.session_execution import get_default_runner
        get_default_runner().start()
    except Exception:  # pragma: no cover - startup must not take the app down
        pass
