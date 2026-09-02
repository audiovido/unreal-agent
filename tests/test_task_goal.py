import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import task_goal
from app import api


@pytest.fixture()
def isolated_goal(tmp_path, monkeypatch):
    monkeypatch.setattr(task_goal, "TASK_GOAL_FILE", tmp_path / "task_goal.json")
    return tmp_path / "task_goal.json"


def long_request():
    return (
        "Build the AvaLive feature with avatar, environment, lighting, camera, "
        "chat UI, text input, Send, Enter-to-send, real local Ollama response, "
        "Thinking/Online state, animation, save, runtime validation, reopen "
        "verification, and final screenshot."
    )


def test_long_request_preserves_original_goal_and_pending_criteria(isolated_goal):
    goal = task_goal.build_acceptance_contract(long_request())
    task_goal.save_task_goal(goal)
    restored = task_goal.load_task_goal()
    assert restored["original_user_request"] == long_request()
    assert restored["pending_criteria"]
    assert restored["continuation_state"]["milestones"]


def test_inspect_ping_cannot_complete_build_request(isolated_goal):
    goal = task_goal.build_acceptance_contract(long_request())
    state = {"task_goal": goal, "plan": {"steps": [
        {"step_id": "i", "status": "completed", "phase": "INSPECT"},
        {"step_id": "p", "status": "completed", "phase": "INSPECT"},
    ]}, "validation_result": "passed"}
    assert api._can_complete(state) is False
    assert api._completion_blocker(state)["detail"] == "PENDING_ACCEPTANCE_CRITERIA"


def test_verified_steps_advance_milestone_and_parent_goal(isolated_goal):
    goal = task_goal.build_acceptance_contract(
        "Create a test scene with a cube named GOAL_TEST, add a light, save the level, verify both exist, capture a screenshot."
    )
    goal = task_goal.reconcile_step(goal, {"preferred_tool": "spawn_actor", "parameters": {"actor_name": "GOAL_TEST", "class_name": "StaticMeshActor"}}, {"ok": True, "result": {"ok": True, "label": "GOAL_TEST"}})
    goal = task_goal.reconcile_step(goal, {"preferred_tool": "spawn_actor", "parameters": {"actor_name": "GOAL_TEST_LIGHT", "class_name": "PointLight"}}, {"ok": True, "result": {"ok": True, "label": "GOAL_TEST_LIGHT"}})
    assert "actor:GOAL_TEST:exists" in goal["completed_criteria"]
    assert "light:exists" in goal["completed_criteria"]
    assert goal["pending_criteria"]
    task_goal.save_task_goal(goal)
    assert task_goal.load_task_goal()["original_user_request"].startswith("Create a test scene")


def test_restart_preserves_pending_acceptance_criteria(isolated_goal):
    goal = task_goal.build_acceptance_contract(long_request())
    task_goal.save_task_goal(goal)
    # Simulated process restart: only durable file is reloaded.
    restored = task_goal.load_task_goal()
    assert restored["pending_criteria"] == goal["pending_criteria"]
    assert restored["original_user_request"] == goal["original_user_request"]


def test_complete_forbidden_until_all_mandatory_criteria_verified(isolated_goal):
    goal = task_goal.build_acceptance_contract("Create a cube named X, save, verify, and capture a screenshot.")
    state = {"task_goal": goal, "plan": {"steps": []}, "validation_result": "passed"}
    assert api._terminal_verdict(state)[0] == "RUNNING"
    for criterion in list(goal["pending_criteria"]):
        goal = task_goal.update_task_goal(goal, completed=[criterion])
    state["task_goal"] = goal
    state["validation_result"] = "passed"
    assert api._can_complete(state) is True


def test_optional_criteria_do_not_block_completion(isolated_goal):
    goal = task_goal.build_acceptance_contract("Create a cube named X, save, verify, and capture a screenshot. Optional nice to have polish.")
    goal["optional_criteria"].append("polish")
    for criterion in list(goal["pending_criteria"]):
        goal = task_goal.update_task_goal(goal, completed=[criterion])
    assert task_goal.contract_complete(goal) is True


def test_no_prompt_needed_between_milestones(isolated_goal):
    goal = task_goal.build_acceptance_contract(long_request())
    assert len(goal["continuation_state"]["milestones"]) >= 2
    goal = task_goal.update_task_goal(goal, milestone=1, status="active")
    assert goal["continuation_state"]["next_milestone"] == 2


