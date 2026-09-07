"""Hermetic end-to-end run of the full 10-group matrix against stub
backend + bridge. Proves the runner, checks, ledger and verdict all work
together and that a clean environment yields RELEASE_READY without any
live Unreal/backend access."""
from __future__ import annotations

import json
import threading

import pytest

import qa.checks as checks_mod
import qa.model as model
import qa.runner as runner


class FakeBridge:
    def ping(self):
        return {"ok": True}

    def identity(self):
        return {"ok": True, "project_name": "ASSET_Showcase2",
                "engine": "5.8.2-56702186+++UE5+Release-5.8",
                "world": "/Game/Maps/AividoHQ.AividoHQ", "port": 6766}

    def current_level(self):
        return {"ok": True, "result": {
            "world_path": "/Game/Maps/AividoHQ.AividoHQ"}}

    def actor_names(self):
        cast = [f"AVIDO_Human_{role}" for role in
                ("Animation", "Audio", "Creative", "Lighting", "Master",
                 "Technical", "VFX", "Visual")]
        actors = [{"name": f"StaticMeshActor_{i}",
                   "label": (cast.pop(0) if i < 8 else f"AVIDO_Prop_{i}"),
                   "class": "StaticMeshActor"} for i in range(166)]
        return {"ok": True, "actors": actors, "count": 166}


class FakeBackend:
    _missions = {}

    def request(self, method, path, payload=None, timeout=None):
        if "mission_does_not_exist" in path or "nonexistent" in path:
            return {"ok": True, "http_status": 404, "latency_ms": 1,
                    "body": {"error": "not found"}}
        if method == "POST" and "/async" in path:
            if payload == {"prompt": ""}:
                return {"ok": True, "http_status": 422, "latency_ms": 1,
                        "body": {"error": "prompt cannot be empty"}}
            mid = f"mission_fake_{len(self._missions) + 1}"
            self._missions[mid] = {"status": "executing", "verdict": None,
                                   "mission_id": mid}
            return {"ok": True, "http_status": 200, "latency_ms": 1,
                    "body": {"ok": True, "mission_id": mid,
                              "status": "accepted"}}
        return {"ok": True, "http_status": 200, "latency_ms": 1,
                "body": {"ok": True,
                          "raw": "<html><body>Aivido</body></html>"}}

    def status(self):
        return {"ok": True, "http_status": 200, "latency_ms": 12,
                "body": {"ok": True, "unreal": {"ok": True},
                         "ollama": {"ok": True}}}

    def doctor(self):
        return {"ok": True, "http_status": 200,
                "body": {"overall": "PASS", "summary": {"PASS": 5, "WARN": 0,
                                                        "FAIL": 0},
                         "checks": [], "generated_at": 0.0}}

    def start_mission(self, prompt, **kwargs):
        mid = f"mission_fake_{len(self._missions) + 1}"
        ev = {"path": str(_EV_DIR / f"{mid}.json"), "kind": "diagnostic"}
        _EV_DIR.mkdir(parents=True, exist_ok=True)
        (_EV_DIR / f"{mid}.json").write_text("{}", encoding="utf-8")
        self._missions[mid] = {
            "status": "complete", "verdict": "PASS",
            "completed_work": {"steps_completed": 3},
            "evidence": [ev], "mission_id": mid,
            "plan": {"steps": [{"preferred_tool": "capture_unreal_viewport"}],
                     "phases": [{"phase": "EVIDENCE"}]}}
        return {"ok": True, "http_status": 200,
                "body": {"ok": True, "mission_id": mid, "status": "accepted"}}

    def mission(self, mission_id):
        if mission_id in self._missions:
            return {"ok": True, "http_status": 200,
                    "body": self._missions[mission_id]}
        return {"ok": False, "http_status": 404,
                "body": {"error": f"Unknown mission {mission_id}"}}

    def mission_resume(self, mission_id):
        return {"ok": False, "http_status": 404, "body": {}}

    def mission_cancel(self, mission_id):
        return {"ok": False, "http_status": 404, "body": {}}

    def classify(self, prompt):
        return {"ok": True, "http_status": 200,
                "body": {"ok": True, "routing": "code"}}

    def enqueue_code_task(self, **kwargs):
        return {"ok": True, "http_status": 200,
                "body": {"task": {"id": "ctfake"}}}

    def code_task(self, task_id):
        ev_path = str(_EV_DIR / "ct_evidence.json")
        _EV_DIR.mkdir(parents=True, exist_ok=True)
        (_EV_DIR / "ct_evidence.json").write_text("{}", encoding="utf-8")
        return {"ok": True, "http_status": 200, "body": {"task": {
            "id": task_id, "status": "passed", "verdict": "PASS",
            "result": {"commit": "abc123", "branch": "aivido/code-task/x"},
            "evidence": [ev_path]}}}

    def code_task_evidence(self, task_id):
        return {"ok": True, "http_status": 200, "body": {"evidence": {
            "evidence_files": [str(_EV_DIR / "ct_evidence.json")]}}}

    def code_tasks(self):
        return {"ok": True, "http_status": 200, "body": {
            "ok": True, "tasks": [],
            "snapshot": {"queue_size": 0, "current_task_id": None,
                         "loop_running": True, "by_status": {}}}}

    def session_identity(self):
        return {"ok": True, "http_status": 200, "body": {"ok": True,
                                                         "session": {}}}

    def workspace(self):
        return {"ok": True, "http_status": 200, "body": {"ok": True}}

    def proof_status(self):
        return {"ok": True, "http_status": 200, "body": {"ok": True}}

    def proof_latest(self):
        return {"ok": True, "http_status": 200, "body": {}}


