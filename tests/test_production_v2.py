"""Production Pipeline V2 — hermetic regression tests (A–J contract).

These tests pin the anti-false-pass architecture: executor success can never
graduate a high-level mission, SceneDiff and fresh screenshot evidence are
mandatory, and the visual evaluator + bounded repair cannot be fooled by
repeats or restarts.

No Unreal instance is required: scene evidence and captures are injected.
"""
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import production_v2 as pv2


# ---------------------------------------------------------------------------
# Helpers: fixture factories
# ---------------------------------------------------------------------------

def base_scene(map_name="AIVIDO_Showcase", actors=None):
    return {
        "map": map_name,
        "actors": actors if actors is not None else ["PlayerStart"],
        "classes": {"PlayerStart": "PlayerStart"},
        "transforms": {},
        "mesh_refs": [],
        "material_refs": [],
        "lights": [],
        "cameras": [],
    }


def scene_with_cube(map_name="AIVIDO_Showcase"):
    scene = base_scene(map_name=map_name)
    scene["actors"] = ["PlayerStart", "AIVIDO_STAGE_A_Cube"]
    scene["classes"]["AIVIDO_STAGE_A_Cube"] = "StaticMeshActor"
    scene["transforms"]["AIVIDO_STAGE_A_Cube"] = {
        "location": {"x": 300.0, "y": 0.0, "z": 100.0},
        "rotation": {"x": 0.0, "y": 0.0, "z": 0.0},
        "scale": {"x": 1.0, "y": 1.0, "z": 1.0},
    }
    scene["mesh_refs"] = ["/Engine/BasicShapes/Cube.Cube"]
    scene["lights"] = ["DirectionalLight"]
    return scene


def fresh_capture(map_name="AIVIDO_Showcase", **overrides):
    data = {
        "path": "/tmp/aivido_shot.png",
        "size_bytes": 123456,
        "mtime_ns": 111,
        "map": map_name,
        "captured_at": 999.0,
        "unreal_ok": True,
        "stale": False,
    }
    data.update(overrides)
    return data


def passing_visual(**overrides):
    visual = pv2.evaluate_visual(fresh_capture(), {}, None)
    visual.update(overrides)
    return visual


def run_mission(request, *, before, after, executor_ok=True, capture=None,
                visual=None, executor=None, contract=None):
    state = pv2.ProductionMissionState(
        request,
        evidence_provider=lambda _state: after if _state in ("SNAPSHOT_AFTER", "TARGETED_REPAIR") else before,
        capture_provider=(lambda _state: capture) if capture is not None else None,
        executor=executor or (lambda _req: {"ok": executor_ok}),
        vision_reviewer=None,
        acceptance_contract=contract,
    )
    state.run()
    return state


# ---------------------------------------------------------------------------
# Lane classification (supports tests A, B)
# ---------------------------------------------------------------------------

class TestLaneClassification:
    def test_atomic_cube_command_is_atomic(self):
        assert pv2.classify_lane("create a cube") == "atomic"

    def test_atomic_spawn_sphere_is_atomic(self):
        assert pv2.classify_lane("spawn sphere") == "atomic"

    def test_complex_visual_prompt_is_production(self):
        assert pv2.classify_lane(
            "make a beautiful scene with a cube as the centerpiece"
        ) == "production"

    def test_negative_wording_is_never_atomic(self):
        for text in (
            "create a scene, do not use cubes",
            "build a room without cubes",
            "make it look good, no cubes",
        ):
            assert pv2.classify_lane(text) == "production", text
            assert not pv2.atomic_fast_path_allowed(text), text

    def test_multi_object_is_production(self):
        assert pv2.classify_lane("add a cube and a sphere") == "production"

    def test_empty_request_is_production(self):
        assert pv2.classify_lane("") == "production"

    def test_fast_path_gate_matches_classifier(self):
        assert pv2.atomic_fast_path_allowed("create a cube")
        assert not pv2.atomic_fast_path_allowed(
            "create a beautiful scene with a cube"
        )


