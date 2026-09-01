import sys
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


def _plan():
    task = "Create /Game/AgentGraduation/BP_FinalSelfFixProbe. Add String variable AgentGraduationMarker. Initially set it to WRONG_VALUE. Expected value is EXPECTED_VALUE. Capture evidence. Delete the probe."
    return api.normalize_execution_plan(task, {})


def test_main_loop_consumes_normalized_steps_and_cleanup():
    state = api.new_execution("Create /Game/AgentGraduation/BP_FinalSelfFixProbe. Add String variable AgentGraduationMarker. Initially set it to WRONG_VALUE. Expected value is EXPECTED_VALUE. Capture evidence. Delete the probe.")
    state["plan"] = _plan()
    state["state"] = "PLANNING"
    values = iter(["WRONG_VALUE", "EXPECTED_VALUE"])
    calls = []
    def fake(spec, args, timeout_seconds=60):
        calls.append(spec.name)
        if spec.name == "get_blueprint_variable_default":
            return {"ok": True, "result": {"value": next(values)}}
        if spec.name == "get_asset_info":
            return {"ok": False, "error": "Asset not found"}
        if spec.name == "delete_asset":
            return {"ok": True, "result": {"deleted": True}}
        if spec.name == "capture_unreal_viewport":
            return {"ok": True, "result": {"path": "fake.png"}}
        if spec.name == "create_blueprint":
            return {"ok": True, "result": {"asset_path": "/Game/AgentGraduation/BP_FinalSelfFixProbe"}}
        if spec.name == "delete_asset":
            return {"ok": True, "result": {"deleted": True}}
        return {"ok": True, "result": {}}
    api.events.clear()
    with patch.object(api, "call_tool_hard_timeout", side_effect=fake), patch.object(api, "call_model_hard_timeout", side_effect=AssertionError("model must not be selected")):
        api.execution_state = state
        result = api.run_execution_until_pause()
    assert result["state"] == "complete"
    assert api.execution_state is None
    assert state["validation_result"] == "passed"
    assert state["failed_step"] is None
    assert state["retry_count"] == 1
    assert "create_blueprint" in calls
    assert "delete_asset" in calls
    assert any(e["title"] == "COMPLETE" for e in api.events)


def test_layer_f_true_main_loop_happy_path():
    task = "Create /Game/AgentGraduation/BP_FinalSelfFixProbe. Add String variable AgentGraduationMarker. Initially set it to WRONG_VALUE. Expected value is EXPECTED_VALUE. Capture evidence. Delete the probe."
    state = api.new_execution(task)
    state["plan"] = _plan()
    state["max_execution_iterations"] = 40
    calls = []
    values = iter(["WRONG_VALUE", "EXPECTED_VALUE"])
    def fake(spec, args, timeout_seconds=60):
        calls.append(spec.name)
        if spec.name == "get_blueprint_variable_default": return {"ok": True, "result": {"value": next(values)}}
        if spec.name == "create_blueprint": return {"ok": True, "result": {"asset_path": "/Game/AgentGraduation/BP_FinalSelfFixProbe"}}
        if spec.name == "capture_unreal_viewport": return {"ok": True, "result": {"path": "evidence.png"}}
        if spec.name == "delete_asset": return {"ok": True, "result": {"deleted": True}}
        if spec.name == "get_asset_info": return {"ok": True, "result": {"found": False}}
        return {"ok": True, "result": {}}
    api.execution_state = state
    with patch.object(api, "call_tool_hard_timeout", side_effect=fake):
        result = api.run_execution_until_pause()
    assert result["state"] == "complete"
    assert state["state"] == "COMPLETE"
    assert calls.count("get_blueprint_variable_default") == 2
    assert calls.count("set_blueprint_variable_default") == 2
    assert calls.count("delete_asset") == 1
    assert calls.count("get_asset_info") == 1
    assert len([s for s in state["plan"]["steps"] if s["step_id"].startswith("fix:")]) == 1
    assert not api._cleanup_pending(state)
    api.execution_state = None


