"""Deterministic terminal-state tests.

Goal: prove that a successful execution emits COMPLETE exactly once, never
EXECUTION_STALLED, and that EXECUTION_STALLED only fires on genuinely
unfinished work with no progress/recovery path. Also proves resume/restart
does not duplicate terminal events.

The module autouse fixture redirects the durable parent-goal file into a temp
dir so these tests can never clobber the live Agent's task_goal.json.
"""
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import task_goal

from app import api


@pytest.fixture(autouse=True)
def isolated_goal_file(tmp_path, monkeypatch):
    monkeypatch.setattr(task_goal, "TASK_GOAL_FILE", tmp_path / "task_goal.json")

ACTOR = "TERMINAL_STATE_FINAL_TEST"


def _cube_plan():
    actor = ACTOR
    return {
        "goal": "cube",
        "success_criteria": [],
        "steps": [
            {"step_id": "inspect", "phase": "INSPECT", "intent": "inspect_project",
             "preferred_tool": "inspect_project", "allowed_tools": ["inspect_project"],
             "parameters": {}, "expected_result": {}, "depends_on": [], "disposable": False,
             "status": "pending"},
            {"step_id": "spawn", "phase": "EDIT", "intent": "spawn_actor",
             "preferred_tool": "spawn_actor", "allowed_tools": ["spawn_actor"],
             "parameters": {"class_name": "StaticMeshActor", "actor_name": actor,
                            "location": [0, 0, 0], "scale": [0.5, 0.5, 0.5],
                            "mesh_asset": "/Engine/BasicShapes/Cube.Cube"},
             "expected_result": {}, "depends_on": ["inspect"], "disposable": False,
             "status": "pending"},
            {"step_id": "save", "phase": "BUILD", "intent": "save_level",
             "preferred_tool": "save_level", "allowed_tools": ["save_level"],
             "parameters": {}, "expected_result": {}, "depends_on": ["spawn"],
             "disposable": False, "status": "pending"},
            {"step_id": "verify", "phase": "VALIDATE", "intent": "get_actor",
             "preferred_tool": "get_actor", "allowed_tools": ["get_actor"],
             "parameters": {"actor_name": actor}, "expected_result": {"exists": True},
             "depends_on": ["save"], "disposable": False, "status": "pending"},
        ],
    }


def _cube_state():
    return {
        "id": str(uuid.uuid4()),
        "task": "Spawn a cube named TERMINAL_STATE_FINAL_TEST, save the level, verify it exists.",
        "project_context": dict(api._default_project_context()),
        "phase": "PLAN", "current_phase": "PLAN", "current_step": 0, "completed_steps": [],
        "failed_step": None, "retry_count": 0, "validation_result": None,
        "created_resources": [], "processed_dispatch_ids": [],
        "fix_pending": False, "fix_step_id": None, "retry_pending": False,
        "retry_validation_step_id": None, "max_retries": 3, "max_tool_calls": 40,
        "model_messages": [], "trace": [], "failed_calls": {}, "verification_pending": False,
        "successful_calls": 0, "final_rejections": 0, "step": 0, "tool_call_count": 0,
        "state": "PLANNING", "current_action": None, "start_ts": None, "end_ts": None,
        "plan": _cube_plan(),
    }


def _happy_fake(spec, args, timeout_seconds=60):
    n = spec.name
    if n == "inspect_project":
        return {"ok": True, "result": {"project": "AVLC"}}
    if n == "spawn_actor":
        return {"ok": True, "result": {"actor_name": args.get("actor_name"), "success": True}}
    if n == "save_level":
        return {"ok": True, "result": {"saved": True}}
    if n == "get_actor":
        return {"ok": True, "result": {"found": True}}
    return {"ok": True, "result": {}}


def _event_counts():
    complete = sum(1 for e in api.events if e.get("type") == "complete")
    stalled = sum(1 for e in api.events if e.get("title") == "EXECUTION_STALLED")
    return complete, stalled


def _run(state, fake=_happy_fake):
    api.execution_state = state
    with patch.object(api, "call_tool_hard_timeout", side_effect=fake):
        return api.run_execution_until_pause()


def test_all_steps_success_emits_complete_exactly_once():
    api.events.clear()
    state = _cube_state()
    result = _run(state)
    complete, stalled = _event_counts()
    # Core regression: never EXECUTION_STALLED after genuine success.
    assert stalled == 0
    assert complete == 1
    assert result["state"] == "complete"
    assert result["terminal"] == "PASS"
    assert state["state"] == "COMPLETE"
    assert state["final_verdict"] == "PASS"
    assert state["terminal_emitted"] is True
    assert api.execution_state is None
    assert state["validation_result"] == "passed"
    assert state["failed_step"] is None


def test_successful_read_back_emits_complete():
    api.events.clear()
    state = _cube_state()
    result = _run(state)
    assert result["state"] == "complete"
    assert state["validation_result"] == "passed"
    assert any(e.get("type") == "complete" for e in api.events)


