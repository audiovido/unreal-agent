"""UNREAL CODER — cross-domain generalization matrix.

Proves routing + planning + capability selection + anti-overreach across the
representative user categories (UI, gameplay, environment, cinematic,
materials/asset, visual improvement) plus genuinely vague/non-technical
prompts. All offline and deterministic.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.universal_intent import expand_requirements, interpret_intent
from core.universal_planner import build_universal_planner

from tools.unreal.project_manager import (
    create_project, discover_projects, inspect_project, open_project,
)


@pytest.fixture(scope="module")
def planner():
    from core.tool_registry import build_registry
    from tools.unreal.unreal_bridge import UnrealBridge
    registry = build_registry(
        discover_projects, inspect_project, open_project, create_project,
        lambda **k: {}, lambda **k: {}, lambda **k: {}, lambda **k: {},
        bridge=UnrealBridge(),
    )
    return build_universal_planner(registry)


def plan_for(planner, prompt):
    intent = interpret_intent(prompt)
    spec = expand_requirements(intent)
    return intent, spec, planner.build_plan(intent, spec, None)


MISSIONS = [
    # (prompt, required domains, required capabilities, forbidden kinds)
    ("Create a polished Unreal main menu.",
     {"ui"}, {"umg_widget_authoring"}, {"assets"}),
    ("Build a third-person sci-fi shooter prototype.",
     {"gameplay"}, {"blueprint_authoring"}, {"assets"}),
    ("Improve the lighting and materials of a basic environment.",
     {"lighting", "materials"}, {"lighting_setup"}, {"assets"}),
    ("Create a short Sequencer camera cinematic.",
     {"cinematics"}, {"sequencer_cinematic"}, {"assets"}),
    ("Import and prepare a mesh asset for my scene.",
     {"asset_pipeline"}, {"asset_import"}, set()),
    ("Turn this room into a photorealistic apartment.",
     {"environment_art"}, {"environment_composition"}, set()),
    ("Optimize this project for performance.",
     {"optimization"}, {"performance_analysis"}, set()),
    ("Create an architectural walkthrough of the apartment.",
     {"archviz"}, set(), {"assets"}),
    ("Create a city map with roads and terrain.",
     {"world_building"}, set(), set()),
    ("Build a multiplayer lobby.",
     {"gameplay"}, set(), set()),
    ("Create an interactive museum.",
     {"environment_art"}, set(), set()),
    ("Make a character selection screen.",
     {"ui"}, {"umg_widget_authoring"}, {"assets"}),
]

VAGUE_PROMPTS = [
    "make it prettier",
    "make this look like a movie",
    "I want a menu for my game",
    "make me a cool room",
    "this asset looks bad fix it",
]


class TestGeneralizationMatrix:
    @pytest.mark.parametrize("prompt,domains,caps,forbidden", MISSIONS)
    def test_mission_routes_and_plans(
        self, planner, prompt, domains, caps, forbidden
    ):
        intent, spec, plan = plan_for(planner, prompt)
        assert intent.mode == "execute", prompt
        assert domains <= set(intent.domains), (
            prompt, intent.domains)
        assert caps <= set(plan.selected_capabilities), (
            prompt, plan.selected_capabilities)
        kinds = {r["kind"] for r in spec.requirements}
        assert not (forbidden & kinds), (prompt, kinds)
        # Every plan grounds the project first.
        assert plan.phases[0]["phase"] == "GROUND"
        # No invented tools anywhere.
        for step in plan.normalized_steps():
            assert step["preferred_tool"], prompt

    @pytest.mark.parametrize("prompt", VAGUE_PROMPTS)
    def test_vague_prompt_translates_safely(self, planner, prompt):
        intent, spec, plan = plan_for(planner, prompt)
        assert intent.mode == "execute"
        # Safe actionable work: real requirements, real tools, validation.
        assert spec.requirements
        assert any(r["kind"] == "validation" for r in spec.requirements)
        assert plan.normalized_steps()

    @pytest.mark.parametrize("prompt", VAGUE_PROMPTS)
    def test_vague_prompt_never_launches_heavy_systems(
        self, planner, prompt
    ):
        intent, spec, plan = plan_for(planner, prompt)
        if "blender" not in intent.domains:
            assert "blender_asset_repair" not in plan.selected_capabilities
        assert "asset_cleanup_destructive" not in plan.selected_capabilities

    def test_mixed_intent_selects_multiple_specialists(self, planner):
        intent, spec, plan = plan_for(
            planner, "Make a photorealistic racing game intro menu.")
        assert intent.mixed
        caps = set(plan.selected_capabilities)
        assert "umg_widget_authoring" in caps
        assert len(caps & {"sequencer_cinematic", "camera_framing",
                           "material_authoring", "lighting_setup",
                           "environment_composition"}) >= 1

    def test_quality_targets_differ_by_request(self, planner):
        _, _, cinematic = plan_for(
            planner, "make a photoreal cinematic of my level")
        _, _, prototype = plan_for(planner, "block out a combat arena")
        assert (cinematic.visual_gate["score_floor"]
                > prototype.visual_gate["score_floor"])

    def test_all_missions_have_stops_and_gates(self, planner):
        for prompt, *_ in MISSIONS:
            _, _, plan = plan_for(planner, prompt)
            for step in plan.normalized_steps():
                assert step["stop_condition"] or step["phase"] in {
                    "INSPECT", "BUILD", "EDIT", "VISUAL"}
            assert plan.acceptance_tests


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
