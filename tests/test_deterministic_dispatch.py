from unittest.mock import patch
from app import api


def test_result_helpers_accept_bridge_wrapped_shapes():
    assert api._tool_success({'ok': True, 'result': {'value': 'WRONG_VALUE'}})
    assert api._tool_success({'success': True})
    assert api._tool_success({'status': 'success'})
    assert api._extract_tool_value({'ok': True, 'result': {'value': 'WRONG_VALUE'}}) == 'WRONG_VALUE'
    assert api._extract_resource_path({'ok': True, 'result': {'asset_path': '/Game/Probe'}}) == '/Game/Probe'
    assert api._extract_tool_error({'detail': 'bad'}) == 'bad'
    assert api._tool_success(None) is False


def test_next_normalized_step_is_pure_and_dependency_ready():
    steps = [
        {'step_id': 'a', 'status': 'completed'},
        {'step_id': 'b', 'status': 'pending', 'depends_on': ['a']},
        {'step_id': 'c', 'status': 'pending', 'depends_on': ['missing']},
    ]
    state = {'plan': {'steps': steps}}
    index, step = api._next_normalized_step(state)
    assert index == 1 and step['step_id'] == 'b'


def test_resolved_args_inject_project_path_without_model():
    step = {'preferred_tool': 'inspect_project', 'parameters': {}}
    args = api._resolved_step_args({'project_context': {}}, step)
    assert args['uproject_path'].endswith('AudioVidoLivingCity.uproject')


def test_dispatch_is_control_pure():
    with patch.object(api, 'create_execution_plan', return_value={}):
        s = api.new_execution('inspect current project')
    s['phase'] = 'INSPECT'
    s['current_step'] = 0
    step = {'step_id': 'inspect', 'phase': 'INSPECT', 'preferred_tool': 'unreal_ping', 'parameters': {}, 'allowed_tools': ['unreal_ping'], 'status': 'pending', 'disposable': False}
    before = {k: s.get(k) for k in ('phase', 'current_phase', 'current_step', 'failed_step', 'validation_result', 'created_resources', 'retry_count')}
    with patch.object(api, 'call_tool_hard_timeout', return_value={'ok': True}) as runner, patch.object(api, 'call_model_hard_timeout') as model:
        result = api._deterministic_step_dispatch(s, step)
    assert result['tool_name'] == 'unreal_ping'
    assert result['transport_success'] is True
    assert {k: s.get(k) for k in before} == before
    assert step['status'] == 'pending'
    runner.assert_called_once()
    model.assert_not_called()


def test_apply_step_result_ordinary_success_completes_step():
    state = {"created_resources": []}
    step = {"step_id": "inspect", "status": "pending", "phase": "INSPECT", "disposable": False}
    result = {"dispatch_id": "d1", "transport_success": True, "resource_path": None}
    applied = api._apply_step_result(state, step, result)
    assert applied["status"] == "completed"
    assert step["status"] == "completed"


def test_apply_step_result_ordinary_failure_records_error():
    state = {"created_resources": []}
    step = {"step_id": "inspect", "status": "running", "phase": "INSPECT", "disposable": False}
    applied = api._apply_step_result(state, step, {"dispatch_id": "d2", "transport_success": False, "error": "bad"})
    assert applied["status"] == "failed"
    assert step["status"] == "failed"
    assert state["failure_evidence"]["error"] == "bad"


def test_apply_step_result_validation_passes():
    state = {"created_resources": [], "failed_step": "old"}
    step = {"step_id": "validate", "status": "pending", "phase": "VALIDATE", "expected_result": {"expected": "ok"}}
    applied = api._apply_step_result(state, step, {"dispatch_id": "d3", "transport_success": True, "value": "ok"})
    assert applied["validation"] == "passed"
    assert state["validation_result"] == "passed"
    assert state["failed_step"] is None


def test_apply_step_result_validation_mismatch_records_evidence():
    state = {"created_resources": []}
    step = {"step_id": "validate", "status": "pending", "phase": "VALIDATE", "expected_result": {"expected": "expected"}}
    applied = api._apply_step_result(state, step, {"dispatch_id": "d4", "transport_success": True, "value": "actual"})
    assert applied["validation"] == "failed"
    assert state["failed_step"] == "validate"
    assert state["failure_evidence"]["expected"] == "expected"
    assert state["failure_evidence"]["actual"] == "actual"


def test_readback_does_not_register_duplicate_disposable_resource():
    state = {"created_resources": []}
    create = {"step_id": "create", "intent": "create_blueprint", "status": "pending", "phase": "EDIT", "disposable": True}
    readback = {"step_id": "read", "intent": "get_blueprint_variable_default", "status": "pending", "phase": "VALIDATE", "disposable": True}
    api._apply_step_result(state, create, {"dispatch_id": "rd1", "transport_success": True, "resource_path": "/Game/Probe"})
    api._apply_step_result(state, readback, {"dispatch_id": "rd2", "transport_success": True, "resource_path": "/Game/Probe.Probe", "value": "ok"})
    assert [item["path"] for item in state["created_resources"]] == ["/Game/Probe"]


