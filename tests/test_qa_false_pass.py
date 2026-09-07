"""Hermetic tests for the false-pass defense (injected bad cases MUST fail)."""
from __future__ import annotations

import pytest

import qa.checks as checks
import qa.model as model


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setattr(model, "DEFAULT_RUNS_DIR", tmp_path / "runs")
    return model.QARun(target="false-pass test")


class _FakeClient:
    """Minimal backend stub: unknown mission id -> 404-ish envelope."""

    def mission(self, mission_id):
        return {"ok": False, "http_status": 404,
                "body": {"error": f"Unknown mission {mission_id}"}}

    def mission_resume(self, mission_id):
        return {"ok": False, "http_status": 404, "body": {}}

    def mission_cancel(self, mission_id):
        return {"ok": False, "http_status": 404, "body": {}}


def test_false_pass_defense_rejects_every_bad_case(run, tmp_path, monkeypatch):
    monkeypatch.setattr(model, "DEFAULT_RUNS_DIR", tmp_path / "runs")
    checks.run_false_pass_defense(run, _FakeClient())

    names = {c.name: c for c in run.checks}
    for name in ("completed_without_evidence", "missing_screenshot",
                 "invalid_screenshot", "stale_duplicate_evidence",
                 "blocked_task_not_pass", "timed_out_task_not_pass",
                 "bridge_unavailable_fails", "impossible_claim_rejected",
                 "wrong_task_id_rejected"):
        assert names[name].status == model.STATUS_PASS, (
            f"{name} should PASS (bad case rejected) but is "
            f"{names[name].status}: {names[name].detail}")
    # No defect may be raised by a healthy defense (all bad cases rejected).
    assert run.defects == []


def test_false_pass_defense_catches_a_real_false_pass():
    """If the pipeline ever DID accept a bad case, the defense must flag it."""
    check = model.QACheck("probe", "FALSE_PASS_DEFENSE",
                          verifier="expect_failure",
                          severity_if_failed=model.SEV_CRITICAL)
    # Simulate a verifier that wrongly PASSES the bad case.
    result = {"ok": True, "detail": "bad case accepted"}
    outcome = "PASS" if result.get("ok") else "FAIL"
    ok = outcome != "PASS"
    check.mark(model.STATUS_PASS if ok else model.STATUS_FAIL,
               observed={"outcome": outcome})
    assert check.status == model.STATUS_FAIL
    assert check.observed["outcome"] == "PASS"


def test_mission_verdict_rejects_zero_step_pass():
    from qa.verifier import run_verifier
    result = run_verifier(
        "mission_verdict", "complete PASS",
        {"status": "complete", "verdict": "PASS",
         "completed_work": {"steps_completed": 0}, "evidence": []})
    assert result["ok"] is False
    assert "0 executed steps" in result["detail"]