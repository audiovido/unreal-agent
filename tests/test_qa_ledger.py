"""Hermetic tests for the durable defect ledger (qa/ledger.py)."""
from __future__ import annotations

import qa.ledger as ledger
import qa.model as model


def test_ledger_merge_and_dedupe(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "LEDGER_PATH", tmp_path / "defects.json")
    d1 = model.QADefect(model.SEV_CRITICAL, "one", "API_CONTRACT",
                        defect_id="QA-AA")
    d2 = model.QADefect(model.SEV_MAJOR, "two", "RUNTIME_HEALTH",
                        defect_id="QA-BB")
    data = ledger.merge_run_defects([d1, d2], run_id="qar_1")
    assert len(data["defects"]) == 2
    assert data["counts"][model.LEDGER_OPEN] == 2

    # Same run merged again dedupes by id.
    data2 = ledger.merge_run_defects([d1], run_id="qar_1")
    assert len(data2["defects"]) == 2


def test_ledger_status_change(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "LEDGER_PATH", tmp_path / "defects.json")
    d = model.QADefect(model.SEV_CRITICAL, "x", "G", defect_id="QA-CC")
    ledger.merge_run_defects([d], run_id="qar_1")
    assert ledger.set_defect_status("QA-CC", model.LEDGER_FIXED) is True
    data = ledger.load_ledger()
    fixed = [x for x in data["defects"] if x["id"] == "QA-CC"][0]
    assert fixed["status"] == model.LEDGER_FIXED
    assert ledger.open_defects() == []


def test_ledger_never_hides_failures(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "LEDGER_PATH", tmp_path / "defects.json")
    d = model.QADefect(model.SEV_CRITICAL, "blocker", "RELEASE_SAFETY",
                       defect_id="QA-DD", blocker=True)
    data = ledger.merge_run_defects([d], run_id="qar_1")
    # The blocker is recorded OPEN; no status is auto-FIXED/VERIFIED.
    entry = [x for x in data["defects"] if x["id"] == "QA-DD"][0]
    assert entry["status"] == model.LEDGER_OPEN
    assert entry["blocker"] is True
    assert entry["severity"] == model.SEV_CRITICAL


def test_ledger_reconcile_marks_verified_when_check_passes(
        tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "LEDGER_PATH", tmp_path / "defects.json")
    d = model.QADefect(model.SEV_MAJOR, "engine version", "RUNTIME_HEALTH",
                       defect_id="QA-EE", check_name="bridge_engine_version")
    ledger.merge_run_defects([d], run_id="qar_1")
    assert ledger.load_ledger()["defects"][0]["status"] == model.LEDGER_OPEN

    # A later run proves the check passes -> the defect is VERIFIED, never
    # deleted, and history is retained.
    check = model.QACheck("bridge_engine_version", "RUNTIME_HEALTH",
                          verifier="truthful_claim")
    check.mark(model.STATUS_PASS, observed="5.8")
    data = ledger.reconcile_ledger(run_id="qar_2", checks=[check])
    entry = [x for x in data["defects"] if x["id"] == "QA-EE"][0]
    assert entry["status"] == model.LEDGER_VERIFIED
    assert entry["verified_in_run"] == "qar_2"
    assert len(data["defects"]) == 1  # retained, not deleted


def test_ledger_reconcile_keeps_still_failing_open(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "LEDGER_PATH", tmp_path / "defects.json")
    d = model.QADefect(model.SEV_MAJOR, "route broken", "UI_BLACKBOX",
                       defect_id="QA-FF", check_name="production_routes_serve")
    ledger.merge_run_defects([d], run_id="qar_1")
    check = model.QACheck("production_routes_serve", "UI_BLACKBOX",
                          verifier="truthful_claim")
    check.mark(model.STATUS_FAIL, observed="HTTP 500")
    data = ledger.reconcile_ledger(run_id="qar_2", checks=[check])
    entry = [x for x in data["defects"] if x["id"] == "QA-FF"][0]
    # Still failing in the latest run -> stays OPEN.
    assert entry["status"] == model.LEDGER_OPEN


def test_ledger_reconcile_supersedes_older_duplicate(tmp_path, monkeypatch):
    """A fresh OPEN defect for the same check retires older OPEN entries so
    the ledger keeps one OPEN per live defect (history retained)."""
    monkeypatch.setattr(ledger, "LEDGER_PATH", tmp_path / "defects.json")
    old = model.QADefect(model.SEV_MINOR, "capture phrasing",
                         "MISSION_BLACKBOX", defect_id="QA-OLD",
                         check_name="plain_capture_phrasing_routing")
    ledger.merge_run_defects([old], run_id="qar_1")
    check = model.QACheck("plain_capture_phrasing_routing",
                          "MISSION_BLACKBOX", verifier="truthful_claim")
    check.mark(model.STATUS_FAIL, observed={"step_count": 0})
    new = model.QADefect(model.SEV_MINOR, "capture phrasing (repro)",
                         "MISSION_BLACKBOX", defect_id="QA-NEW",
                         check_name="plain_capture_phrasing_routing")
    # The new run's defect is merged first, then reconciled.
    ledger.merge_run_defects([new], run_id="qar_2")
    data = ledger.reconcile_ledger(run_id="qar_2", checks=[check],
                                   current_run_defects=[new])
    by_id = {x["id"]: x for x in data["defects"]}
    assert by_id["QA-OLD"]["status"] == model.LEDGER_VERIFIED
    assert by_id["QA-OLD"].get("superseded_in_run") == "qar_2"
    assert by_id["QA-NEW"]["status"] == model.LEDGER_OPEN
    assert len(data["defects"]) == 2  # history retained, not deleted