_EV_DIR = None


@pytest.fixture
def hermetic_env(tmp_path, monkeypatch):
    global _EV_DIR
    _EV_DIR = tmp_path / "ev"
    monkeypatch.setattr(model, "DEFAULT_RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(checks_mod, "BackendClient", FakeBackend)
    monkeypatch.setattr(checks_mod, "BridgeProbe", FakeBridge)
    monkeypatch.setattr(runner, "BackendClient", FakeBackend)
    monkeypatch.setattr(runner, "BridgeProbe", FakeBridge)
    from tools.unreal import unreal_bridge
    monkeypatch.setattr(unreal_bridge.UnrealBridge, "get_actor",
                        lambda self, name: {"ok": True, "result": {
                            "ok": True, "rotation": [0.0, 0.0, 0.0]}})
    return tmp_path


def test_full_matrix_clean_release_ready(hermetic_env):
    run = model.QARun(target="hermetic matrix")
    run.status = model.STATUS_RUNNING
    run.started_at = 1.0
    run.environment_snapshot = {}
    run.save()
    result = runner.execute_run(run.id)

    assert result["status"] == "COMPLETED"
    assert result["verdict"] == model.VERDICT_RELEASE_READY, (
        f"expected RELEASE_READY, got {result['verdict']}: "
        f"{result['verdict_why']}")
    # All 10 groups must be represented and PASS.
    groups = set(result["category_status"].keys())
    expected_groups = {
        "RUNTIME_HEALTH", "API_CONTRACT", "MISSION_BLACKBOX",
        "FALSE_PASS_DEFENSE", "EVIDENCE_INTEGRITY", "UNREAL_STATE_SAFETY",
        "CINEMATIC_ARTIFACT", "UI_BLACKBOX", "RECOVERY", "RELEASE_SAFETY",
    }
    assert expected_groups <= groups
    for g, st in result["category_status"].items():
        assert st in (model.STATUS_PASS, model.STATUS_SKIPPED), \
            f"group {g} failed: {st}"
    # No CRITICAL/MAJOR defects may be open (MINOR/WARNING findings such
    # as the absolute demo path in ui demo data are allowed but listed).
    sevs = [d["severity"] for d in result["defects"]]
    assert model.SEV_CRITICAL not in sevs
    assert model.SEV_MAJOR not in sevs
    assert result["verdict"] == model.VERDICT_RELEASE_READY


def test_full_matrix_defense_flags_false_pass(hermetic_env):
    """If a required check FAILs (e.g. a bad case passes), verdict drops."""
    run = model.QARun(target="hermetic fail")
    run.status = model.STATUS_RUNNING
    run.started_at = 1.0
    run.save()
    result = runner.execute_run(run.id)
    # Force-inject a critical defect to simulate a genuine finding and
    # recompute the verdict: it must become NOT_READY, never hide.
    run = model.QARun.load(run.id)
    run.add_defect(model.QADefect(model.SEV_CRITICAL, "injected", "G",
                                  defect_id="QA-FAIL"))
    from qa.verdict import compute_verdict
    verdict = compute_verdict(run)
    assert verdict["verdict"] == model.VERDICT_NOT_READY
    assert any("CRITICAL" in r for r in verdict["reasons"])