def test_layer_f_terminal_complete_exits_without_dispatch():
    state = {"state": "COMPLETE"}; api.execution_state = state
    with patch.object(api, "_deterministic_step_dispatch") as dispatch:
        result = api.run_execution_until_pause()
    assert result["state"] == "complete"; dispatch.assert_not_called(); api.execution_state = None


def test_main_loop_cleanup_verification_failure_is_not_complete():
    state = api.new_execution("cleanup")
    state["plan"] = {"steps": []}
    state["validation_result"] = "passed"
    state["created_resources"] = [{"path": "/Game/AgentGraduation/Probe", "disposable": True}]
    api.execution_state = state
    def fake(spec, args, timeout_seconds=60):
        return {"ok": True} if spec.name == "delete_asset" else {"ok": True, "path": "/Game/AgentGraduation/Probe"}
    with patch.object(api, "call_tool_hard_timeout", side_effect=fake):
        result = api.run_execution_until_pause()
    assert result["state"] == "failed"
    assert state["created_resources"][0].get("verified_clean") is not True
    api.execution_state = None


def test_actor_removal_loop_deletes_and_verifies_absence():
    task = ("Create a visible cube actor named UA_FinalCloseoutMarker, save the level, "
            "verify it exists, then remove it and verify cleanup.")
    state = api.new_execution(task)
    state["plan"] = api.normalize_execution_plan(task, {})
    state["state"] = "PLANNING"
    calls = []

    def fake(spec, args, timeout_seconds=60):
        calls.append(spec.name)
        if spec.name == "spawn_actor":
            return {"ok": True, "result": {"name": "StaticMeshActor_9", "label": "UA_FinalCloseoutMarker"}}
        if spec.name == "get_actor":
            if "delete_actor" in calls:
                return {"ok": False, "error": "Actor not found: UA_FinalCloseoutMarker"}
            return {"ok": True, "result": {"name": "StaticMeshActor_9", "label": "UA_FinalCloseoutMarker"}}
        if spec.name == "delete_actor":
            return {"ok": True, "result": {"deleted": True, "label": "UA_FinalCloseoutMarker"}}
        if spec.name == "save_level":
            return {"ok": True, "result": {"saved": True}}
        return {"ok": True, "result": {}}

    api.events.clear()
    with patch.object(api, "call_tool_hard_timeout", side_effect=fake), \
            patch.object(api, "call_model_hard_timeout", side_effect=AssertionError("model must not be selected")):
        api.execution_state = state
        result = api.run_execution_until_pause()
    assert result["state"] == "complete"
    assert state["state"] == "COMPLETE"
    assert "delete_actor" in calls
    assert calls.count("save_level") == 2
    assert state.get("cleanup_failure") is None
    assert any(e["title"] == "COMPLETE" for e in api.events)
    api.execution_state = None


def test_actor_removal_verify_still_present_is_not_complete():
    state = api.new_execution("remove the actor")
    state["plan"] = {"steps": [{
        "step_id": "verify_actor_absent",
        "phase": "VERIFY_CLEANUP",
        "intent": "get_actor",
        "preferred_tool": "get_actor",
        "parameters": {"actor_name": "UA_StillThere"},
        "expected_result": {"absent": True},
        "depends_on": [],
        "status": "pending",
    }]}
    state["validation_result"] = "passed"
    api.execution_state = state

    def fake(spec, args, timeout_seconds=60):
        # Actor is still present: absence verification must NOT pass.
        return {"ok": True, "result": {"name": "UA_StillThere", "label": "UA_StillThere"}}

    with patch.object(api, "call_tool_hard_timeout", side_effect=fake):
        result = api.run_execution_until_pause()
    assert result["state"] == "failed"
    assert state.get("cleanup_failure", {}).get("reason") == "resource_still_present"
    api.execution_state = None