def test_evidence_criterion_clears_with_outer_ok_envelope(isolated_goal):
    """Regression: a successful tool envelope shaped {"ok": True, "result": {...}}
    must clear its parent acceptance criterion. Previously reconcile_step
    required the ok flag nested inside result, so capture evidence left
    viewport:captured pending and the completion gate ended the task STALLED.
    """
    goal = task_goal.build_acceptance_contract(
        "Create a cube named R1, save, verify, and capture a screenshot of the scene."
    )
    goal = task_goal.reconcile_step(
        goal,
        {"preferred_tool": "spawn_actor", "parameters": {"actor_name": "R1"}},
        {"ok": True, "result": {"label": "R1"}},
    )
    goal = task_goal.reconcile_step(
        goal,
        {"preferred_tool": "save_level"},
        {"ok": True, "result": {"map": "/Game/R1"}},
    )
    goal = task_goal.reconcile_step(
        goal,
        {"preferred_tool": "get_actor", "parameters": {"actor_name": "R1"}},
        {"ok": True, "result": {"label": "R1"}},
    )
    goal = task_goal.reconcile_step(
        goal,
        {"preferred_tool": "capture_unreal_viewport"},
        {"ok": True, "result": {"path": "evidence.png"}},
    )
    assert "viewport:captured" in goal["completed_criteria"]
    assert task_goal.contract_complete(goal) is True


def test_failed_envelope_does_not_clear_any_criterion(isolated_goal):
    goal = task_goal.build_acceptance_contract(
        "Create a cube named R2, then capture a screenshot."
    )
    before = list(goal["pending_criteria"])
    goal = task_goal.reconcile_step(
        goal,
        {"preferred_tool": "capture_unreal_viewport"},
        {"ok": False, "error": "bridge down"},
    )
    assert goal["pending_criteria"] == before
    assert "viewport:captured" not in goal["completed_criteria"]


def test_reopen_criterion_is_satisfiable_via_open_map(isolated_goal):
    """Regression: a task mentioning reopen adds deliverable:reopen, which must
    be satisfiable by a real open_map step. Previously the criterion was
    unreachable, so every successful reopen task ended STALLED at
    PENDING_ACCEPTANCE_CRITERIA.
    """
    goal = task_goal.build_acceptance_contract(
        "Create a cube named R4, save the level, then close and reopen the project to confirm persistence."
    )
    assert "deliverable:reopen" in goal["acceptance_criteria"]
    goal = task_goal.reconcile_step(goal, {"preferred_tool": "spawn_actor", "parameters": {"actor_name": "R4"}}, {"ok": True, "result": {"label": "R4"}})
    goal = task_goal.reconcile_step(goal, {"preferred_tool": "get_actor", "parameters": {"actor_name": "R4"}}, {"ok": True, "result": {"label": "R4"}})
    goal = task_goal.reconcile_step(goal, {"preferred_tool": "save_level"}, {"ok": True, "result": {"map": "/Game/Maps/X"}})
    # before open_map, the contract must not be complete
    assert not task_goal.contract_complete(goal)
    goal = task_goal.reconcile_step(goal, {"preferred_tool": "open_map"}, {"ok": True, "result": {"level_path": "/Game/Maps/X", "world_path": "/Game/Maps/X.X", "identity_ok": True}})
    assert "deliverable:reopen" in goal["completed_criteria"]
    assert task_goal.contract_complete(goal) is True


def test_open_map_failure_does_not_complete_reopen_criterion(isolated_goal):
    goal = task_goal.build_acceptance_contract("Reopen the map to verify it persists.")
    goal = task_goal.reconcile_step(goal, {"preferred_tool": "open_map"}, {"ok": False, "error": "bridge down"})
    assert "deliverable:reopen" not in goal["completed_criteria"]
    assert not task_goal.contract_complete(goal)


def test_scene_deliverables_are_satisfiable_by_real_spawns(isolated_goal):
    """Regression: deliverable:environment/lighting/camera were unsatisfiable,
    so every long scene build stalled at PENDING_ACCEPTANCE_CRITERIA after all
    steps succeeded. Each must clear via the concrete actor class that proves it.
    """
    goal = task_goal.build_acceptance_contract(
        "Build a small polished scene with environment geometry, lighting, a camera, "
        "save the map, and capture a final screenshot."
    )
    assert "deliverable:environment" in goal["acceptance_criteria"]
    assert "deliverable:lighting" in goal["acceptance_criteria"]
    assert "deliverable:camera" in goal["acceptance_criteria"]
    goal = task_goal.reconcile_step(goal, {"preferred_tool": "spawn_actor", "parameters": {"actor_name": "Floor", "class_name": "StaticMeshActor"}}, {"ok": True, "result": {"label": "Floor"}})
    assert "deliverable:environment" in goal["completed_criteria"]
    goal = task_goal.reconcile_step(goal, {"preferred_tool": "spawn_actor", "parameters": {"actor_name": "L", "class_name": "PointLight"}}, {"ok": True, "result": {"label": "L"}})
    assert "deliverable:lighting" in goal["completed_criteria"]
    goal = task_goal.reconcile_step(goal, {"preferred_tool": "spawn_actor", "parameters": {"actor_name": "Cam", "class_name": "CameraActor"}}, {"ok": True, "result": {"label": "Cam"}})
    assert "deliverable:camera" in goal["completed_criteria"]
    goal = task_goal.reconcile_step(goal, {"preferred_tool": "save_level"}, {"ok": True, "result": {"map": "/Game/Maps/X"}})
    goal = task_goal.reconcile_step(goal, {"preferred_tool": "capture_unreal_viewport"}, {"ok": True, "result": {"path": "x.png"}})
    assert task_goal.contract_complete(goal) is True