def test_apply_step_result_tracks_disposable_resource_once():
    state = {"created_resources": []}
    step = {"step_id": "create", "status": "pending", "phase": "EDIT", "disposable": True}
    result = {"dispatch_id": "d5", "transport_success": True, "resource_path": "/Game/Probe", "resource_type": "Blueprint"}
    api._apply_step_result(state, step, result)
    assert len(state["created_resources"]) == 1
    assert state["created_resources"][0] == {"path": "/Game/Probe", "resource_type": "Blueprint", "step_id": "create", "disposable": True, "verified_clean": False}


def test_apply_step_result_rejects_duplicate_dispatch():
    state = {"created_resources": []}
    step = {"step_id": "create", "status": "pending", "phase": "EDIT", "disposable": True}
    result = {"dispatch_id": "d6", "transport_success": True, "resource_path": "/Game/Probe"}
    api._apply_step_result(state, step, result)
    duplicate = api._apply_step_result(state, step, result)
    assert duplicate["event"] == "DUPLICATE_RESULT_PROCESSING"
    assert len(state["created_resources"]) == 1


def _layer_d_state():
    return {"created_resources": [], "plan": {"steps": []}, "retry_count": 0, "max_retries": 2, "failed_step": None, "fix_pending": False, "retry_pending": False}


def _layer_d_validation():
    return {"step_id": "validate", "status": "pending", "phase": "VALIDATE", "parameters": {"asset_path": "/Game/Probe", "variable_name": "Marker"}, "expected_result": {"expected": "EXPECTED"}}


def test_layer_d_mismatch_creates_one_pending_fix():
    state = _layer_d_state(); step = _layer_d_validation()
    result = api._apply_step_result(state, step, {"dispatch_id": "d7", "transport_success": True, "value": "WRONG"})
    assert result["transition"] == "fix_pending" and state["fix_pending"] and not state["retry_pending"]
    fixes = [s for s in state["plan"]["steps"] if s["step_id"].startswith("fix:validate:")]
    assert len(fixes) == 1 and fixes[0]["status"] == "pending"


def test_layer_d_fix_success_schedules_retry_only():
    state = _layer_d_state(); validation = _layer_d_validation()
    api._apply_step_result(state, validation, {"dispatch_id": "d8", "transport_success": True, "value": "WRONG"})
    fix = state["plan"]["steps"][-1]
    result = api._apply_step_result(state, fix, {"dispatch_id": "d9", "transport_success": True})
    assert result["transition"] == "retry_pending" and state["retry_pending"] and not state["fix_pending"]


def test_layer_d_fix_failure_does_not_schedule_retry():
    state = _layer_d_state(); validation = _layer_d_validation()
    api._apply_step_result(state, validation, {"dispatch_id": "d10", "transport_success": True, "value": "WRONG"})
    fix = state["plan"]["steps"][-1]
    api._apply_step_result(state, fix, {"dispatch_id": "d11", "transport_success": False, "error": "failed"})
    assert not state["retry_pending"] and not state["fix_pending"] and fix["status"] == "failed"


def test_layer_d_retry_pass_clears_failure():
    state = _layer_d_state(); validation = _layer_d_validation()
    api._apply_step_result(state, validation, {"dispatch_id": "d12", "transport_success": True, "value": "WRONG"})
    fix = state["plan"]["steps"][-1]
    api._apply_step_result(state, fix, {"dispatch_id": "d13", "transport_success": True})
    result = api._apply_step_result(state, validation, {"dispatch_id": "d14", "transport_success": True, "value": "EXPECTED"})
    assert result["validation"] == "passed" and not state["retry_pending"] and state["failed_step"] is None


def test_layer_d_retry_mismatch_creates_one_next_fix():
    state = _layer_d_state(); validation = _layer_d_validation()
    api._apply_step_result(state, validation, {"dispatch_id": "d15", "transport_success": True, "value": "WRONG"})
    fix = state["plan"]["steps"][-1]
    api._apply_step_result(state, fix, {"dispatch_id": "d16", "transport_success": True})
    result = api._apply_step_result(state, validation, {"dispatch_id": "d17", "transport_success": True, "value": "WRONG"})
    assert result["transition"] == "next_fix" and state["fix_pending"]
    assert len([s for s in state["plan"]["steps"] if s["step_id"].startswith("fix:validate:")]) == 2