# ---------------------------------------------------------------------------
# SceneDiff contract (supports tests B, C, F)
# ---------------------------------------------------------------------------

class TestSceneDiff:
    def test_diff_reports_added_actor(self):
        diff = pv2.scene_diff(base_scene(), scene_with_cube())
        assert "AIVIDO_STAGE_A_Cube" in diff["actors_added"]
        assert pv2.scene_diff_is_meaningful(diff)

    def test_diff_reports_removed_actor(self):
        diff = pv2.scene_diff(scene_with_cube(), base_scene())
        assert "AIVIDO_STAGE_A_Cube" in diff["actors_removed"]

    def test_diff_reports_transform_change(self):
        before = scene_with_cube()
        after = scene_with_cube()
        after["transforms"]["AIVIDO_STAGE_A_Cube"]["location"]["x"] = 900.0
        diff = pv2.scene_diff(before, after)
        assert "AIVIDO_STAGE_A_Cube" in diff["transforms_changed"]

    def test_identical_scenes_have_empty_diff(self):
        scene = scene_with_cube()
        diff = pv2.scene_diff(scene, scene)
        assert not pv2.scene_diff_is_meaningful(diff)

    def test_empty_diff_is_not_meaningful(self):
        assert not pv2.scene_diff_is_meaningful(pv2.scene_diff(None, None))

    def test_diff_has_full_contract_keys(self):
        diff = pv2.scene_diff(base_scene(), scene_with_cube())
        for key in pv2.SCENEDIFF_KEYS:
            assert key in diff

    def test_light_state_change_is_meaningful_without_actor_set_change(self):
        """A lighting re-pass keeps the same lights and only re-tunes them;
        the diff must be meaningful from value changes alone."""
        before = base_scene(actors=["AIVIDO_KeyWarm"],)
        before["lights"] = ["AIVIDO_KeyWarm"]
        before["light_state"] = {"AIVIDO_KeyWarm": {"intensity": 100.0, "color": [1.0, 1.0, 1.0]}}
        after = base_scene(actors=["AIVIDO_KeyWarm"],)
        after["lights"] = ["AIVIDO_KeyWarm"]
        after["light_state"] = {"AIVIDO_KeyWarm": {"intensity": 3200.0, "color": [1.0, 0.72, 0.42]}}
        diff = pv2.scene_diff(before, after)
        assert "AIVIDO_KeyWarm" in diff["lights_changed"]
        assert pv2.scene_diff_is_meaningful(diff)

    def test_material_state_change_is_meaningful_without_actor_set_change(self):
        before = base_scene(actors=["AIVIDO_Floor"])
        before["material_state"] = {"AIVIDO_Floor": {"0": "/Game/Old/M_Old"}}
        after = base_scene(actors=["AIVIDO_Floor"])
        after["material_state"] = {"AIVIDO_Floor": {"0": "/Game/Cinema/Materials/M_Cinema_Floor"}}
        diff = pv2.scene_diff(before, after)
        assert "AIVIDO_Floor" in diff["materials_changed"]
        assert pv2.scene_diff_is_meaningful(diff)

    def test_identical_light_state_is_not_a_change(self):
        scene = base_scene(actors=["L"])
        scene["lights"] = ["L"]
        scene["light_state"] = {"L": {"intensity": 500.0, "color": [1.0, 0.8, 0.5]}}
        diff = pv2.scene_diff(scene, scene)
        assert diff["lights_changed"] == []


# ---------------------------------------------------------------------------
# Fresh screenshot evidence (supports tests D, G)
# ---------------------------------------------------------------------------

