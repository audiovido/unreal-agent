from __future__ import annotations

from fastapi.testclient import TestClient

from app import api


PROMPT = (
    "Create a premium cinematic vehicle showcase scene with a real vehicle, "
    "save it, capture fresh proof, and improve the visual quality automatically."
)


def test_devboard_action_prompt_routes_vehicle_profile_into_real_execution_plan(monkeypatch):
    """The Devboard transport must select the profile before execution starts."""
    captured = {}

    def fake_start(message, source="ui"):
        state = api.new_execution(message)
        captured["state"] = state
        return {
            "ok": True,
            "state": "running",
            "action": source,
            "task_id": state["id"],
        }

    monkeypatch.setattr(api, "_start_async_ui_execution", fake_start)
    with TestClient(api.app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/action",
            json={
                "action": "prompt",
                "payload": {"message": PROMPT},
                "context": {"project": "ASSET_Showcase2", "provider": "local"},
            },
        )

    assert response.status_code == 200
    state = captured["state"]
    assert state["visual_profile"] == "vehicle_showcase"
    assert state["visual_target"]["visual_profile"] == "vehicle_showcase"
    assert state["visual_strategy"]["max_passes"] == 3
    assert state["visual_floor"] == 8.5
    assert state["plan"]["_routing"]["visual_profile"] == "vehicle_showcase"
    step_ids = [step["step_id"] for step in state["plan"]["steps"]]
    assert "showcase_vehicle" in step_ids
    assert "showcase_evidence" in step_ids
    vehicle = next(step for step in state["plan"]["steps"]
                   if step["step_id"] == "showcase_vehicle")
    assert vehicle["parameters"]["mesh_asset"].endswith(
        "Cesium_Milk_Truck.Cesium_Milk_Truck"
    )


def test_profiled_visual_failure_cannot_bypass_canonical_terminal_gate():
    state = {
        "visual_profile": "vehicle_showcase",
        "visual_acceptance_failure": {
            "status": "BLOCKED",
            "error": "fresh production proof hash did not change",
            "fresh_hash_changed": False,
        },
        "task_goal": None,
        "plan": {"steps": []},
        "validation_result": "passed",
        "evidence_handled": True,
    }

    blocker = api._completion_blocker(state)

    assert blocker["code"] == "BLOCKED"
    assert blocker["detail"] == "BLOCKED_VISUAL_ACCEPTANCE"
    assert blocker["stall_detail"]["visual_profile"] == "vehicle_showcase"
    assert blocker["stall_detail"]["fresh_hash_changed"] is False


def test_vehicle_profile_keeps_bounded_strategy_and_corrected_locator(monkeypatch):
    """The production self-fix seam uses the shared loop/profile, not a second path."""
    calls = {}

    class FakeAdapter:
        def __init__(self, bridge, visible_retries=2, wake_editor=None):
            calls["adapter"] = (bridge, visible_retries, wake_editor)

        def capture(self, path):
            from pathlib import Path
            index = len(calls.setdefault("captures", []))
            calls["captures"].append(path)
            Path(path).write_bytes(
                b"initial-proof" if index == 0 else b"final-proof"
            )
            return {"path": path}

        def apply(self, *args):
            calls.setdefault("apply", []).append(args[0])
            return {"ok": True, "note": args[0]}

        def _restore(self, *args):
            calls["rollback"] = True
            return {"ok": True}

    class FakeLoop:
        def __init__(self, **kwargs):
            calls["loop"] = kwargs

        def run(self):
            capture = calls["loop"]["capture"]
            initial = capture()
            final = capture()
            return {
                "status": "COMPLETE",
                "iterations": 2,
                "final": {"path": final, "score": {"overall": 8.83}},
                "initial": initial,
            }

    import core.unreal_fix_adapter as fix_adapter
    import core.visual_loop as visual_loop
    monkeypatch.setattr(fix_adapter, "UnrealFixAdapter", FakeAdapter)
    monkeypatch.setattr(visual_loop, "AutonomousVisualLoop", FakeLoop)
    monkeypatch.setattr(api, "BRIDGE", object())

    state = {
        "id": "task_vehicle_integration",
        "visual_profile": "vehicle_showcase",
        "visual_target": api._production_visual_target(PROMPT),
    }
    result = api._run_production_visual_director(
        state,
        "assetlib/proof/vehicle_showcase_controlled_20260905/final_fresh_vehicle.png",
    )

    assert result["status"] == "COMPLETE", result
    assert result["fresh_hash_changed"] is True
    assert calls["loop"]["target"]["visual_profile"] == "vehicle_showcase"
    assert calls["loop"]["max_passes"] == 3
    assert calls["loop"]["subject_locator"] is not None
    assert calls["loop"]["rollback"] is not None
