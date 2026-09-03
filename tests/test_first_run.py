"""Hermetic tests for core/first_run.py."""
from __future__ import annotations

import json

from core import first_run


def test_progression_stage_order(tmp_path):
    proj = tmp_path / "Show.uproject"
    proj.write_text("{}", encoding="utf-8")
    snap = first_run.build_progression(
        doctor={"overall": "PASS", "summary": "3 pass", "user_error": "ok",
                "failures": [], "warnings": []},
        recent_project=str(proj),
        unreal_build={"label": "5.4", "editor_exe": "C:/UE/UE.exe"},
        file_path=None)
    stages = [s["stage"] for s in snap["progression"]]
    assert stages == first_run.STAGES
    assert snap["ready"] is True


def test_ready_false_without_project():
    snap = first_run.build_progression(
        doctor={"overall": "PASS", "summary": "ok", "user_error": "ok",
                "failures": [], "warnings": []},
        recent_project=None, unreal_build=None, file_path=None)
    assert snap["ready"] is False
    r = first_run.stage_result(snap, "ready")
    assert r["status"] == "pending"


def test_failing_doctor_blocks_environment_stage(tmp_path):
    proj = tmp_path / "Show.uproject"
    proj.write_text("{}", encoding="utf-8")
    snap = first_run.build_progression(
        doctor={"overall": "FAIL", "summary": "1 fail",
                "user_error": "Environment check failed",
                "failures": [{"name": "x"}], "warnings": []},
        recent_project=str(proj), unreal_build=None,
        file_path=None)
    stage = first_run.stage_result(snap, "environment_check")
    assert stage["status"] == "blocked"
    assert snap["ready"] is False


def test_no_unreal_build_is_a_warning_not_blocker():
    snap = first_run.build_progression(
        doctor={"overall": "WARNING", "summary": "ok",
                "user_error": "warnings", "failures": [], "warnings": ["u"]},
        recent_project="C:/p/Show.uproject", unreal_build=None,
        file_path=None)
    stage = first_run.stage_result(snap, "unreal_detected")
    assert stage["status"] == "warn"


def test_persist_and_load(tmp_path):
    target = tmp_path / "first_run.json"
    snap = first_run.build_progression(
        doctor={"overall": "PASS", "summary": "ok", "user_error": "ok",
                "failures": [], "warnings": []},
        recent_project="C:/p/Show.uproject", unreal_build=None,
        file_path=target)
    assert target.exists()
    loaded = first_run.load_snapshot(file_path=target)
    assert loaded["ready"] == snap["ready"]
    assert json.loads(target.read_text(encoding="utf-8"))["schema"] == \
        "ua.first_run.v1"


def test_load_missing_returns_empty(tmp_path, monkeypatch):
    # hermetic: point the default snapshot at a temp path so the test never
    # depends on whether a REAL first_run.json artifact exists in the repo
    from core import app_config
    monkeypatch.setattr(app_config, "FIRST_RUN_FILE", tmp_path / "first_run.json")
    snap = first_run.load_snapshot(file_path=None)
    assert snap["ready"] is False and snap["progression"] == []