class TestScreenshotEvidence:
    def test_fresh_capture_accepted(self):
        snapshot = {"map": "AIVIDO_Showcase", "captured_at": 100.0}
        assert pv2.screenshot_fresh(fresh_capture(), snapshot)

    def test_older_capture_is_stale(self):
        snapshot = {"map": "AIVIDO_Showcase", "captured_at": 5000.0}
        assert not pv2.screenshot_fresh(fresh_capture(captured_at=999.0), snapshot)

    def test_missing_capture_rejected(self):
        snapshot = {"map": "AIVIDO_Showcase", "captured_at": 100.0}
        assert not pv2.screenshot_fresh(None, snapshot)

    def test_map_mismatch_rejected(self):
        snapshot = {"map": "Other_Map", "captured_at": 100.0}
        assert not pv2.screenshot_fresh(fresh_capture(), snapshot)

    def test_explicit_stale_flag_rejected(self):
        snapshot = {"map": "AIVIDO_Showcase", "captured_at": 100.0}
        assert not pv2.screenshot_fresh(fresh_capture(stale=True), snapshot)

    def test_content_hash_is_stable(self):
        a = pv2.screenshot_content_hash(fresh_capture())
        b = pv2.screenshot_content_hash(fresh_capture())
        assert a == b and len(a) == 16


# ---------------------------------------------------------------------------
# Visual evaluator (supports test E)
# ---------------------------------------------------------------------------

class TestVisualEvaluator:
    def test_evaluator_scores_all_requested_categories(self):
        result = pv2.evaluate_visual(fresh_capture(), {}, None)
        for cat in (
            "exposure", "composition", "focal_point", "depth",
            "material_quality", "lighting", "clutter",
            "placeholder_prevalence", "framing", "target_match",
        ):
            assert cat in result["scores"]

    def test_black_frame_penalizes_exposure(self):
        result = pv2.evaluate_visual(fresh_capture(), {"issues": ["black_frame"]}, None)
        assert result["scores"]["exposure"] < 8.0
        assert not result["accepted"]

    def test_vision_review_is_advisory_only(self):
        clean = pv2.evaluate_visual(fresh_capture(), {}, None)
        reviewed = pv2.evaluate_visual(
            fresh_capture(), {}, {"score": 9, "pass": True, "issues": []}
        )
        # Advisory review never executes anything; it only annotates scores.
        assert reviewed["scores"] == clean["scores"]
        assert "vision_advisory" in reviewed["evaluator"]

    def test_clean_frame_is_accepted(self):
        assert pv2.evaluate_visual(fresh_capture(), {}, None)["accepted"]


# ---------------------------------------------------------------------------
# Graduation gates (tests C, D, E, F)
# ---------------------------------------------------------------------------

class TestGraduationGates:
    def _gates(self, **overrides):
        kwargs = dict(
            executor_success=True,
            diff=pv2.scene_diff(base_scene(), scene_with_cube()),
            capture=fresh_capture(),
            snapshot_after={"map": "AIVIDO_Showcase", "captured_at": 100.0, "unreal_ok": True},
            visual=passing_visual(),
            acceptance_contract={"present": True, "satisfied": True},
        )
        kwargs.update(overrides)
        return pv2.graduation_gates(**kwargs)

    def test_all_gates_pass_gives_pass(self):
        gates = self._gates()
        assert gates["passed"] is True
        for key in (
            "execution_gate", "scene_diff_gate", "technical_unreal_gate",
            "evidence_gate", "visual_gate", "acceptance_contract",
        ):
            assert gates[key] is True

    def test_executor_success_alone_does_not_pass(self):
        gates = self._gates(diff=pv2.scene_diff(base_scene(), base_scene()))
        assert gates["execution_gate"] is True
        assert gates["scene_diff_gate"] is False
        assert gates["passed"] is False

    def test_empty_scenediff_never_passes(self):
        gates = self._gates(diff=pv2.scene_diff(base_scene(), base_scene()))
        assert gates["passed"] is False

    def test_missing_screenshot_never_visual_pass(self):
        gates = self._gates(capture=None)
        assert gates["evidence_gate"] is False
        assert gates["passed"] is False

    def test_visual_reject_blocks_pass(self):
        gates = self._gates(visual={**passing_visual(), "accepted": False})
        assert gates["visual_gate"] is False
        assert gates["passed"] is False

    def test_stale_screenshot_rejected(self):
        gates = self._gates(
            snapshot_after={"map": "AIVIDO_Showcase", "captured_at": 9999.0, "unreal_ok": True}
        )
        assert gates["evidence_gate"] is False
        assert gates["passed"] is False


