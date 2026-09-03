"""UNREAL CODER — Phase C: real multi-project safety tests.

Proves the mutation guard blocks: wrong project, stale bridge (editor
restart/PID change), bridge down, changed active map, PIE-active mutation —
and allows the correct project through. All offline via a fake bridge.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.project_safety import (
    MUTATING_TOOLS,
    ProjectMutationGuard,
    guard_dispatch,
)


class FakeBridge:
    """Scriptable bridge: returns canned results per call."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.host = "127.0.0.1"
        self.port = 6766

    def execute_python(self, code, **kwargs):
        self.calls.append(code[:60])
        if self.script:
            item = self.script.pop(0)
            if isinstance(item, Exception):
                raise item
            return {"result": item}
        return {"result": {"ok": False}}


PROJECT_A = {
    "ok": True, "project_path": "C:/Games/ProjectA/ProjectA.uproject",
    "project_name": "ProjectA", "engine": "5.8.2",
    "editor_pid": 111, "active_map": "/Game/Maps/Main.Main",
    "pie_running": False,
}
PROJECT_B = {
    "ok": True, "project_path": "C:/Games/ProjectB/ProjectB.uproject",
    "project_name": "ProjectB", "engine": "5.8.2",
    "editor_pid": 222, "active_map": "/Game/Maps/Other.Other",
    "pie_running": False,
}


def ok_step(step):
    return {"ok": True, "tool": step.get("preferred_tool")}


class TestMutationGuard:
    def test_correct_project_allowed(self):
        bridge = FakeBridge([PROJECT_A, PROJECT_A])
        guard = ProjectMutationGuard(bridge=bridge)
        guard.capture_identity()
        verdict = guard.validate_mutation(
            expected_uproject=PROJECT_A["project_path"])
        assert verdict.ok is True
        assert verdict.code == "OK"

    def test_wrong_project_blocked(self):
        bridge = FakeBridge([PROJECT_B, PROJECT_B])
        guard = ProjectMutationGuard(bridge=bridge)
        guard.capture_identity()
        verdict = guard.validate_mutation(
            expected_uproject=PROJECT_A["project_path"])
        assert verdict.ok is False
        assert verdict.code == "WRONG_PROJECT"
        assert "cross-project mutation" in verdict.detail

    def test_wrong_project_by_name_blocked(self):
        bridge = FakeBridge([PROJECT_B, PROJECT_B])
        guard = ProjectMutationGuard(bridge=bridge)
        guard.capture_identity()
        verdict = guard.validate_mutation(expected_project_name="ProjectA")
        assert verdict.ok is False
        assert verdict.code == "WRONG_PROJECT"

    def test_editor_restart_pid_change_blocked(self):
        restarted = dict(PROJECT_A, editor_pid=999)
        bridge = FakeBridge([PROJECT_A, restarted])
        guard = ProjectMutationGuard(bridge=bridge)
        guard.capture_identity()
        verdict = guard.validate_mutation(
            expected_uproject=PROJECT_A["project_path"])
        assert verdict.ok is False
        assert verdict.code == "EDITOR_RESTARTED"

    def test_bridge_down_blocks_mutation(self):
        # Identity capture succeeds, then the live probe dies (editor closed).
        class DyingBridge(FakeBridge):
            def execute_python(self, code, **kwargs):
                self.calls.append(code[:60])
                raise ConnectionError("refused")

        bridge = DyingBridge([PROJECT_A])
        guard = ProjectMutationGuard(bridge=bridge)
        guard.capture_identity()
        verdict = guard.validate_mutation(
            expected_uproject=PROJECT_A["project_path"])
        assert verdict.ok is False
        assert verdict.code == "BRIDGE_DOWN"

    def test_map_change_blocked_mid_mission(self):
        moved = dict(PROJECT_A, active_map="/Game/Maps/Elsewhere.Elsewhere")
        bridge = FakeBridge([PROJECT_A, moved])
        guard = ProjectMutationGuard(bridge=bridge)
        guard.capture_identity()
        verdict = guard.validate_mutation(
            expected_uproject=PROJECT_A["project_path"])
        assert verdict.ok is False
        assert verdict.code == "MAP_CHANGED"
        # But explicitly allowed map changes pass (fresh live read).
        guard.identity = None  # re-capture the moved map as the baseline
        bridge2 = FakeBridge([moved])
        guard.bridge = bridge2
        guard.capture_identity()
        bridge3 = FakeBridge([moved])
        guard.bridge = bridge3
        verdict2 = guard.validate_mutation(
            expected_uproject=PROJECT_A["project_path"],
            allow_map_change=True)
        assert verdict2.ok is True

    def test_pie_blocks_editor_mutation(self):
        pie = dict(PROJECT_A, pie_running=True)
        bridge = FakeBridge([PROJECT_A, pie])
        guard = ProjectMutationGuard(bridge=bridge)
        guard.capture_identity()
        verdict = guard.validate_mutation(
            expected_uproject=PROJECT_A["project_path"])
        assert verdict.ok is False
        assert verdict.code == "PIE_ACTIVE"
        # PIE-aware tools may opt in (fresh live read of the same state).
        bridge2 = FakeBridge([pie])
        guard.bridge = bridge2
        verdict2 = guard.validate_mutation(
            expected_uproject=PROJECT_A["project_path"], allow_pie=True)
        assert verdict2.ok is True

    def test_multiple_editors_distinct_ports(self):
        """Two editors on different ports resolve distinct identities."""
        bridge_a = FakeBridge([PROJECT_A])
        guard_a = ProjectMutationGuard(bridge=bridge_a)
        id_a = guard_a.capture_identity()
        bridge_b = FakeBridge([PROJECT_B])
        guard_b = ProjectMutationGuard(bridge=bridge_b, )
        guard_b.bridge.port = 6767  # second editor port
        id_b = guard_b.capture_identity()
        assert id_a.uproject_path != id_b.uproject_path
        assert id_a.bridge_port == 6766 and id_b.bridge_port == 6767


