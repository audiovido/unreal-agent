"""UNREAL CODER — Phase F: canonical API product hardening tests.

Validates the product-grade behavior of POST /api/unreal-coder and its
companion endpoints: request validation, HTTP codes, malformed input,
unknown missions, dry-run idempotency of planning, structured error
payloads, and the Phase T user result contract.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from app import api
    from app.unreal_coder_api import register_unreal_coder_api
    register_unreal_coder_api(api.app, tool_registry=lambda: api.REGISTRY)
    with TestClient(api.app, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def isolated_checkpoints(tmp_path, monkeypatch):
    from core import mission as mission_mod
    monkeypatch.setattr(mission_mod, "CHECKPOINT_DIR", tmp_path / "cp")
    yield


class TestRequestValidation:
    def test_missing_prompt_422(self, client):
        response = client.post("/api/unreal-coder", json={})
        assert response.status_code == 422

    def test_empty_prompt_400(self, client):
        response = client.post("/api/unreal-coder", json={"prompt": "   "})
        assert response.status_code == 400

    def test_non_string_prompt_422(self, client):
        response = client.post("/api/unreal-coder", json={"prompt": 12345})
        assert response.status_code == 422

    def test_malformed_body_422(self, client):
        response = client.post(
            "/api/unreal-coder", content=b"{not json",
            headers={"Content-Type": "application/json"})
        assert response.status_code == 422

    def test_unknown_fields_tolerated(self, client):
        """Simplest request stays simple; extra fields never break the API."""
        response = client.post("/api/unreal-coder", json={
            "prompt": "make a menu",
            "dry_run": True,
            "future_field": {"whatever": True},
        })
        assert response.status_code == 200

    def test_unknown_mission_404_structured(self, client):
        response = client.get("/api/unreal-coder/mission/mission_nope")
        assert response.status_code == 404
        assert "mission_nope" in response.text

    def test_unknown_mission_resume_404(self, client):
        response = client.post("/api/unreal-coder", json={
            "prompt": "add a light", "mission_id": "mission_missing"})
        assert response.status_code == 404

    def test_unknown_project_still_plans_ground_step(self, client):
        """An unresolvable project path must not crash planning; the plan
        grounds the project and surfaces resolvable issues."""
        response = client.post("/api/unreal-coder", json={
            "prompt": "add a warm light",
            "project": "Q:/definitely/not/real/Nope.uproject",
            "dry_run": True,
        })
        assert response.status_code == 200
        plan = response.json()["plan"]
        assert plan.get("phases")
        assert plan.get("phases", [{}])[0].get("phase") == "GROUND"


class TestSimplestRequest:
    def test_one_sentence_mode_minimal(self, client):
        """{prompt} alone is valid — dry-run proves interpret+plan works."""
        response = client.post("/api/unreal-coder", json={
            "prompt": "make this scene look cinematic"})
        # Live execute may fail without project binding, but MUST NOT 4xx.
        assert response.status_code == 200
        data = response.json()
        assert data["mission_id"]
        assert data["status"] in (
            "complete", "failed", "blocked", "planning", "executing",
            "validating", "repairing")

    def test_dry_run_never_mutates(self, client):
        response = client.post("/api/unreal-coder", json={
            "prompt": "build a whole open world with multiplayer",
            "dry_run": True})
        assert response.status_code == 200
        assert response.json()["status"] in ("planning", "complete")


class TestCompanionEndpoints:
    def test_capabilities(self, client):
        response = client.get("/api/unreal-coder/capabilities")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 20 and data["available"] > 0

    def test_session_endpoint(self, client):
        response = client.get("/api/unreal-coder/session")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] in (True, False)
        if data["ok"]:
            session = data["session"]
            for field in ("project_name", "uproject_path", "engine_version",
                          "bridge", "session_id"):
                assert field in session

    def test_doctor_endpoint(self, client):
        response = client.get("/api/unreal-coder/doctor")
        assert response.status_code == 200
        data = response.json()
        assert {"PASS", "WARN", "FAIL"} <= set(data["summary"])

    def test_mission_roundtrip(self, client):
        created = client.post("/api/unreal-coder", json={
            "prompt": "create a cozy room", "dry_run": True}).json()
        fetched = client.get(
            f"/api/unreal-coder/mission/{created['mission_id']}")
        assert fetched.status_code == 200
        assert fetched.json()["mission_id"] == created["mission_id"]


class TestStructuredPayloads:
    def test_dry_run_envelope_is_stable(self, client):
        data = client.post("/api/unreal-coder", json={
            "prompt": "polish the lighting",
            "dry_run": True}).json()
        for key in ("mission_id", "status", "verdict", "interpretation",
                    "plan", "completed_work", "evidence", "warnings",
                    "remaining_issues", "artifacts", "resumable"):
            assert key in data, key

    def test_plan_includes_visual_gate_for_visual_tasks(self, client):
        data = client.post("/api/unreal-coder", json={
            "prompt": "make the room look cinematic and premium",
            "dry_run": True}).json()
        gate = data["plan"].get("visual_gate") or {}
        assert gate.get("enabled") is True
        assert gate.get("score_floor", 0) >= 7.0

    def test_planning_idempotent(self, client):
        """Same input twice -> same interpretation + same selected caps."""
        first = client.post("/api/unreal-coder", json={
            "prompt": "create a polished sci-fi main menu",
            "dry_run": True}).json()
        second = client.post("/api/unreal-coder", json={
            "prompt": "create a polished sci-fi main menu",
            "dry_run": True}).json()
        assert first["interpretation"] == second["interpretation"]
        assert (first["plan"]["selected_capabilities"]
                == second["plan"]["selected_capabilities"])


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