# ---------------------------------------------------------------------------
# State machine end-to-end (tests A–J)
# ---------------------------------------------------------------------------

class TestProductionStateMachine:
    def test_atomic_cube_command_stays_atomic(self):
        """Test A: atomic request runs one op and never runs the machine."""
        assert pv2.classify_lane("create a cube") == "atomic"
        assert pv2.atomic_fast_path_allowed("create a cube")

    def test_complex_visual_never_uses_fast_path(self):
        """Test B: cube-worded mission is production; fast path forbidden."""
        state = run_mission(
            "make a beautiful scene with a cube as the centerpiece",
            before=base_scene(),
            after=scene_with_cube(),
            capture=fresh_capture(),
        )
        assert state.lane == "production"
        assert state.verdict == "PASS"
        assert pv2.atomic_fast_path_allowed(
            "make a beautiful scene with a cube as the centerpiece"
        ) is False

    def test_empty_scenediff_means_no_pass(self):
        """Test C: executor succeeded but nothing changed -> BLOCKED path."""
        state = run_mission(
            "redesign the room",
            before=base_scene(),
            after=base_scene(),
            capture=fresh_capture(),
        )
        assert state.diff_meaningful is False
        assert state.verdict != "PASS"
        assert state.gates["scene_diff_gate"] is False

    def test_missing_screenshot_means_no_visual_pass(self):
        """Test D: no capture -> evidence gate fails, no PASS."""
        state = run_mission(
            "redesign the room",
            before=base_scene(),
            after=scene_with_cube(),
            capture=None,
        )
        assert state.verdict != "PASS"
        assert state.gates["evidence_gate"] is False

    def test_visual_evaluator_reject_blocks(self):
        """Test E: evaluator rejects the frame -> no PASS, repair attempted."""
        calls = {"n": 0}

        def analyzer(_capture):
            calls["n"] += 1
            return {"issues": ["black_frame"]}

        state = pv2.ProductionMissionState(
            "redesign the room",
            evidence_provider=lambda s: scene_with_cube() if s in ("SNAPSHOT_AFTER", "TARGETED_REPAIR") else base_scene(),
            capture_provider=lambda s: fresh_capture(),
            executor=lambda r: {"ok": True},
            frame_analyzer=analyzer,
        )
        state.run()
        assert state.verdict != "PASS" or state.repair_iterations > 0
        assert state.visual["accepted"] is False

    def test_all_gates_pass_graduates(self):
        """Test F: everything green -> GRADUATE with PASS."""
        state = run_mission(
            "redesign the room",
            before=base_scene(),
            after=scene_with_cube(),
            capture=fresh_capture(),
        )
        assert state.state == "GRADUATE"
        assert state.verdict == "PASS"
        assert all(state.gates[k] for k in (
            "execution_gate", "scene_diff_gate", "technical_unreal_gate",
            "evidence_gate", "visual_gate", "acceptance_contract",
        ))

    def test_stale_screenshot_never_graduates(self):
        """Test G: capture older than snapshot_after is rejected."""
        state = run_mission(
            "redesign the room",
            before=base_scene(),
            after=scene_with_cube(),
            capture=fresh_capture(captured_at=1.0),
        )
        # snapshot_after is stamped 'now' (>1.0), so the capture is stale.
        assert state.gates["evidence_gate"] is False
        assert state.verdict != "PASS"

    def test_max_repair_count_enforced(self):
        """Test H: repair stops at 3 iterations and BLOCKs."""
        state = pv2.ProductionMissionState(
            "redesign the room",
            evidence_provider=lambda s: scene_with_cube(),
            capture_provider=lambda s: fresh_capture(),
            executor=lambda r: {"ok": True},
            frame_analyzer=lambda c: {"issues": ["black_frame"]},
        )
        state.run()
        assert state.repair_iterations <= pv2.ProductionMissionState.MAX_REPAIRS
        assert state.state == "BLOCKED"
        assert state.blocker in ("REPAIR_BUDGET_EXHAUSTED", "REPEATED_FAILURE_SIGNATURE")

    def test_repeated_failure_changes_strategy_or_blocks(self):
        """Test I: identical repeated failure signature BLOCKs, never PASSes."""
        state = pv2.ProductionMissionState(
            "redesign the room",
            evidence_provider=lambda s: scene_with_cube(),
            capture_provider=lambda s: fresh_capture(),
            executor=lambda r: {"ok": True},
            frame_analyzer=lambda c: {"issues": ["black_frame"]},
        )
        state.run()
        assert state.verdict != "PASS"
        assert state.state == "BLOCKED"

    def test_restart_retry_cannot_create_false_pass(self):
        """Test I (restart variant): a fresh state machine replaying the same
        failed evidence still cannot graduate."""
        for _ in range(2):
            state = run_mission(
                "redesign the room",
                before=base_scene(),
                after=base_scene(),
                capture=fresh_capture(),
            )
            assert state.verdict != "PASS"

    def test_executor_failure_never_graduates(self):
        state = run_mission(
            "redesign the room",
            before=base_scene(),
            after=scene_with_cube(),
            executor_ok=False,
            capture=fresh_capture(),
        )
        assert state.verdict is None
        assert state.state == "BLOCKED"
        assert state.blocker == "EXECUTOR_FAILED"


