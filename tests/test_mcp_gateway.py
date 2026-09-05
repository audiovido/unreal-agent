"""MCP GATEWAY — hermetic tests (no live backend, no live editor).

Covers the gateway's own surface: the 7 required MCP tools are registered,
Bearer auth is enforced on every POST, the health probe stays public,
structured envelopes are shaped correctly, and backend failures degrade to
structured JSON instead of raising.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REQUIRED_TOOLS = {
    "get_status", "start_task", "get_task_status", "run_validation",
    "get_evidence", "retry_task", "cancel_task",
    # autonomous supervisor code-task tools
    "start_code_task", "get_code_task_status", "get_code_evidence",
    "retry_code_task", "cancel_code_task", "route_prompt",
}


@pytest.fixture(autouse=True)
def _fake_key(monkeypatch):
    monkeypatch.setenv("AIVIDO_MCP_API_KEY", "test-key-1234567890")
    from app import mcp_gateway
    monkeypatch.setattr(
        mcp_gateway, "BACKEND_URL", "http://127.0.0.1:1")  # unreachable


@pytest.fixture()
def gateway_app():
    from app import mcp_gateway
    return mcp_gateway.create_gateway_app(
        mcp_gateway.load_or_create_api_key())


@pytest.fixture()
def client(gateway_app):
    from fastapi.testclient import TestClient
    with TestClient(gateway_app, raise_server_exceptions=False) as c:
        yield c


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

def test_all_required_tools_registered():
    import asyncio
    from app import mcp_gateway
    server = mcp_gateway.build_mcp_server("k")
    listing = asyncio.run(server.list_tools())
    tools = {t.name for t in listing}
    assert REQUIRED_TOOLS <= tools, f"missing: {REQUIRED_TOOLS - tools}"


def test_required_tools_absent_from_legacy_registry():
    """The gateway must not invent extra execution tools."""
    import asyncio
    from app import mcp_gateway
    server = mcp_gateway.build_mcp_server("k")
    listing = asyncio.run(server.list_tools())
    tools = {t.name for t in listing}
    assert tools == REQUIRED_TOOLS


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def _post_mcp(client, token=None, body=None):
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    return client.post(
        "/mcp",
        headers=headers,
        json=body or {"jsonrpc": "2.0", "id": 1,
                      "method": "initialize",
                      "params": {"protocolVersion": "2025-03-26",
                                 "capabilities": {},
                                 "clientInfo": {"name": "t", "version": "0"}}},
    )


def test_post_without_token_rejected(client):
    response = _post_mcp(client, token=None)
    assert response.status_code == 401


def test_post_with_wrong_token_rejected(client):
    response = _post_mcp(client, token="wrong-token")
    assert response.status_code == 401


def test_post_with_valid_token_passes_auth(client):
    response = _post_mcp(client, token="test-key-1234567890")
    # Middleware lets it through: the MCP handler answers (initialization
    # over an unreachable backend still yields an MCP-level response, but
    # NEVER a 401).
    assert response.status_code != 401


def test_x_api_key_header_accepted(client):
    response = client.post(
        "/mcp",
        headers={"x-api-key": "test-key-1234567890",
                 "Content-Type": "application/json"},
        json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
    )
    assert response.status_code != 401


def test_health_is_public_without_auth(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["mcp_endpoint"] == "/mcp"


# ---------------------------------------------------------------------------
# Tool behavior (unit level, backend mocked away)
# ---------------------------------------------------------------------------

def test_start_task_rejects_empty_prompt():
    from app import mcp_gateway
    result = mcp_gateway.tool_start_task("   ")
    assert result["ok"] is False
    assert "prompt is required" in result["errors"]


def test_backend_failure_degrades_to_structured_json(monkeypatch):
    from app import mcp_gateway

    class _Broken:
        def _get(self, path, timeout=None):
            raise RuntimeError("backend unreachable")

    monkeypatch.setattr(mcp_gateway, "AividoBackend", lambda *a, **k: _Broken())
    result = mcp_gateway.tool_get_task_status("mission_x")
    assert result["ok"] is False
    assert result["status"] == "error"
    assert result["stage"] == "error"
    assert result["errors"]
    assert "task_id" in result and "evidence" in result


def test_mission_envelope_shapes_real_payload():
    from app import mcp_gateway
    payload = {
        "status": "complete",
        "verdict": "PASS",
        "why": "All 4 steps verified.",
        "interpretation": {"primary_domain": "world_building"},
        "plan": {"phases": []},
        "completed_work": {"steps_total": 4, "steps_completed": 4},
        "remaining_issues": [],
        "blockers": [],
        "warnings": ["bridge slow"],
        "evidence": [{"path": "C:/x/capture_01.png"}],
        "artifacts": [{"path": "C:/x/level.umap"}],
        "mission_log": "C:/memory/mission_logs/mission_x.json",
    }
    env = mcp_gateway._mission_envelope("mission_x", payload)
    assert env["task_id"] == "mission_x"
    assert env["status"] == "complete"
    assert env["stage"] == "complete"
    assert env["result"]["verdict"] == "PASS"
    assert env["errors"] == ["warnings: bridge slow"]
    assert env["evidence"]["paths"] == ["C:/x/capture_01.png"]
    assert env["evidence"]["artifacts"] == ["C:/x/level.umap"]


def test_mission_envelope_maps_stages():
    from app import mcp_gateway
    for status, stage in (
        ("interpreting", "planning"), ("planning", "planning"),
        ("executing", "executing"), ("validating", "validating"),
        ("repairing", "validating"), ("complete", "complete"),
        ("failed", "failed"), ("blocked", "blocked"),
    ):
        env = mcp_gateway._mission_envelope(
            "m", {"status": status, "verdict": None})
        assert env["stage"] == stage, status


def test_key_from_env_var(monkeypatch):
    from app import mcp_gateway
    monkeypatch.setenv("AIVIDO_MCP_API_KEY", "env-key-abc")
    assert mcp_gateway.load_or_create_api_key() == "env-key-abc"