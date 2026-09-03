"""UNREAL CODER — canonical single API integration tests.

Exercises POST /api/unreal-coder through the FastAPI app WITHOUT a live
editor: the mission engine runs against the real capability registry built
from the real tool registry, but mission execution in this suite is the
planning + checkpoint path (dry_run) or chat mode (model mocked at the
requests layer). Confirms boot, routes, error responses and envelopes.
"""
import sys
from pathlib import Path
from unittest.mock import patch

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


class TestUnrealCoderAPI:
    def test_route_registered(self, client):
        response = client.get("/openapi.json")
        assert response.status_code == 200
        paths = response.json()["paths"]
        assert "/api/unreal-coder" in paths
        assert "/api/unreal-coder/capabilities" in paths
        assert "/api/unreal-coder/resume" in paths
        assert "/api/unreal-coder/mission/{mission_id}" in paths

    def test_empty_prompt_rejected(self, client):
        response = client.post("/api/unreal-coder", json={"prompt": "  "})
        assert response.status_code == 400

    def test_capabilities_endpoint(self, client):
        response = client.get("/api/unreal-coder/capabilities")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 20
        assert data["available"] > 0
        assert "ui" in data["domains"]
        assert "cinematics" in data["domains"]

    def test_dry_run_returns_full_envelope(self, client, tmp_path, monkeypatch):
        from core import mission as mission_mod
        monkeypatch.setattr(
            mission_mod, "CHECKPOINT_DIR", tmp_path / "cp")
        response = client.post("/api/unreal-coder", json={
            "prompt": "Create a polished sci-fi main menu",
            "dry_run": True,
        })
        assert response.status_code == 200
        data = response.json()
        for key in ("mission_id", "status", "verdict", "interpretation",
                    "plan", "completed_work", "evidence", "warnings",
                    "remaining_issues", "artifacts", "resumable"):
            assert key in data, key
        assert data["interpretation"]["domains"]
        assert "ui" in data["interpretation"]["domains"]
        caps = data["plan"]["selected_capabilities"]
        assert "umg_widget_authoring" in caps

    def test_chat_mode_answers_without_execution(
        self, client, tmp_path, monkeypatch
    ):
        from core import mission as mission_mod
        monkeypatch.setattr(
            mission_mod, "CHECKPOINT_DIR", tmp_path / "cp")
        with patch("core.orchestrator.run_chat",
                   return_value="A GameMode defines the rules of play."):
            response = client.post("/api/unreal-coder", json={
                "prompt": "What is a GameMode?",
            })
        assert response.status_code == 200
        data = response.json()
        assert data["mode"] == "chat"
        assert "GameMode" in data["message"]

    def test_mission_state_persisted(self, client, tmp_path, monkeypatch):
        from core import mission as mission_mod
        cp = tmp_path / "cp"
        monkeypatch.setattr(mission_mod, "CHECKPOINT_DIR", cp)
        response = client.post("/api/unreal-coder", json={
            "prompt": "make me a beautiful room",
            "dry_run": True,
        })
        mission_id = response.json()["mission_id"]
        assert list(cp.glob(f"{mission_id}.json"))

    def test_unknown_mission_404(self, client):
        response = client.get(
            "/api/unreal-coder/mission/mission_doesnotexist")
        assert response.status_code == 404

    def test_existing_api_untouched(self, client):
        """Regression guard: legacy routes still exist side by side."""
        response = client.get("/openapi.json")
        paths = response.json()["paths"]
        assert "/api/chat" in paths
        assert "/api/status" in paths
        assert "/api/workboard/runner/status" in paths
