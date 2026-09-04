"""Hermetic unit tests for scripts/live_ui_detector_graduation.py helpers.

The live probe itself requires a running Unreal Editor bridge, so only its
pure helper logic is exercised here (no bridge, no editor, no network):

  * ``check()`` PASS/FAIL/BLOCKED result accounting,
  * ``payload()`` nested bridge-result extraction,
  * ``build_evidence()`` verdict rules (PASS only when nothing FAILed;
    BLOCKED sub-checks are recorded, never failures) and the evidence JSON
    shape written for the graduation report.

Module import is side-effect free: the probe instantiates its bridge only
inside ``main()``, which pytest never runs.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "live_ui_detector_graduation",
    ROOT / "scripts" / "live_ui_detector_graduation.py")
probe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(probe)


# --------------------------------------------------------------------------
# check() accounting
# --------------------------------------------------------------------------

def test_check_records_pass_fail_blocked(capsys):
    probe.RESULTS.clear()
    probe.check("a pass", "PASS", "detail-a")
    probe.check("a fail", "FAIL", "detail-b")
    probe.check("a blocked", "BLOCKED", "detail-c")
    assert len(probe.RESULTS) == 3
    assert probe.RESULTS[0] == {"name": "a pass", "ok": True,
                                "status": "PASS", "detail": "detail-a"}
    assert probe.RESULTS[1] == {"name": "a fail", "ok": False,
                                "status": "FAIL", "detail": "detail-b"}
    assert probe.RESULTS[2] == {"name": "a blocked", "ok": False,
                                "status": "BLOCKED", "detail": "detail-c"}
    out = capsys.readouterr().out
    assert "PASS a pass" in out and "FAIL a fail" in out \
        and "BLOCKED a blocked" in out


# --------------------------------------------------------------------------
# payload() nested-result extraction
# --------------------------------------------------------------------------

def test_payload_unwraps_nested_result():
    assert probe.payload({"ok": False, "error": "x"}) == {"ok": False,
                                                          "error": "x"}
    assert probe.payload({"result": {"ok": True, "path": "/p"}}) \
        == {"ok": True, "path": "/p"}
    assert probe.payload({"result": [1, 2]}) == {"result": [1, 2]}
    assert probe.payload(None) == {}


# --------------------------------------------------------------------------
# build_evidence() verdict + evidence shape
# --------------------------------------------------------------------------

def _check(status: str) -> dict:
    return {"name": f"check-{status}", "ok": status == "PASS",
            "status": status, "detail": f"detail-{status}"}


def test_build_evidence_all_pass_verdict():
    verdict, evidence = probe.build_evidence(
        [_check("PASS"), _check("PASS")],
        session={"project": "P", "map": "M", "engine": "5.8.2"},
        widget_asset="/Game/ReleaseMissions/W",
        evidence_paths={"frame": "/ev/frame.png"})
    assert verdict == "PASS"
    assert evidence["status"] == "PASS"
    assert evidence["session"] == {"project": "P", "map": "M",
                                   "engine": "5.8.2"}
    assert evidence["widget_asset"] == "/Game/ReleaseMissions/W"
    assert evidence["evidence"] == {"frame": "/ev/frame.png"}
    assert evidence["blocked_notes"] == []


def test_build_evidence_blocked_subcheck_keeps_pass():
    """A BLOCKED sub-check is recorded but must never fail the verdict."""
    verdict, evidence = probe.build_evidence(
        [_check("PASS"), _check("BLOCKED")],
        session={}, widget_asset="W", evidence_paths={})
    assert verdict == "PASS"
    assert len(evidence["blocked_notes"]) == 1
    assert evidence["blocked_notes"][0] == "detail-BLOCKED"
    assert [c["status"] for c in evidence["checks"]] == ["PASS", "BLOCKED"]


def test_build_evidence_any_fail_verdict():
    verdict, evidence = probe.build_evidence(
        [_check("PASS"), _check("FAIL")],
        session={}, widget_asset="W", evidence_paths={})
    assert verdict == "FAIL"
    assert evidence["status"] == "FAIL"


def test_build_evidence_serializes_to_report_json():
    """The exact dict main() writes must round-trip through json.dumps."""
    verdict, evidence = probe.build_evidence(
        [_check("PASS"), _check("BLOCKED")],
        session={"project": "ASSET_Showcase2", "map": "ShowcaseMap"},
        widget_asset="/Game/ReleaseMissions/UA",
        evidence_paths={"editor_frame": "a.png", "pie_frame": "b.png"})
    raw = json.dumps(evidence, indent=2)
    loaded = json.loads(raw)
    assert loaded["status"] == verdict
    assert set(loaded) == {"task", "status", "date", "session",
                           "widget_asset", "checks", "blocked_notes",
                           "evidence"}
    assert len(loaded["checks"]) == 2
    assert loaded["blocked_notes"] == ["detail-BLOCKED"]


def test_build_evidence_default_task_name():
    _, evidence = probe.build_evidence([_check("PASS")], session={},
                                       widget_asset="W", evidence_paths={})
    assert evidence["task"] == "AIVIDO_UI_DETECTOR_GRADUATION_LIVE"
    assert evidence["date"]
