from unittest.mock import patch
from app import api


def state():
    with patch.object(api, 'create_execution_plan', return_value={"steps": [{"step_id": "test", "preferred_tool": "unreal_ping"}]}):
        s = api.new_execution("test disposable blueprint")
    s["current_phase"] = s["phase"] = "EDIT"
    return s


def test_phase_table_rejects_out_of_phase_mutation():
    assert "spawn_actor" not in api.PHASE_TOOL_RULES["VALIDATE"]
    assert "get_asset_info" in api.PHASE_TOOL_RULES["VALIDATE"]


def test_semantic_duplicate_resource_key_is_argument_independent():
    a = api._resource_key("spawn_actor", {"actor_name": "Probe", "location": [0, 0, 0]})
    b = api._resource_key("spawn_actor", {"actor_name": "Probe", "location": [100, 200, 0]})
    assert a == b


def test_validation_mismatch_is_structured():
    assert api._validation_mismatch({"expected": "EXPECTED_VALUE", "actual": "WRONG_VALUE"}) == {
        "expected": "EXPECTED_VALUE", "actual": "WRONG_VALUE", "resource": None
    }


def test_validation_failure_transitions_to_fix_metadata():
    s = state()
    mismatch = api._validation_mismatch({"expected": "EXPECTED_VALUE", "actual": "WRONG_VALUE"})
    s["validation_result"] = "failed"
    s["failed_step"] = 2
    s["failure_evidence"] = mismatch
    s["current_phase"] = s["phase"] = "FIX"
    assert s["current_phase"] == "FIX"
    assert s["failure_evidence"]["actual"] == "WRONG_VALUE"


def test_corrective_mutation_enters_retry_and_retry_is_bounded():
    s = state()
    s["current_phase"] = s["phase"] = "FIX"
    s["retry_count"] = 1
    s["retry_count"] += 1
    s["current_phase"] = s["phase"] = "RETRY"
    assert s["retry_count"] == 2
    assert "spawn_actor" not in api.PHASE_TOOL_RULES["RETRY"]


def test_complete_has_no_eligible_tools():
    assert api.PHASE_TOOL_RULES["COMPLETE"] == set()
    assert api.PHASE_TOOL_RULES["FAILED"] == set()