def test_camera_deliverable_not_completed_by_marker_cube(isolated_goal):
    goal = task_goal.build_acceptance_contract("Build a scene with a camera and a cube named C1; save; capture proof.")
    goal = task_goal.reconcile_step(goal, {"preferred_tool": "spawn_actor", "parameters": {"actor_name": "C1", "class_name": "StaticMeshActor"}}, {"ok": True, "result": {"label": "C1"}})
    assert "deliverable:camera" not in goal["completed_criteria"]


# ============================================================
# READ-ONLY INSPECTION — regression: a pure inspection/query
# goal must complete from inspection evidence instead of dying
# with STALL_NO_PROGRESS / PENDING_ACCEPTANCE_CRITERIA.
# ============================================================

READ_ONLY_REQUEST = (
    "Inspect the current Unreal project read-only. Report the current level "
    "name, whether PIE is running, and the main actors present. "
    "Do not modify anything."
)


def test_read_only_inspection_contract_uses_inspection_criterion(isolated_goal):
    goal = task_goal.build_acceptance_contract(READ_ONLY_REQUEST)
    assert "inspection:result" in goal["acceptance_criteria"]
    assert "task:original_goal_complete" not in goal["acceptance_criteria"]


def test_read_only_inspection_goal_completes_from_inspection_evidence(isolated_goal):
    goal = task_goal.build_acceptance_contract(READ_ONLY_REQUEST)
    # tool executes -> useful result exists
    goal = task_goal.reconcile_step(
        goal,
        {"preferred_tool": "inspect_project"},
        {"ok": True, "result": {"uproject": {"EngineAssociation": "5.8"}}},
    )
    goal = task_goal.reconcile_step(
        goal,
        {"preferred_tool": "unreal_ping"},
        {"ok": True, "result": {"ok": True, "engine": "5.8.2"}},
    )
    assert "inspection:result" in goal["completed_criteria"]
    assert task_goal.contract_complete(goal) is True
    # terminal verdict is COMPLETE, not STALL_NO_PROGRESS
    state = {
        "task_goal": goal,
        "plan": {"steps": [
            {"step_id": "inspect_project", "status": "completed", "phase": "INSPECT"},
            {"step_id": "ping", "status": "completed", "phase": "INSPECT"},
        ]},
        "validation_result": "passed",
    }
    assert api._terminal_verdict(state)[0] == "COMPLETE"
    assert api._completion_blocker(state) is None


def test_failed_inspection_does_not_clear_inspection_criterion(isolated_goal):
    goal = task_goal.build_acceptance_contract(READ_ONLY_REQUEST)
    before = list(goal["pending_criteria"])
    goal = task_goal.reconcile_step(
        goal,
        {"preferred_tool": "inspect_project"},
        {"ok": False, "error": "bridge down"},
    )
    assert goal["pending_criteria"] == before
    assert task_goal.contract_complete(goal) is False


def test_vague_no_criteria_request_keeps_catchall_gate(isolated_goal):
    """Write-task gate is NOT weakened: vague no-criteria requests still carry
    the unsatisfiable catch-all and cannot complete from health checks."""
    goal = task_goal.build_acceptance_contract(
        "Make the project feel more complete and polished."
    )
    assert "task:original_goal_complete" in goal["acceptance_criteria"]
    assert "inspection:result" not in goal["acceptance_criteria"]
    state = {
        "task_goal": goal,
        "plan": {"steps": [
            {"step_id": "inspect_project", "status": "completed", "phase": "INSPECT"},
            {"step_id": "ping", "status": "completed", "phase": "INSPECT"},
        ]},
        "validation_result": "passed",
    }
    # Health checks alone can never finish it: the catch-all stays pending and
    # the completion gate reports PENDING_ACCEPTANCE_CRITERIA (which the
    # finalizer maps to EXECUTION_STALLED / STALL_NO_PROGRESS).
    blocker = api._completion_blocker(state)
    assert blocker is not None
    assert blocker["detail"] == "PENDING_ACCEPTANCE_CRITERIA"
    assert api._terminal_verdict(state)[0] == "RUNNING"


def test_mutation_request_is_never_treated_as_read_only(isolated_goal):
    """A query-phrased request with mutation intent must NOT be treated as
    read-only: it keeps the catch-all gate so it cannot complete from
    inspection evidence alone."""
    goal = task_goal.build_acceptance_contract(
        "Inspect the project, then make it look more futuristic."
    )
    assert "task:original_goal_complete" in goal["acceptance_criteria"]
    assert "inspection:result" not in goal["acceptance_criteria"]


def test_concrete_criteria_are_never_replaced_by_read_only_path(isolated_goal):
    """Requests that parse concrete criteria keep them: the read-only path
    only ever kicks in when nothing else was parsed, so real write goals are
    never downgraded to an inspection-only contract."""
    goal = task_goal.build_acceptance_contract(
        "Inspect the project, then add a cube named Z1 and save the level."
    )
    assert "actor:Z1:exists" in goal["acceptance_criteria"]
    assert "level:saved" in goal["acceptance_criteria"]
    assert "inspection:result" not in goal["acceptance_criteria"]
