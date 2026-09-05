"""Strict acceptance-gate regression tests for /api/action missions.

Observed bug: the Devboard marked a task DONE as soon as execution finished
and a proof screenshot existed, even when the user's explicit acceptance
criteria were not satisfied (e.g. a showcase that required a real visible
vehicle, saved level, fresh proof, visual validation AND a visual score of at
least 8.5/10 returned DONE while the measured/confirmed score was missing or
below the floor).

These tests prove the terminal-state gate in app.api:
  - execution finished + proof exists is NEVER sufficient for DONE when
    requested acceptance criteria are still pending;
  - an explicitly requested visual-score floor must be measured AND met before
    COMPLETE; a measured score below the floor is FAILED, never DONE;
  - simple tasks without a visual-score request still complete with valid
    verified evidence.
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


ACTOR = "ACCEPT_GATE_CUBE"


def _plan(with_evidence=True):
    steps = [
        {"step_id": "inspect", "phase": "INSPECT", "intent": "inspect_project",
         "preferred_tool": "inspect_project", "allowed_tools": ["inspect_project"],
         "parameters": {}, "expected_result": {}, "depends_on": [], "disposable": False,
         "status": "pending"},
        {"step_id": "spawn", "phase": "EDIT", "intent": "spawn_actor",
         "preferred_tool": "spawn_actor", "allowed_tools": ["spawn_actor"],
         "parameters": {"class_name": "StaticMeshActor", "actor_name": ACTOR,
                        "location": [0, 0, 200], "scale": [0.5, 0.5, 0.5],
                        "mesh_asset": "/Engine/BasicShapes/Cube.Cube"},
         "expected_result": {}, "depends_on": ["inspect"], "disposable": False,
         "status": "pending"},
        {"step_id": "save", "phase": "BUILD", "intent": "save_level",
         "preferred_tool": "save_level", "allowed_tools": ["save_level"],
         "parameters": {}, "expected_result": {}, "depends_on": ["spawn"],
         "disposable": False, "status": "pending"},
        {"step_id": "verify", "phase": "VALIDATE", "intent": "get_actor",
         "preferred_tool": "get_actor", "allowed_tools": ["get_actor"],
         "parameters": {"actor_name": ACTOR}, "expected_result": {"exists": True},
         "depends_on": ["save"], "disposable": False, "status": "pending"},
    ]
    if with_evidence:
        steps.append({
            "step_id": "evidence", "phase": "EVIDENCE", "intent": "capture_unreal_viewport",
            "preferred_tool": "capture_unreal_viewport", "allowed_tools": ["capture_unreal_viewport"],
            "parameters": {}, "expected_result": {}, "depends_on": ["verify"],
            "disposable": False, "status": "pending",
        })
    return {"goal": "acceptance gate", "success_criteria": [], "steps": steps}


def _state(task_text, *, visual_floor=None, evidence_score=None):
    goal = task_goal.build_acceptance_contract(task_text, api._default_project_context())
    task_goal.save_task_goal(goal)
    return {
        "id": str(uuid.uuid4()),
        "task": task_text,
        "task_goal": goal,
        "project_context": dict(api._default_project_context()),
        "phase": "PLAN", "current_phase": "PLAN", "current_step": 0, "completed_steps": [],
        "failed_step": None, "retry_count": 0, "validation_result": None,
        "created_resources": [], "processed_dispatch_ids": [],
        "fix_pending": False, "fix_step_id": None, "retry_pending": False,
        "retry_validation_step_id": None, "max_retries": 3, "max_tool_calls": 40,
        "model_messages": [], "trace": [], "failed_calls": {}, "verification_pending": False,
        "successful_calls": 0, "final_rejections": 0, "step": 0, "tool_call_count": 0,
        "state": "PLANNING", "current_action": None, "start_ts": None, "end_ts": None,
        "plan": _plan(),
        "visual_floor": visual_floor,
        "visual_score_measured": None,
        "visual_score_evidence": None,
    }


def _fake_tools(evidence_score=None):
    def fake(spec, args, timeout_seconds=60):
        name = spec.name
        if name == "inspect_project":
            return {"ok": True, "result": {"project": "ACCEPT_GATE_PROJECT"}}
        if name == "spawn_actor":
            return {"ok": True, "result": {"actor_name": args.get("actor_name"), "success": True}}
        if name == "save_level":
            return {"ok": True, "result": {"saved": True}}
        if name == "get_actor":
            return {"ok": True, "result": {"found": True, "actor_name": args.get("actor_name")}}
        if name == "capture_unreal_viewport":
            payload = {"ok": True, "result": {"path": "C:/proof/acceptance_latest.png", "visible": True}}
            if evidence_score is not None:
                payload["result"]["score"] = evidence_score
            return payload
        return {"ok": True, "result": {}}
    return fake


def _run(state, evidence_score=None):
    api.execution_state = state
    with patch.object(api, "call_tool_hard_timeout", side_effect=_fake_tools(evidence_score)):
        return api.run_execution_until_pause()


def _complete_events():
    return sum(1 for e in api.events if e.get("type") == "complete")


def _scored_request_text():
    return (
        "Create a vehicle showcase scene with a cube named " + ACTOR
        + ", save the level, verify the actor, and capture fresh proof. "
        + "Visual validation is required and the visual score must be at "
        + "least 8.5/10."
    )


def test_execution_finished_and_proof_exists_but_acceptance_fails_is_not_done():
    """Regression: finished steps + captured proof must not auto-complete when
    the parent contract still has pending acceptance criteria."""
    api.events.clear()
    state = _state(
        "Create a cube named " + ACTOR + " with a spotlight, save the level, "
        "verify it exists and capture proof."
    )
    result = _run(state, evidence_score=None)
    # Everything ran (proof captured), but the requested light was never
    # created, so the contract can never complete.
    assert state.get("evidence_handled") is True
    assert any(s.get("status") == "completed" for s in state["plan"]["steps"])
    assert state["state"] != "COMPLETE"
    assert result["terminal"] != "PASS"
    assert result["state"] != "complete"
    assert _complete_events() == 0


def test_measured_score_below_requested_floor_is_not_done():
    """Score 8.2 with a required 8.5 floor => FAILED, never DONE."""
    api.events.clear()
    state = _state(_scored_request_text(), visual_floor=8.5)
    result = _run(state, evidence_score=8.2)
    assert state["visual_score_measured"] == 8.2
    assert state["state"] == "FAILED"
    assert result["terminal"] == "FAIL"
    assert result["state"] == "failed"
    assert _complete_events() == 0


def test_measured_score_at_or_above_floor_with_verified_evidence_is_done():
    """Score 8.6 with a required 8.5 floor + all evidence verified => DONE."""
    api.events.clear()
    state = _state(_scored_request_text(), visual_floor=8.5)
    result = _run(state, evidence_score=8.6)
    assert state["visual_score_measured"] == 8.6
    assert state["state"] == "COMPLETE"
    assert result["terminal"] == "PASS"
    assert result["state"] == "complete"
    assert _complete_events() == 1


def test_scored_request_never_evaluated_is_not_done():
    """A requested visual floor with NO measured score anywhere => FAILED."""
    api.events.clear()
    state = _state(_scored_request_text(), visual_floor=8.5)
    result = _run(state, evidence_score=None)
    assert state["visual_score_measured"] is None
    assert state["state"] != "COMPLETE"
    assert result["terminal"] != "PASS"
    assert _complete_events() == 0


def test_simple_cube_task_with_valid_evidence_still_completes():
    """No visual-score request => existing simple-task completion preserved."""
    api.events.clear()
    state = _state(
        "Create one cube at 0,0,200 named " + ACTOR + ", save the level, "
        "verify it exists and capture fresh proof."
    )
    result = _run(state, evidence_score=None)
    assert state.get("visual_floor") is None
    assert state["state"] == "COMPLETE"
    assert result["terminal"] == "PASS"
    assert result["state"] == "complete"
    assert _complete_events() == 1


def test_requested_visual_floor_parser():
    assert api._requested_visual_floor(
        "Build a vehicle showcase. Visual validation score >= 8.5/10 required."
    ) == 8.5
    assert api._requested_visual_floor(
        "The final visual score must be at least 8.5 out of 10 to pass."
    ) == 8.5
    assert api._requested_visual_floor(
        "Set the scene lighting and make it look premium."
    ) is None
    assert api._requested_visual_floor(
        "Create one cube at 0,0,200, save the level and capture fresh proof."
    ) is None


def test_requested_visual_floor_mission_quality_phrasing():
    """Supervisor/mission phrasing states the floor as a quality target
    without the literal "score >= N" form; the strict gate must arm too.
    Otherwise mission-routed showcase tasks bypass visual acceptance and
    "execution finished + proof" becomes DONE with no verified score."""
    mission_text = (
        "Create a polished vehicle showcase scene in the active Unreal project.\n"
        "Requirements:\n"
        "- Use one real vehicle asset already available in the project or "
        "ready-asset library.\n"
        "- Add a suitable environment or architectural asset around it.\n"
        "- Run visual validation.\n"
        "- If visual quality is below 8.5/10, automatically improve the scene "
        "and repeat validation.\n"
        "- Mark DONE only when the scene is saved, fresh proof captured, and "
        "the visual quality score meets the 8.5/10 target."
    )
    assert api._requested_visual_floor(mission_text) == 8.5
    assert api._requested_visual_floor(
        "Visual quality score is at least 8.5/10 after validation."
    ) == 8.5
    assert api._requested_visual_floor(
        "The final review rating must reach 9/10 before completion."
    ) == 9.0
    assert api._requested_visual_floor(
        "what is the current visual score of the viewport?"
    ) is None


def test_scene_proof_scope_removes_unreachable_ui_cap(tmp_path):
    """A scene proof (no UI panel) must be measured under the scene category
    scope. Scored against the full default set, ui=2.0 + readability=2.0 cap
    every non-UI frame at <= 8.24, so an 8.5 floor is unreachable by
    construction for ANY showcase shot."""
    from PIL import Image, ImageDraw

    from app import api

    w, h = 800, 450
    img = Image.new("RGB", (w, h), (0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, w, h], fill=(205, 205, 205))
    r = int(h * 0.36)
    cx, cy = w // 2, int(h * 0.50)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(120, 120, 120))
    path = tmp_path / "scene.png"
    img.save(str(path))

    unscoped = api._measure_proof_score(str(path), None)
    scoped = api._measure_proof_score(str(path), api.SCENE_VISUAL_CATEGORIES)
    assert unscoped is not None and scoped is not None
    # No UI: ui and readability are fixed at 2.0, capping the weighted mean.
    assert unscoped <= 8.24 + 1e-6
    # Scoped to the scene categories the frame can actually earn, the same
    # proof scores higher and the 8.5 floor becomes reachable.
    assert scoped > unscoped
    assert set(api.SCENE_VISUAL_CATEGORIES).isdisjoint({"ui", "readability"})


def test_no_visual_floor_never_blocks_simple_completion():
    goal = task_goal.build_acceptance_contract(
        "Create a cube named " + ACTOR + ", save, verify and capture proof."
    )
    state = {
        "task_goal": goal,
        "plan": {"steps": []},
        "validation_result": "passed",
        "evidence_handled": True,
        "visual_floor": None,
    }
    for criterion in list(goal["pending_criteria"]):
        goal = task_goal.update_task_goal(goal, completed=[criterion])
    state["task_goal"] = goal
    assert api._completion_blocker(state) is None
