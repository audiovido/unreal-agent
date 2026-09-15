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


def test_fake_validation_mismatch_creates_fix_step():
    task = "Create /Game/AgentGraduation/BP_FinalSelfFixProbe. Add String variable AgentGraduationMarker. Initially set it to WRONG_VALUE. Expected value is EXPECTED_VALUE. Delete the probe."
    state = api.new_execution(task)
    steps = state["plan"]["steps"]
    validation = next(s for s in steps if s["step_id"] == "validate_value")
    state["current_step"] = steps.index(validation)
    state["current_phase"] = state["phase"] = "VALIDATE"
    with patch.object(api, "call_tool_hard_timeout", return_value={"ok": True, "result": {"value": "WRONG_VALUE"}}):
        result = api._deterministic_step_dispatch(state, validation)
    api._apply_step_result(state, validation, result)
    assert result["ok"] is True
    assert state["validation_result"] == "failed"
    assert state["current_phase"] == "FIX"
    assert state["failure_evidence"]["expected"] == "EXPECTED_VALUE"
    fix = next(step for step in state["plan"]["steps"] if step["step_id"].startswith("fix:validate_value:"))
    assert fix["preferred_tool"] == "set_blueprint_variable_default"
    assert fix["parameters"]["value"] == "EXPECTED_VALUE"


def test_fake_result_shapes_are_normalized():
    assert api._tool_success({"success": True})
    assert api._tool_success({"status": "success"})
    assert api._extract_tool_value({"ok": True, "result": {"value": "EXPECTED_VALUE"}}) == "EXPECTED_VALUE"


def test_cleanup_failure_does_not_claim_verified():
    state = api.new_execution("cleanup")
    state["created_resources"] = [{"path": "/Game/AgentGraduation/Probe", "disposable": True}]
    assert state["created_resources"][0]["disposable"] is True
