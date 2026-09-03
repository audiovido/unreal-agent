"""UNREAL CODER — capability registry + universal planner tests (L3/L4)."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.capability_registry import build_capability_registry
from core.universal_intent import expand_requirements, interpret_intent
from core.universal_planner import (
    QUALITY_VISUAL_FLOORS,
    build_universal_planner,
)

from tools.unreal.project_manager import (
    create_project,
    discover_projects,
    inspect_project,
    open_project,
)


def _live_registry():
    from core.tool_registry import build_registry
    from tools.unreal.unreal_bridge import UnrealBridge
    return build_registry(
        discover_projects, inspect_project, open_project, create_project,
        lambda **k: {}, lambda **k: {}, lambda **k: {}, lambda **k: {},
        bridge=UnrealBridge(),
    )


@pytest.fixture(scope="module")
def registry():
    return _live_registry()


@pytest.fixture(scope="module")
def planner(registry):
    return build_universal_planner(registry)


class TestCapabilityRegistry:
    def test_registry_binds_to_tools(self, registry):
        caps = build_capability_registry(registry)
        project_inspection = caps.get("project_inspection")
        assert project_inspection.available
        assert caps.available("project_inspection")

    def test_missing_tools_mark_unavailable(self, registry):
        caps = build_capability_registry({})
        assert not caps.available("project_inspection")
        cap = caps.get("project_inspection")
        assert "inspect_project" in cap.missing_tools

    def test_discovery_summary(self, registry):
        caps = build_capability_registry(registry)
        summary = caps.discover()
        assert summary["total"] >= 20
        assert summary["available"] > 0
        assert "ui" in summary["domains"]
        assert "materials" in summary["domains"]

    def test_no_invented_tools_planned(self, registry):
        """Every planned step must use a tool from the live registry."""
        caps = build_capability_registry(registry)
        planner = build_universal_planner(registry)
        for prompt in (
            "make me a main menu",
            "create a cinematic",
            "import a fbx asset",
            "fix my lighting",
        ):
            intent = interpret_intent(prompt)
            spec = expand_requirements(intent)
            plan = planner.build_plan(intent, spec, None)
            for step in plan.normalized_steps():
                tool = step["preferred_tool"]
                if step["phase"] not in {"SAFETY"} and tool:
                    assert tool in registry, (
                        f"{prompt!r}: invented tool {tool}"
                    )


class TestUniversalPlanner:
    def test_menu_plan_selects_ui_capability(self, planner):
        intent = interpret_intent("Create a polished Unreal main menu.")
        spec = expand_requirements(intent)
        plan = planner.build_plan(intent, spec, None)
        assert "umg_widget_authoring" in plan.selected_capabilities
        assert "project_inspection" in plan.selected_capabilities
        assert plan.visual_gate["enabled"]
        phases = [p["phase"] for p in plan.phases]
        assert "GROUND" in phases

    def test_menu_plan_has_no_blender(self, planner):
        intent = interpret_intent("Create a polished Unreal main menu.")
        spec = expand_requirements(intent)
        plan = planner.build_plan(intent, spec, None)
        assert "blender_asset_repair" not in plan.selected_capabilities

    def test_dependency_chain_ordered(self, planner):
        intent = interpret_intent("create a small sci-fi environment scene")
        spec = expand_requirements(intent)
        plan = planner.build_plan(intent, spec, None)
        seen = set()
        for step in plan.normalized_steps():
            for dep in step["depends_on"]:
                assert dep in seen, f"{step['step_id']} before {dep}"
            seen.add(step["step_id"])

    def test_quality_floor_reflects_mode(self, planner):
        intent = interpret_intent("make a photoreal cinematic")
        spec = expand_requirements(intent)
        plan = planner.build_plan(intent, spec, None)
        assert plan.visual_gate["score_floor"] >= QUALITY_VISUAL_FLOORS[
            "cinematic"]

    def test_prototype_floor_low(self, planner):
        intent = interpret_intent("block out a combat arena")
        spec = expand_requirements(intent)
        plan = planner.build_plan(intent, spec, None)
        assert plan.visual_gate["score_floor"] <= QUALITY_VISUAL_FLOORS[
            "prototype"]

    def test_chat_plan_no_execution_steps(self, planner):
        intent = interpret_intent("what is a level sequence?")
        spec = expand_requirements(intent)
        plan = planner.build_plan(intent, spec, None)
        assert plan.normalized_steps() == []
        assert plan.phases[0]["phase"] == "ANSWER"

    def test_destructive_plan_inserts_checkpoint(self, planner):
        intent = interpret_intent("delete all unused assets")
        spec = expand_requirements(intent)
        plan = planner.build_plan(intent, spec, None)
        ids = [s.step_id for s in plan.steps]
        assert "checkpoint" in ids

    def test_normalized_steps_match_executor_schema(self, planner):
        intent = interpret_intent("fix the lighting in this room")
        spec = expand_requirements(intent)
        plan = planner.build_plan(intent, spec, None)
        for step in plan.normalized_steps():
            for key in ("step_id", "phase", "intent", "preferred_tool",
                        "parameters", "expected_result", "depends_on",
                        "status"):
                assert key in step, key

    def test_skipped_capabilities_recorded(self, registry):
        planner = build_universal_planner(registry)
        caps = build_capability_registry({})
        # A planner bound to an empty registry must skip, not crash.
        empty_planner = build_universal_planner({})
        intent = interpret_intent("make a menu")
        spec = expand_requirements(intent)
        plan = empty_planner.build_plan(intent, spec, None)
        assert plan.skipped_capabilities
        assert plan.warnings  # visual gate availability warning


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
