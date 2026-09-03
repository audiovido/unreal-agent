"""RECOVERY TORTURE T6 — missing-mesh truthfulness (hermetic).

Regression coverage for the defect found during Recovery Torture: spawn_actor
used to report silent full success when the requested mesh asset did not
exist. The bridge listener now returns a truthful structured status:

    missing mesh  -> mesh_loaded: false + warning, never silent full success
    valid mesh    -> mesh_loaded: true
    no mesh asked -> mesh_loaded: null (actor-only spawn)

These tests never touch the live editor: the transport is stubbed, exactly
like the conftest regression guard would stub it. The generated listener
script is asserted to contain the truthful branches, and a canned missing-
mesh listener response is asserted to flow through unchanged.
"""
import json

from tools.unreal.unreal_bridge import UnrealBridge


class _StubTransport:
    """Replaces _send: records the payload, returns a canned response."""

    def __init__(self, response):
        self.response = response
        self.payload = None

    def __call__(self, payload):
        self.payload = payload
        return self.response


def _stub_bridge(response):
    bridge = UnrealBridge()
    stub = _StubTransport(response)
    bridge._send = stub  # instance-level stub (transport only)
    return bridge, stub


class TestMissingMeshTruthfulness:
    def test_missing_mesh_script_has_no_silent_success_path(self, monkeypatch):
        """The listener script must expose mesh_loaded + warning so a missing
        mesh is never reported as a clean full success."""
        bridge, stub = _stub_bridge({"ok": False, "error": "unused"})
        bridge.spawn_actor(
            actor_name="Sentinel",
            actor_type="StaticMeshActor",
            mesh_asset="/Game/DoesNotExist/Missing",
        )
        code = stub.payload["code"]
        assert "mesh_loaded" in code
        assert '"warning"' in code
        assert "/Game/DoesNotExist/Missing" in code

    def test_missing_mesh_response_is_truthful_not_full_success(self,
                                                                monkeypatch):
        """Canned listener response for a missing mesh (actor spawned, mesh
        NOT found) must flow through with mesh_loaded=false + warning — the
        response shape the T6 fix added — and must not claim the mesh loaded."""
        canned = {
            "ok": True,
            "name": "Sentinel_0",
            "class": "StaticMeshActor",
            "mesh_loaded": False,
            "requested_mesh": "/Game/DoesNotExist/Missing",
            "warning": "Requested mesh asset not found: /Game/DoesNotExist/Missing",
        }
        bridge, _ = _stub_bridge(canned)
        result = bridge.spawn_actor(
            actor_name="Sentinel",
            actor_type="StaticMeshActor",
            mesh_asset="/Game/DoesNotExist/Missing",
        )
        assert result.get("ok") is True            # the ACTOR spawned
        assert result.get("mesh_loaded") is False  # but the MESH did not load
        assert "warning" in result                 # surfaced, not swallowed
        assert result.get("requested_mesh") == "/Game/DoesNotExist/Missing"

    def test_valid_mesh_response_unaffected(self, monkeypatch):
        """Valid-mesh behavior is unchanged: mesh_loaded=true, no warning."""
        canned = {
            "ok": True,
            "name": "Cube_0",
            "class": "StaticMeshActor",
            "mesh_loaded": True,
            "requested_mesh": "/Engine/BasicShapes/Cube",
        }
        bridge, _ = _stub_bridge(canned)
        result = bridge.spawn_actor(
            actor_name="Cube0",
            actor_type="StaticMeshActor",
            mesh_asset="/Engine/BasicShapes/Cube",
        )
        assert result.get("ok") is True
        assert result.get("mesh_loaded") is True
        assert "warning" not in result

    def test_no_mesh_request_actor_only_spawn(self, monkeypatch):
        """Actor-only spawn (no mesh requested) keeps mesh_loaded null."""
        canned = {
            "ok": True,
            "name": "Empty_0",
            "class": "Actor",
            "mesh_loaded": None,
            "requested_mesh": None,
        }
        bridge, _ = _stub_bridge(canned)
        result = bridge.spawn_actor(actor_name="Empty0")
        assert result.get("ok") is True
        assert result.get("mesh_loaded") is None
