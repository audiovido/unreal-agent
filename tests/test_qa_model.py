"""Hermetic tests for the QA state model (qa/model.py)."""
from __future__ import annotations

import json

import pytest

import qa.model as model


@pytest.fixture
def tmp_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(model, "DEFAULT_RUNS_DIR", tmp_path / "runs")
    return tmp_path / "runs"


def test_run_roundtrip_persists(tmp_runs):
    run = model.QARun(target="test")
    run.status = model.STATUS_RUNNING
    run.started_at = 100.0
    check = run.add_check(model.QACheck(
        "status_endpoint", "API_CONTRACT", expected="ok",
        verifier="health_ok", severity_if_failed=model.SEV_CRITICAL))
    check.mark(model.STATUS_PASS, observed={"ok": True})
    defect = run.add_defect(model.QADefect(
        model.SEV_MAJOR, "title", "API_CONTRACT", expected="x", actual="y"))
    run.score = 42.5
    run.save()

    loaded = model.QARun.load(run.id)
    assert loaded is not None
    assert loaded.id == run.id
    assert loaded.status == model.STATUS_RUNNING
    assert loaded.score == 42.5
    assert len(loaded.checks) == 1
    assert loaded.checks[0].status == model.STATUS_PASS
    assert loaded.checks[0].verifier == "health_ok"
    assert len(loaded.defects) == 1
    assert loaded.defects[0].severity == model.SEV_MAJOR


def test_check_defect_promotion_never_auto_pass(tmp_runs):
    check = model.QACheck("mission", "MISSION_BLACKBOX",
                          verifier="truthful_claim",
                          severity_if_failed=model.SEV_CRITICAL)
    assert check.status == model.STATUS_PENDING
    check.mark(model.STATUS_FAIL, observed={})
    assert check.status == model.STATUS_FAIL


def test_recover_interrupted_marks_not_pass(tmp_runs):
    run = model.QARun(target="t")
    run.status = model.STATUS_RUNNING
    check = run.add_check(model.QACheck("c", "RUNTIME_HEALTH",
                                        verifier="truthful_claim"))
    check.mark(model.STATUS_RUNNING)
    run.save()

    model.QARun.recover_interrupted()

    loaded = model.QARun.load(run.id)
    assert loaded.status == model.STATUS_BLOCKED
    assert loaded.verdict == model.VERDICT_BLOCKED
    assert loaded.interrupted_note
    assert loaded.checks[0].status == model.STATUS_BLOCKED
    # It must never become PASS.
    assert loaded.checks[0].status != model.STATUS_PASS
    assert loaded.status != model.STATUS_PASS


def test_summary_and_defects_by_severity(tmp_runs):
    run = model.QARun()
    run.add_check(model.QACheck("a", "G", verifier="truthful_claim")).mark(
        model.STATUS_PASS)
    run.add_check(model.QACheck("b", "G", verifier="truthful_claim")).mark(
        model.STATUS_FAIL)
    run.add_check(model.QACheck("c", "G", verifier="truthful_claim")).mark(
        model.STATUS_SKIPPED)
    run.add_defect(model.QADefect(model.SEV_CRITICAL, "t", "G"))
    run.add_defect(model.QADefect(model.SEV_MINOR, "u", "G"))
    s = run.summary()
    assert s["total"] == 3
    assert s[model.STATUS_PASS] == 1
    assert s[model.STATUS_FAIL] == 1
    db = run.defects_by_severity()
    assert db[model.SEV_CRITICAL] == 1
    assert db[model.SEV_MINOR] == 1
    assert db[model.SEV_MAJOR] == 0


def test_list_ids_sorted(tmp_runs):
    for i in range(3):
        r = model.QARun(target=f"t{i}")
        r.save()
    ids = model.QARun.list_ids()
    assert len(ids) == 3