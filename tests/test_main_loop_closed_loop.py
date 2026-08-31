from unittest.mock import patch
from app import api


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