def test_layer_d_retry_limit_is_enforced():
    state = _layer_d_state(); state["max_retries"] = 1; validation = _layer_d_validation()
    api._apply_step_result(state, validation, {"dispatch_id": "d18", "transport_success": True, "value": "WRONG"})
    fix = state["plan"]["steps"][-1]
    api._apply_step_result(state, fix, {"dispatch_id": "d19", "transport_success": True})
    result = api._apply_step_result(state, validation, {"dispatch_id": "d20", "transport_success": True, "value": "WRONG"})
    assert result["transition"] == "retry_limit" and state["failure_evidence"]["retry_limit"]


def test_layer_d_duplicate_result_does_not_duplicate_control_transition():
    state = _layer_d_state(); validation = _layer_d_validation(); result = {"dispatch_id": "d21", "transport_success": True, "value": "WRONG"}
    api._apply_step_result(state, validation, result); duplicate = api._apply_step_result(state, validation, result)
    assert duplicate["event"] == "DUPLICATE_RESULT_PROCESSING"
    assert len(state["plan"]["steps"]) == 1


def test_layer_e_evidence_success_and_failure_preserve_cleanup():
    state = {"created_resources": [{"path": "/Game/P", "disposable": True, "verified_clean": False}]}
    success = {"dispatch_id": "e1", "transport_success": True, "raw_result": {"path": "shot.png"}}
    assert api._apply_step_result(state, {"step_id": "evidence", "phase": "EVIDENCE", "status": "pending"}, success)["evidence"] == "captured"
    failure = {"dispatch_id": "e2", "transport_success": False, "error": "capture failed"}
    api._apply_step_result(state, {"step_id": "evidence2", "phase": "EVIDENCE", "status": "pending"}, failure)
    assert state["evidence_failure"] == "capture failed" and api._cleanup_pending(state)


def test_layer_e_cleanup_and_absence_semantics():
    state = {"created_resources": [{"path": "/Game/A", "disposable": True, "verified_clean": False}, {"path": "/Game/U", "disposable": False}]}
    assert [r["path"] for r in api._cleanup_pending(state)] == ["/Game/A"]
    assert api._resource_is_absent({"result": {"exists": False}})
    assert api._resource_is_absent({"result": {"found": False}})
    assert api._resource_is_absent({"error": "asset not found"})
    step = {"step_id": "cleanup", "phase": "CLEANUP", "status": "pending"}
    api._apply_step_result(state, step, {"dispatch_id": "e3", "transport_success": True, "resource_path": "/Game/A"})
    assert not state["created_resources"][0]["verified_clean"]
    api._apply_step_result(state, {"step_id": "verify", "phase": "VERIFY_CLEANUP", "status": "pending"}, {"dispatch_id": "e4", "transport_success": True, "resource_path": "/Game/A", "raw_result": {"found": False}})
    assert state["created_resources"][0]["verified_clean"]


def test_layer_e_cleanup_verification_failure_and_completion_gate():
    state = {"created_resources": [{"path": "/Game/A", "disposable": True, "verified_clean": False}], "validation_result": "passed", "failed_step": None, "evidence_handled": True, "fix_pending": False, "retry_pending": False, "plan": {"steps": [{"status": "completed"}]}}
    assert not api._can_complete(state)
    api._apply_step_result(state, {"step_id": "verify", "phase": "VERIFY_CLEANUP", "status": "pending"}, {"dispatch_id": "e5", "transport_success": True, "resource_path": "/Game/A", "raw_result": {"exists": True}})
    assert state["cleanup_failure"]
    state["cleanup_failure"] = None; state["created_resources"][0]["verified_clean"] = True
    assert api._can_complete(state)


def test_layer_e_duplicate_does_not_double_apply_evidence():
    state = {}; step = {"step_id": "evidence", "phase": "EVIDENCE", "status": "pending"}; result = {"dispatch_id": "e6", "transport_success": True, "raw_result": {"path": "a"}}
    api._apply_step_result(state, step, result); duplicate = api._apply_step_result(state, step, result)
    assert duplicate["event"] == "DUPLICATE_RESULT_PROCESSING" and state["evidence_result"] == {"path": "a"}


def test_dispatch_missing_schema_args_returns_data_failure_without_execution():
    with patch.object(api, 'create_execution_plan', return_value={}):
        s = api.new_execution('create disposable blueprint')
    step = {'step_id': 'bad', 'phase': 'EDIT', 'preferred_tool': 'create_blueprint', 'parameters': {}, 'allowed_tools': ['create_blueprint'], 'status': 'pending', 'disposable': True}
    with patch.object(api, 'call_tool_hard_timeout') as runner:
        result = api._deterministic_step_dispatch(s, step)
    assert result is not None
    assert result['transport_success'] is False
    runner.assert_not_called()
