"""Hermetic tests for the autonomous release verdict rules."""
from __future__ import annotations

import pytest

import qa.model as model
from qa.verdict import (
    GATE_GROUPS, compute_verdict, render_json_report, render_md_report,
)


def _run_with(checks, defects):
    run = model.QARun(target="verdict test")
    for spec in checks:
        name, cat, status = spec
        run.add_check(model.QACheck(name, cat, verifier="truthful_claim")
                      ).mark(status)
    for spec in defects:
        sev, title, cat = spec
        run.add_defect(model.QADefect(sev, title, cat))
    return run


def _passing_run():
    checks = [
        ("readonly_diagnostic_mission", "MISSION_BLACKBOX", model.STATUS_PASS),
        ("code_task_pipeline", "MISSION_BLACKBOX", model.STATUS_PASS),
        ("isolated_capture_mission", "MISSION_BLACKBOX", model.STATUS_PASS),
    ]
    for group in GATE_GROUPS:
        if group == "MISSION_BLACKBOX":
            continue
        checks.append((f"{group}_check", group, model.STATUS_PASS))
    run = model.QARun(target="verdict test")
    for name, cat, status in checks:
        run.add_check(model.QACheck(name, cat, verifier="truthful_claim")
                      ).mark(status)
    run.status = "COMPLETED"
    return run


def test_release_ready_when_all_gates_pass(tmp_path, monkeypatch):
    monkeypatch.setattr(model, "DEFAULT_RUNS_DIR", tmp_path / "runs")
    run = _passing_run()
    verdict = compute_verdict(run)
    assert verdict["verdict"] == model.VERDICT_RELEASE_READY
    assert verdict["ready"] is True
    assert run.verdict == model.VERDICT_RELEASE_READY


def test_critical_defect_blocks_release(tmp_path, monkeypatch):
    monkeypatch.setattr(model, "DEFAULT_RUNS_DIR", tmp_path / "runs")
    run = _passing_run()
    run.add_defect(model.QADefect(model.SEV_CRITICAL, "crit", "RUNTIME_HEALTH"))
    verdict = compute_verdict(run)
    assert verdict["verdict"] == model.VERDICT_NOT_READY
    assert any("CRITICAL" in r for r in verdict["reasons"])


def test_major_defect_blocks_release(tmp_path, monkeypatch):
    monkeypatch.setattr(model, "DEFAULT_RUNS_DIR", tmp_path / "runs")
    run = _passing_run()
    run.add_defect(model.QADefect(model.SEV_MAJOR, "maj", "API_CONTRACT"))
    verdict = compute_verdict(run)
    assert verdict["verdict"] == model.VERDICT_NOT_READY
    assert any("MAJOR" in r for r in verdict["reasons"])


def test_minor_and_warning_do_not_block(tmp_path, monkeypatch):
    monkeypatch.setattr(model, "DEFAULT_RUNS_DIR", tmp_path / "runs")
    run = _passing_run()
    run.add_defect(model.QADefect(model.SEV_MINOR, "min", "UI_BLACKBOX"))
    run.add_defect(model.QADefect(model.SEV_WARNING, "warn", "RECOVERY"))
    verdict = compute_verdict(run)
    assert verdict["verdict"] == model.VERDICT_RELEASE_READY
    assert verdict["counts"]["minor_open"] == 1
    assert verdict["counts"]["warnings"] == 1


def test_core_mission_failure_blocks_release(tmp_path, monkeypatch):
    monkeypatch.setattr(model, "DEFAULT_RUNS_DIR", tmp_path / "runs")
    run = _passing_run()
    run.check("readonly_diagnostic_mission").mark(
        model.STATUS_FAIL, detail="failed")
    verdict = compute_verdict(run)
    assert verdict["verdict"] == model.VERDICT_NOT_READY
    assert verdict["core_mission_ok"] is False


def test_false_pass_group_failure_blocks_release(tmp_path, monkeypatch):
    monkeypatch.setattr(model, "DEFAULT_RUNS_DIR", tmp_path / "runs")
    run = _passing_run()
    run.add_check(model.QACheck("bad_case", "FALSE_PASS_DEFENSE",
                                verifier="expect_failure")).mark(
        model.STATUS_FAIL)
    verdict = compute_verdict(run)
    assert verdict["verdict"] == model.VERDICT_NOT_READY
    assert verdict["gate_results"]["false-pass defense"] is False


def test_interrupted_run_blocks_release(tmp_path, monkeypatch):
    monkeypatch.setattr(model, "DEFAULT_RUNS_DIR", tmp_path / "runs")
    run = _passing_run()
    run.status = model.STATUS_BLOCKED
    verdict = compute_verdict(run)
    assert verdict["verdict"] == model.VERDICT_BLOCKED
    assert verdict["blocked"] is True


def test_reports_generated(tmp_path, monkeypatch):
    monkeypatch.setattr(model, "DEFAULT_RUNS_DIR", tmp_path / "runs")
    from qa import verdict as v
    monkeypatch.setattr(v, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(v, "REPORT_MD", tmp_path / "reports" / "r.md")
    monkeypatch.setattr(v, "REPORT_JSON", tmp_path / "reports" / "r.json")
    run = _passing_run()
    verdict = compute_verdict(run)
    md = render_md_report(run, verdict)
    js = render_json_report(run, verdict)
    assert md.exists() and "VERDICT" in md.read_text(encoding="utf-8")
    import json as _json
    payload = _json.loads(js.read_text(encoding="utf-8"))
    assert payload["verdict"] == model.VERDICT_RELEASE_READY
    assert "checks" in payload and "defects" in payload