class TestValueAwareSceneDiffFromValueStates:
    """Run 13 regression: value-state maps drive the property-change deltas."""

    def _snap(self, mat=None, intensity=None):
        lights = {}
        if intensity is not None:
            lights["AIVIDO_KeyWarm"] = {"intensity": intensity, "color": [1.0, 0.72, 0.42]}
        mats = {"AIVIDO_Floor": {"0": mat}} if mat else {}
        return {
            "map": "/Game/AIVIDO_Showcase.AIVIDO_Showcase",
            "actors": ["AIVIDO_Floor", "AIVIDO_KeyWarm"],
            "classes": {"AIVIDO_Floor": "StaticMeshActor", "AIVIDO_KeyWarm": "PointLight"},
            "transforms": {
                "AIVIDO_Floor": {"location": {"x": 0, "y": 0, "z": 0},
                                 "rotation": {"pitch": 0, "yaw": 0, "roll": 0},
                                 "scale": {"x": 1, "y": 1, "z": 1}},
                "AIVIDO_KeyWarm": {"location": {"x": 1, "y": 2, "z": 3},
                                   "rotation": {"pitch": 0, "yaw": 0, "roll": 0},
                                   "scale": {"x": 1, "y": 1, "z": 1}},
            },
            "mesh_refs": [], "material_refs": [], "lights": list(lights), "cameras": [],
            "light_state": lights, "material_state": mats, "read_errors": [],
        }

    def test_material_state_change_is_meaningful(self):
        before = self._snap(mat="/Game/Old/M_Old")
        after = self._snap(mat="/Game/Cinema/Materials/M_Cinema_Floor")
        d = pv2.scene_diff(before, after)
        assert "AIVIDO_Floor" in d["materials_changed"]
        assert not d["empty"] if "empty" in d else True

    def test_light_state_change_is_meaningful(self):
        before = self._snap(intensity=1000.0)
        after = self._snap(intensity=3200.0)
        d = pv2.scene_diff(before, after)
        assert "AIVIDO_KeyWarm" in d["lights_changed"]

    def test_identical_value_states_are_empty(self):
        snap = self._snap(mat="/Game/X", intensity=3200.0)
        d = pv2.scene_diff(snap, dict(snap))
        assert d["materials_changed"] == []
        assert d["lights_changed"] == []
