from __future__ import annotations

from types import SimpleNamespace

from app import api
from core.release_director import release_accept
from core.task_goal import build_acceptance_contract


def _state(*, required, evaluated=False, verified=False, defects=None):
    return {
        "id": "environment-task",
        "task": "vehicle showcase",
        "state": "RUNNING",
        "final_verdict": None,
        "task_goal": None,
        "plan": {"steps": []},
        "validation_result": "passed",
        "evidence_handled": True,
        "environment_required": required,
        "environment_criterion": "deliverable:environment" if required else None,
        "environment_evaluated": evaluated,
        "environment_verified": verified,
        "environment_status": (
            "required/verified" if verified else
            "required/not_verified" if evaluated and required else
            "required/unevaluated" if required else "advisory"
        ),
        "visual_profile": "vehicle_showcase",
        "visual_score_measured": 9.1,
        "visual_floor": 8.5,
        "visual_self_fix": {
            "passes": [{"defects": list(defects or [])}],
            "final": {"metrics": {"subject_bbox": [558, 73, 1515, 697], "subject_coverage": 0.4075}},
        },
        "visual_proof": [],
    }


def test_environment_requirement_is_derived_from_acceptance_contract():
    assert build_acceptance_contract("Showcase a vehicle")['environment_required'] is False
    required = build_acceptance_contract(
        "Showcase a vehicle in an explicit garage environment with architectural background"
    )
    assert required["environment_required"] is True
    assert required["environment_criterion"] == "deliverable:environment"
    assert required["pending_criteria"] == ["deliverable:environment"]


def test_empty_environment_blocks_required_task():
    blocker = api._completion_blocker(_state(required=True, evaluated=True, verified=False, defects=["EMPTY_ENVIRONMENT"]))
    assert blocker["code"] == "FAILED"
    assert blocker["detail"] == "REQUIRED_ENVIRONMENT_NOT_VERIFIED"


def test_verified_environment_allows_required_task_when_other_gate_passes():
    assert api._completion_blocker(_state(required=True, evaluated=True, verified=True)) is None


def test_empty_environment_is_advisory_without_environment_request():
    assert api._completion_blocker(_state(required=False, defects=["EMPTY_ENVIRONMENT"])) is None
    metrics = SimpleNamespace(
        ok=True, issues=["EMPTY_ENVIRONMENT"], head_clipped=False, stale=False,
        bands=[], roll_deg=0.0, subject_bbox=[558, 73, 1515, 697], subject_coverage=0.4075,
        ui_bbox=None,
    )
    score = SimpleNamespace(overall=9.1)
    assert release_accept(metrics, score, environment_required=False) is True


def test_verified_structured_environment_overrides_image_empty_heuristic():
    metrics = SimpleNamespace(
        ok=True, issues=["EMPTY_ENVIRONMENT"], head_clipped=False, stale=False,
        bands=[], roll_deg=0.0, subject_bbox=[558, 73, 1515, 697], subject_coverage=0.4075,
        ui_bbox=None,
    )
    assert release_accept(
        metrics, SimpleNamespace(overall=9.1),
        environment_required=True,
        environment_verified=True,
    ) is True


def test_required_environment_unevaluated_blocks_completion():
    blocker = api._completion_blocker(_state(required=True, evaluated=False, verified=False))
    assert blocker["code"] == "BLOCKED"
    assert blocker["detail"] == "REQUIRED_ENVIRONMENT_UNEVALUATED"


def test_execution_detail_exposes_advisory_vs_blocking_environment():
    advisory = api._execution_detail(_state(required=False, defects=["EMPTY_ENVIRONMENT"]))
    blocking = api._execution_detail(_state(required=True, evaluated=True, verified=False, defects=["EMPTY_ENVIRONMENT"]))
    assert advisory["visual"]["environment_requirement"]["status"] == "advisory"
    assert advisory["visual"]["environment_requirement"]["blocking"] is False
    assert blocking["visual"]["environment_requirement"]["status"] == "required/not_verified"
    assert blocking["visual"]["environment_requirement"]["blocking"] is True
    verified = api._execution_detail(_state(required=True, evaluated=True, verified=True, defects=["EMPTY_ENVIRONMENT"]))
    assert verified["visual"]["environment_requirement"]["blocking"] is False
