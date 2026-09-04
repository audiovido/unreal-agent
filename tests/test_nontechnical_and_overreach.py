"""UNREAL CODER — Phases G + H: non-technical user mode + anti-overreach.

Phase G: vague, non-technical prompts produce safe, executable, validated
plans with a simple user-facing result contract — users never choose tools.

Phase H: every mission does the MINIMUM sufficient work — a UI request never
launches Blender, a material tweak never routes multiplayer, a lighting fix
never rebuilds gameplay, sequencer work never rebuilds world systems, and
asset cleanup never touches unrelated map logic.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.observability import user_result_contract
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


# ---------------------------------------------------------------------------
# Phase G — non-technical user mode
# ---------------------------------------------------------------------------

BEGINNER_PROMPTS = [
    "make it look better",
    "make me a menu",
    "make a cool room",
    "make this like a movie",
    "fix this asset",
    "make a little game",
]


class TestNontechnicalMode:
    @pytest.mark.parametrize("prompt", BEGINNER_PROMPTS)
    def test_beginner_prompt_produces_executable_plan(self, planner, prompt):
        intent, spec, plan = plan_for(planner, prompt)
        assert intent.mode == "execute", prompt
        assert spec.requirements, prompt
        assert plan.normalized_steps(), prompt
        # Deterministic validation is always part of the plan.
        kinds = {r["kind"] for r in spec.requirements}
        assert "validation" in kinds, prompt

    @pytest.mark.parametrize("prompt", BEGINNER_PROMPTS)
    def test_beginner_prompt_never_asks_user_to_choose_tools(
            self, planner, prompt):
        """The plan resolves every tool itself; nothing is left undefined."""
        _, _, plan = plan_for(planner, prompt)
        for step in plan.normalized_steps():
            assert step.get("preferred_tool"), prompt

    def test_beginner_result_contract_is_simple(self, planner):
        """The Phase T contract exposes plain-language fields only."""
        from core.mission import MissionState
        state = MissionState(mission_id="mission_g1", prompt="make it better")
        state.intent = {
            "domains": ["environment_art", "lighting"],
            "primary_domain": "environment_art",
            "quality": "high",
            "deliverables": ["polished environment"],
        }
        state.plan = {"steps": [
            {"step_id": "s1", "preferred_tool": "spawn_actor", "phase": "EDIT"},
            {"step_id": "s2", "preferred_tool": "save_level", "phase": "BUILD"},
        ]}
        state.completed_step_ids = ["s1", "s2"]
        state.verdict = "PASS"
        state.why = "All 2 steps verified."
        contract = user_result_contract(state)
        for key in ("status", "what_i_understood", "what_i_did", "result",
                    "evidence", "warnings", "remaining_issues", "mission_id"):
            assert key in contract, key
        assert contract["status"] == "PASS"
        assert "spawn" not in contract["what_i_understood"].lower()
        assert contract["what_i_did"].startswith("Executed")

    def test_quality_defaults_safe_for_beginners(self, planner):
        """Vague prompt never escalates to photoreal or cinematic floors."""
        intent, _, plan = plan_for(planner, "make it look better")
        assert intent.quality not in ("photoreal", "cinematic")


# ---------------------------------------------------------------------------
# Phase H — anti-overreach
# ---------------------------------------------------------------------------

class TestAntiOverreach:
    def test_ui_request_never_invokes_blender(self, planner):
        intent, spec, plan = plan_for(
            planner, "Create a polished main menu with Play and Quit.")
        assert "ui" in intent.domains
        assert "blender" not in intent.domains
        assert "blender_asset_repair" not in plan.selected_capabilities
        assert "blender_asset_creation" not in plan.selected_capabilities
        assert "blender" not in {s.get("domain")
                                 for s in spec.requirements} | set()

    def test_material_tweak_never_routes_multiplayer(self, planner):
        intent, spec, plan = plan_for(
            planner, "make the floor material shinier")
        kinds = {r["kind"] for r in spec.requirements}
        assert "networking" not in kinds
        caps = set(plan.selected_capabilities)
        assert not caps & {"multiplayer", "network_setup"}

    def test_simple_lighting_request_does_not_rebuild_gameplay(
            self, planner):
        intent, spec, plan = plan_for(planner, "brighten up my scene a bit")
        assert "lighting" in intent.domains
        caps = set(plan.selected_capabilities)
        assert "blueprint_authoring" not in caps
        assert "gameplay_smoke" not in caps
        kinds = {r["kind"] for r in spec.requirements}
        assert "gameplay" not in kinds

    def test_sequencer_request_does_not_rebuild_world(self, planner):
        intent, spec, plan = plan_for(
            planner, "add a 6 second camera flythrough of this scene")
        assert "cinematics" in intent.domains
        caps = set(plan.selected_capabilities)
        assert caps & {"sequencer_cinematic", "camera_framing"}
        assert "level_creation" not in caps
        assert "terrain_setup" not in caps
        assert "foliage_distribution" not in caps

    def test_asset_cleanup_scoped_to_assets(self, planner):
        intent, spec, plan = plan_for(
            planner, "delete the unused test assets in /Game/Imported")
        assert "asset_pipeline" in intent.domains
        # Cleanup is flagged destructive and never drags in world systems.
        caps = set(plan.selected_capabilities)
        assert "asset_cleanup_destructive" in caps
        assert "level_creation" not in caps
        assert "environment_composition" not in caps

    def test_archviz_never_adds_gameplay(self, planner):
        intent, spec, plan = plan_for(
            planner,
            "Create a clean architectural presentation of this room.")
        assert "archviz" in intent.domains
        caps = set(plan.selected_capabilities)
        assert "blueprint_authoring" not in caps
        assert "gameplay_smoke" not in caps

    def test_excluded_scope_is_recorded_not_dropped(self, planner):
        spec = expand_requirements(
            interpret_intent("just tweak the lighting, don't touch gameplay"))
        excluded = list(spec.excluded)
        kinds = {r["kind"] for r in spec.requirements}
        assert "gameplay" not in kinds
        assert excluded, "excluded scope must be recorded"

    def test_vague_prompt_minimum_sufficient_work(self, planner):
        """'make it prettier' does env+lighting polish, not everything."""
        intent, spec, plan = plan_for(planner, "make it prettier")
        caps = set(plan.selected_capabilities)
        assert caps <= {
            "environment_composition", "lighting_setup", "material_authoring",
            "actor_staging", "visual_quality_gate", "camera_framing",
        } or not caps & {"blueprint_authoring", "gameplay_smoke",
                         "asset_cleanup_destructive", "terrain_setup",
                         "foliage_distribution", "media_playback"}
        kinds = {r["kind"] for r in spec.requirements}
        assert not kinds & {"networking", "packaging"}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