class TestGuardedDispatch:
    def test_read_only_tools_pass_without_validation(self):
        bridge = FakeBridge([])
        guard = ProjectMutationGuard(bridge=bridge)
        dispatched = guard_dispatch(ok_step, guard)
        result = dispatched({"preferred_tool": "list_level_actors"})
        assert result["ok"] is True
        assert bridge.calls == []  # no identity probe for read-only

    def test_mutating_tool_blocked_before_dispatch(self):
        bridge = FakeBridge([PROJECT_B, PROJECT_B])
        guard = ProjectMutationGuard(bridge=bridge,
                                     expected_project_name="ProjectA")
        dispatched = guard_dispatch(ok_step, guard)
        result = dispatched({"preferred_tool": "spawn_actor"})
        assert result["ok"] is False
        assert result["error"].startswith("WRONG_PROJECT")
        assert "guard" in result

    def test_mutating_tool_allowed_on_correct_project(self):
        bridge = FakeBridge([PROJECT_A, PROJECT_A])
        guard = ProjectMutationGuard(bridge=bridge)
        guard.capture_identity()
        dispatched = guard_dispatch(ok_step, guard)
        result = dispatched({"preferred_tool": "save_level"})
        assert result["ok"] is True

    def test_mutation_tool_list_is_comprehensive(self):
        for tool in ("spawn_actor", "delete_asset", "save_level",
                     "compile_blueprint", "run_powershell", "start_pie"):
            assert tool in MUTATING_TOOLS


class TestSessionIdentity:
    def test_identity_contract_fields(self):
        bridge = FakeBridge([PROJECT_A])
        guard = ProjectMutationGuard(bridge=bridge)
        identity = guard.capture_identity()
        data = identity.to_dict()
        for field in ("session_id", "project_name", "uproject_path",
                      "engine_version", "editor_pid", "bridge",
                      "active_map", "pie_running"):
            assert field in data, field
        assert data["project_name"] == "ProjectA"
        assert data["editor_pid"] == 111

    def test_identity_offline_is_empty(self):
        class DeadBridge(FakeBridge):
            def execute_python(self, code, **kwargs):
                raise ConnectionError("down")

        guard = ProjectMutationGuard(bridge=DeadBridge([]))
        identity = guard.capture_identity()
        assert identity.uproject_path == ""
        assert identity.project_name == ""


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
