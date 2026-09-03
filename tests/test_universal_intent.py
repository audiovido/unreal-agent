"""UNREAL CODER universal layers — deterministic unit tests (L1/L2)."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.universal_intent import (
    detect_domains,
    expand_requirements,
    interpret_and_expand,
    interpret_intent,
)


class TestIntentRouter:
    def test_main_menu_routes_ui(self):
        intent = interpret_intent("Make me a beautiful main menu.")
        assert intent.mode == "execute"
        assert "ui" in intent.domains
        assert intent.needs_ui is True
        assert intent.needs_visual_validation is True

    def test_photoreal_racing_menu_is_mixed(self):
        intent = interpret_intent(
            "Make a photorealistic racing game intro menu."
        )
        assert intent.mixed
        assert "ui" in intent.domains
        assert intent.quality in {"photoreal", "cinematic", "high"}
        assert intent.needs_visual_validation

    def test_blockout_is_prototype_quality(self):
        intent = interpret_intent("block out a combat arena")
        assert intent.quality == "prototype"

    def test_photoreal_cinematic_quality_inference(self):
        intent = interpret_intent("make a photoreal cinematic of the scene")
        assert intent.quality in {"photoreal", "cinematic"}
        assert intent.needs_render

    def test_vague_prompt_detected(self):
        intent = interpret_intent("make it prettier")
        assert intent.vague
        assert intent.mode == "execute"

    def test_read_only_stays_chat(self):
        intent = interpret_intent("list the actors in the level")
        assert intent.mode in {"chat", "execute"}
        assert intent.read_only or intent.mode == "chat"

    def test_mobile_downgrades_cinematic(self):
        intent = interpret_intent(
            "make a cinematic main menu for mobile"
        )
        assert intent.quality != "cinematic"
        assert any("mobile" in p for p in intent.platforms)
        assert intent.warnings

    def test_destructive_marker_flagged(self):
        intent = interpret_intent("delete all assets in the project")
        assert intent.destructive
        assert intent.warnings

    def test_domains_include_forest_world(self):
        domains = detect_domains("Make me a realistic forest.")
        assert any(d in domains for d in ("world_building", "environment_art"))


class TestRequirementExpander:
    def test_vague_expands_to_minimum_polish_set(self):
        intent, spec = interpret_and_expand("make it prettier")
        kinds = {r["kind"] for r in spec.requirements}
        assert {"environment", "lighting", "materials"} <= kinds
        assert any(r["kind"] == "validation" for r in spec.requirements)
        assert spec.defaults_applied

    def test_ui_request_does_not_launch_blender(self):
        intent, spec = interpret_and_expand(
            "Create a polished character selection screen"
        )
        kinds = {r["kind"] for r in spec.requirements}
        assert "ui" in kinds
        assert "assets" not in kinds
        assert any("Blender" in x for x in spec.excluded)

    def test_material_tweak_no_multiplayer(self):
        intent, spec = interpret_and_expand(
            "fix the material on this asset"
        )
        kinds = {r["kind"] for r in spec.requirements}
        assert "materials" in kinds
        assert any("Networking" in x or "multiplayer" in x.lower()
                   for x in spec.excluded)

    def test_cinematic_gets_quality_gate(self):
        intent, spec = interpret_and_expand(
            "make a cinematic trailer of my level"
        )
        kinds = {r["kind"] for r in spec.requirements}
        assert "sequencer" in kinds
        assert any(r["id"] == "quality_gate" for r in spec.requirements)

    def test_destructive_requires_backup(self):
        intent, spec = interpret_and_expand(
            "delete all assets in the project folder"
        )
        assert any(r["id"] == "backup" for r in spec.requirements)
        assert any(r["kind"] == "safety" for r in spec.requirements)

    def test_chat_mode_no_mutation(self):
        intent, spec = interpret_and_expand("What is a GameMode?")
        kinds = {r["kind"] for r in spec.requirements}
        assert kinds == {"answer"}

    def test_forest_expands_world_building(self):
        intent, spec = interpret_and_expand("Make me a realistic forest.")
        kinds = {r["kind"] for r in spec.requirements}
        assert "world" in kinds
        assert any(r["kind"] == "validation" for r in spec.requirements)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