def test_empty_queue_after_success_completes():
    # All steps already completed + validation passed -> the loop must go
    # terminal COMPLETE immediately (empty queue), never EXECUTION_STALLED.
    api.events.clear()
    state = _cube_state()
    for s in state["plan"]["steps"]:
        s["status"] = "completed"
    state["validation_result"] = "passed"
    state["state"] = "RUNNING"
    result = _run(state, fake=lambda spec, args, timeout_seconds=60: {"ok": True, "result": {}})
    assert result["state"] == "complete"
    assert state["state"] == "COMPLETE"
    assert _event_counts() == (1, 0)


def test_failed_mandatory_step_is_not_complete():
    # Direct gate: a failed mandatory validation step is FAILED, not complete.
    state = _cube_state()
    state["plan"] = {"steps": [
        {"step_id": "m1", "status": "failed", "phase": "VALIDATE", "intent": "get_actor"}
    ]}
    state["failed_step"] = "m1"
    state["validation_result"] = "failed"
    assert api._can_complete(state) is False
    blocker = api._completion_blocker(state)
    assert blocker["code"] == "FAILED"

    # End-to-end: a failing mandatory step must not emit COMPLETE.
    api.events.clear()
    state = _cube_state()

    def failing(spec, args, timeout_seconds=60):
        if spec.name == "spawn_actor":
            return {"ok": False, "error": "bridge unavailable"}
        return _happy_fake(spec, args, timeout_seconds=timeout_seconds)

    result = _run(state, fake=failing)
    assert result["state"] == "failed"
    assert state["state"] in ("FAILED", "STALLED")
    assert _event_counts()[0] == 0  # no COMPLETE


def test_pending_retry_is_not_complete():
    state = _cube_state()
    state["retry_pending"] = True
    state["retry_validation_step_id"] = "verify"
    assert api._can_complete(state) is False
    assert api._completion_blocker(state)["code"] == "RETRYING"

    # Loop with a retry step that cannot be found -> not complete, structured stall.
    api.events.clear()
    state = _cube_state()
    for s in state["plan"]["steps"]:
        s["status"] = "completed"
    state["validation_result"] = "passed"
    state["retry_pending"] = True
    state["retry_validation_step_id"] = "ghost-step"
    result = _run(state, fake=lambda spec, args, timeout_seconds=60: {"ok": True, "result": {}})
    assert result["state"] == "failed"
    assert result["terminal"] == "STALL"
    assert _event_counts()[0] == 0  # never complete while a retry is unresolved


def test_true_no_progress_emits_structured_stall():
    # A mandatory step can never run (dependency is unsatisfiable) and no
    # cleanup exists. This is genuine unfinished work with no progress path ->
    # EXECUTION_STALLED with STALL_NO_PROGRESS.
    api.events.clear()
    state = _cube_state()
    for s in state["plan"]["steps"]:
        s["status"] = "completed"
    state["validation_result"] = "passed"
    state["plan"]["steps"].append({
        "step_id": "orphan", "status": "pending", "phase": "EDIT",
        "intent": "save_level", "preferred_tool": "save_level", "depends_on": ["never-done"],
        "disposable": False,
    })
    result = _run(state, fake=lambda spec, args, timeout_seconds=60: {"ok": True, "result": {}})
    assert result["state"] == "failed"
    assert result["terminal"] == "STALL"
    assert result["stall_reason"] == api.STALL_NO_PROGRESS
    assert state["stall_reason"] == api.STALL_NO_PROGRESS
    assert _event_counts()[1] == 1  # EXECUTION_STALLED emitted
    assert _event_counts()[0] == 0  # and never COMPLETE


def test_true_no_progress_cleanup_recovery_exhausted():
    # A disposable resource that can never be verified clean -> recovery
    # exhausted structured stall, never a false COMPLETE.
    api.events.clear()
    state = api.new_execution("cleanup probe")
    state["plan"] = {"steps": []}
    state["validation_result"] = "passed"
    state["created_resources"] = [{"path": "/Game/Probe", "disposable": True}]

    def present_fake(spec, args, timeout_seconds=60):
        # delete succeeds, but get_asset_info always reports it still present.
        return {"ok": True} if spec.name == "delete_asset" else {"ok": True, "path": "/Game/Probe"}

    result = _run(state, fake=present_fake)
    assert result["state"] == "failed"
    assert result["terminal"] == "STALL"
    assert result["stall_reason"] == api.STALL_RECOVERY_EXHAUSTED
    assert _event_counts()[0] == 0


def test_resume_does_not_duplicate_terminal_events():
    api.events.clear()
    state = _cube_state()
    first = _run(state)
    assert first["state"] == "complete"
    complete_after_first = _event_counts()[0]

    # Simulate restart/resume against the same persisted execution.
    api.execution_state = state
    resumed = api.run_execution_until_pause()
    assert resumed["once"] is True
    assert resumed["state"] == "complete"
    assert resumed["terminal"] == "PASS"
    assert _event_counts()[0] == complete_after_first  # exactly once