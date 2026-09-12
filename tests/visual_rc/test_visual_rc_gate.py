#!/usr/bin/env python3
"""Hermetic tests for AIVIDO Visual RC Acceptance Gate.

These tests verify the gate logic and deterministic criteria without requiring
live Unreal, backend, or bridge. All external dependencies are mocked or
tested via static analysis and synthetic scene evidence.
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "visual_rc"))

from scene_criteria import (
    SceneEvidence,
    SceneActor,
    run_all_deterministic_checks,
    check_heidi_hero_focal_point,
    check_minimum_three_workers,
    check_distinct_worker_stations_roles,
    check_worker_animation_states,
    check_heidi_to_worker_task_handoff,
    check_no_placeholder_heavy,
    check_scene_actor_integrity,
    check_fresh_evidence,
    check_no_stale_evidence,
    check_western_frontier_readability,
    REQUIRED_ACTOR_LABELS,
    MIN_HEIDI_COUNT,
    MIN_WORKER_COUNT,
    MIN_STATION_COUNT,
    WORKER_ROLE_MARKERS,
    REQUIRED_WORKER_STATES,
    TASK_HANDOFF_MARKERS,
    PLACEHOLDER_INDICATORS,
    REQUIRED_MAP_SUBSTRING,
    MAX_EVIDENCE_AGE_SECONDS,
    REQUIRED_CAPTURE_METADATA_KEYS,
)


def make_actor(name: str, label: str, class_name: str = "", readable: bool = True,
               location: dict | None = None) -> SceneActor:
    """Helper to create a SceneActor with defaults."""
    return SceneActor(
        name=name,
        label=label,
        class_name=class_name,
        location=location or {"x": 0.0, "y": 0.0, "z": 0.0},
        rotation={"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
        scale={"x": 1.0, "y": 1.0, "z": 1.0},
        readable=readable,
    )


def make_valid_evidence(**overrides) -> SceneEvidence:
    """Create a valid baseline SceneEvidence for testing."""
    actors = [
        make_actor("AIVIDO_Heidi_01", "AIVIDO_Heidi", "BP_HeidiCharacter"),
        make_actor("Worker_Miner_01", "Worker_Miner", "BP_Worker_Miner"),
        make_actor("Worker_Engineer_01", "Worker_Engineer", "BP_Worker_Engineer"),
        make_actor("Worker_Prospector_01", "Worker_Prospector", "BP_Worker_Prospector"),
        make_actor("Station_Mining_01", "Station_Mining", "BP_Station_Mining"),
        make_actor("Station_Repair_01", "Station_Repair", "BP_Station_Repair"),
        make_actor("Station_Comms_01", "Station_Comms", "BP_Station_Comms"),
        make_actor("Wall_Frontier_01", "Wall_Frontier", "SM_Wall_Frontier"),
        make_actor("Floor_Frontier_01", "Floor_Frontier", "SM_Floor_Frontier"),
        make_actor("Prop_Crate_01", "Prop_Crate", "SM_Crate"),
        make_actor("Prop_Barrel_01", "Prop_Barrel", "SM_Barrel"),
        make_actor("Prop_Lantern_01", "Prop_Lantern", "SM_Lantern"),
        make_actor("Prop_Toolbox_01", "Prop_Toolbox", "SM_Toolbox"),
    ]
    capture_meta = {
        "frame": "shot_001.png",
        "path": "/evidence/shot_001.png",
        "sha256": "a" * 64,
        "size_bytes": 1024000,
        "captured_at_epoch": time.time(),
        "map": "/Game/AIVIDO_Showcase",
        "source": "bridge",
        "worker_states": {
            "Worker_Miner_01": "IDLE",
            "Worker_Engineer_01": "WALK",
            "Worker_Prospector_01": "WORK",
        },
        "task_handoff": True,
    }
    capture_meta.update(overrides.get("capture_meta", {}))

    return SceneEvidence(
        map_name=overrides.get("map_name", "/Game/AIVIDO_Showcase"),
        actors=overrides.get("actors", actors),
        captured_at_epoch=overrides.get("captured_at_epoch", time.time()),
        capture_metadata=capture_meta,
    )


class TestDeterministicCriteria(unittest.TestCase):
    """Tests for individual deterministic check functions."""

    def test_heidi_hero_focal_point_pass(self):
        evidence = make_valid_evidence()
        result = check_heidi_hero_focal_point(evidence)
        self.assertTrue(result.passed, f"Expected PASS, got issues: {result.issues}")

    def test_heidi_hero_focal_point_fail_missing(self):
        evidence = make_valid_evidence(actors=[
            a for a in make_valid_evidence().actors if "heidi" not in a.label.lower()
        ])
        result = check_heidi_hero_focal_point(evidence)
        self.assertFalse(result.passed)
        self.assertIn("NO_HEIDI_ACTOR_FOUND", result.issues[0])

    def test_heidi_hero_focal_point_fail_multiple(self):
        actors = make_valid_evidence().actors + [
            make_actor("AIVIDO_Heidi_02", "AIVIDO_Heidi", "BP_HeidiCharacter"),
        ]
        evidence = make_valid_evidence(actors=actors)
        result = check_heidi_hero_focal_point(evidence)
        self.assertFalse(result.passed)
        self.assertIn("MULTIPLE_HEIDI_ACTORS", result.issues[0])

    def test_heidi_hero_focal_point_fail_phantom(self):
        actors = [
            make_actor("AIVIDO_Heidi_01", "AIVIDO_Heidi", "BP_HeidiCharacter", readable=False),
        ] + [a for a in make_valid_evidence().actors if "heidi" not in a.label.lower()]
        evidence = make_valid_evidence(actors=actors)
        result = check_heidi_hero_focal_point(evidence)
        self.assertFalse(result.passed)
        self.assertIn("HEIDI_PHANTOM_HANDLE", result.issues[0])

    def test_min_three_workers_pass(self):
        evidence = make_valid_evidence()
        result = check_minimum_three_workers(evidence)
        self.assertTrue(result.passed, f"Expected PASS, got issues: {result.issues}")

    def test_min_three_workers_fail_insufficient(self):
        actors = [a for a in make_valid_evidence().actors if "worker" not in a.label.lower()][:8]
        actors += [
            make_actor("Worker_Only_01", "Worker_Only", "BP_Worker"),
        ]
        evidence = make_valid_evidence(actors=actors)
        result = check_minimum_three_workers(evidence)
        self.assertFalse(result.passed)
        self.assertIn("INSUFFICIENT_WORKERS", result.issues[0])

    def test_min_three_workers_fail_duplicates(self):
        actors = make_valid_evidence().actors[:7]  # 1 heidi + 2 workers + stations + env
        actors += [
            make_actor("Worker_Miner_01", "Worker_Miner", "BP_Worker_Miner"),  # duplicate name
        ]
        evidence = make_valid_evidence(actors=actors)
        result = check_minimum_three_workers(evidence)
        self.assertFalse(result.passed)
        self.assertIn("DUPLICATE_WORKER_NAMES", result.issues[0])

    def test_distinct_worker_stations_roles_pass_stations(self):
        evidence = make_valid_evidence()
        result = check_distinct_worker_stations_roles(evidence)
        self.assertTrue(result.passed, f"Expected PASS, got issues: {result.issues}")

    def test_distinct_worker_stations_roles_pass_roles(self):
        actors = [
            make_actor("AIVIDO_Heidi_01", "AIVIDO_Heidi", "BP_HeidiCharacter"),
            make_actor("Worker_Miner_01", "Worker_Miner", "BP_Worker"),
            make_actor("Worker_Engineer_01", "Worker_Engineer", "BP_Worker"),
            make_actor("Worker_Prospector_01", "Worker_Prospector", "BP_Worker"),
        ] + [make_actor(f"Env_{i}", f"Env_{i}", f"SM_Env") for i in range(5)]
        evidence = make_valid_evidence(actors=actors)
        result = check_distinct_worker_stations_roles(evidence)
        self.assertTrue(result.passed, f"Expected PASS, got issues: {result.issues}")

    def test_distinct_worker_stations_roles_fail(self):
        actors = [
            make_actor("AIVIDO_Heidi_01", "AIVIDO_Heidi", "BP_HeidiCharacter"),
            make_actor("Worker_Generic_01", "Worker_Generic", "BP_Worker"),
            make_actor("Worker_Generic_02", "Worker_Generic", "BP_Worker"),
        ] + [make_actor(f"Env_{i}", f"Env_{i}", "SM_Env") for i in range(5)]
        evidence = make_valid_evidence(actors=actors)
        result = check_distinct_worker_stations_roles(evidence)
        self.assertFalse(result.passed)
        self.assertIn("INSUFFICIENT_STATIONS_ROLES", result.issues[0])

    def test_worker_animation_states_pass(self):
        evidence = make_valid_evidence()
        result = check_worker_animation_states(evidence)
        self.assertTrue(result.passed, f"Expected PASS, got issues: {result.issues}")

    def test_worker_animation_states_fail_missing(self):
        capture_meta = {"worker_states": {"Worker_01": "IDLE"}}
        evidence = make_valid_evidence(capture_meta=capture_meta)
        result = check_worker_animation_states(evidence)
        self.assertFalse(result.passed)
        self.assertIn("MISSING_WORKER_STATES", result.issues[0])

    def test_heidi_worker_task_handoff_pass_metadata(self):
        evidence = make_valid_evidence()
        result = check_heidi_to_worker_task_handoff(evidence)
        self.assertTrue(result.passed, f"Expected PASS, got issues: {result.issues}")

    def test_heidi_worker_task_handoff_pass_actor_marker(self):
        actors = make_valid_evidence().actors + [
            make_actor("Task_Handoff_01", "Task_Handoff", "BP_TaskHandoff"),
        ]
        evidence = make_valid_evidence(actors=actors, capture_meta={})
        result = check_heidi_to_worker_task_handoff(evidence)
        self.assertTrue(result.passed, f"Expected PASS, got issues: {result.issues}")

    def test_heidi_worker_task_handoff_fail(self):
        evidence = make_valid_evidence(capture_meta={"task_handoff": False, "worker_states": {}})
        result = check_heidi_to_worker_task_handoff(evidence)
        self.assertFalse(result.passed)
        self.assertIn("NO_TASK_HANDOFF_INDICATORS_FOUND", result.issues[0])

    def test_no_placeholder_heavy_pass(self):
        evidence = make_valid_evidence()
        result = check_no_placeholder_heavy(evidence)
        self.assertTrue(result.passed, f"Expected PASS, got issues: {result.issues}")

    def test_no_placeholder_heavy_fail_critical_placeholder(self):
        actors = [
            make_actor("Cube_01", "Heidi", "Cube"),  # Critical actor is placeholder
            make_actor("Worker_01", "Worker", "BP_Worker"),
            make_actor("Worker_02", "Worker", "BP_Worker"),
            make_actor("Worker_03", "Worker", "BP_Worker"),
        ] + [make_actor(f"Env_{i}", f"Env_{i}", "SM_Env") for i in range(5)]
        evidence = make_valid_evidence(actors=actors)
        result = check_no_placeholder_heavy(evidence)
        self.assertFalse(result.passed)
        self.assertIn("CRITICAL_ACTORS_ARE_PLACEHOLDERS", result.issues[0])

    def test_no_placeholder_heavy_fail_too_many(self):
        actors = make_valid_evidence().actors[:4]  # heidi + 3 workers
        actors += [make_actor(f"Cube_{i}", f"Cube_{i}", "Cube") for i in range(5)]
        evidence = make_valid_evidence(actors=actors)
        result = check_no_placeholder_heavy(evidence)
        self.assertFalse(result.passed)
        self.assertIn("TOO_MANY_PLACEHOLDERS", result.issues[0])

    def test_no_placeholder_heavy_fail_ratio(self):
        # 4 critical + 2 placeholders = 6 total, ratio = 2/6 = 33% > 30%
        actors = make_valid_evidence().actors[:4]  # heidi + 3 workers
        actors += [make_actor(f"Cube_{i}", f"Cube_{i}", "Cube") for i in range(2)]
        evidence = make_valid_evidence(actors=actors)
        result = check_no_placeholder_heavy(evidence)
        self.assertFalse(result.passed)
        self.assertIn("PLACEHOLDER_RATIO_TOO_HIGH", result.issues[0])

    def test_scene_actor_integrity_pass(self):
        evidence = make_valid_evidence()
        result = check_scene_actor_integrity(evidence)
        self.assertTrue(result.passed, f"Expected PASS, got issues: {result.issues}")

    def test_scene_actor_integrity_fail_wrong_map(self):
        evidence = make_valid_evidence(map_name="/Game/WrongMap")
        result = check_scene_actor_integrity(evidence)
        self.assertFalse(result.passed)
        self.assertIn("WRONG_MAP", result.issues[0])

    def test_scene_actor_integrity_fail_phantom(self):
        actors = make_valid_evidence().actors[:1]
        actors[0] = make_actor("Phantom", "Phantom", "BP_Phantom", readable=False)
        actors += make_valid_evidence().actors[1:]
        evidence = make_valid_evidence(actors=actors)
        result = check_scene_actor_integrity(evidence)
        self.assertFalse(result.passed)
        self.assertIn("PHANTOM_HANDLE", result.issues[0])

    def test_scene_actor_integrity_fail_invalid_transform(self):
        actors = [
            make_actor("BadTransform", "BadTransform", "BP_Bad", location={"x": float("nan"), "y": 0, "z": 0}),
        ] + make_valid_evidence().actors[1:]
        evidence = make_valid_evidence(actors=actors)
        result = check_scene_actor_integrity(evidence)
        self.assertFalse(result.passed)
        self.assertIn("INVALID_TRANSFORM", result.issues[0])

    def test_scene_actor_integrity_fail_duplicate_critical(self):
        actors = make_valid_evidence().actors + [
            make_actor("AIVIDO_Heidi_01", "AIVIDO_Heidi_Dup", "BP_HeidiCharacter"),  # duplicate name
        ]
        evidence = make_valid_evidence(actors=actors)
        result = check_scene_actor_integrity(evidence)
        self.assertFalse(result.passed)
        self.assertIn("DUPLICATE_CRITICAL_NAME", result.issues[0])

    def test_fresh_evidence_pass(self):
        evidence = make_valid_evidence()
        result = check_fresh_evidence(evidence.capture_metadata)
        self.assertTrue(result.passed, f"Expected PASS, got issues: {result.issues}")

    def test_fresh_evidence_fail_missing_metadata(self):
        result = check_fresh_evidence({})
        self.assertFalse(result.passed)
        self.assertIn("MISSING_CAPTURE_METADATA", result.issues[0])

    def test_fresh_evidence_fail_missing_keys(self):
        meta = {"frame": "test.png", "path": "/test.png"}
        result = check_fresh_evidence(meta)
        self.assertFalse(result.passed)
        self.assertIn("MISSING_METADATA_KEYS", result.issues[0])

    def test_fresh_evidence_fail_stale(self):
        meta = dict(make_valid_evidence().capture_metadata)
        meta["captured_at_epoch"] = time.time() - MAX_EVIDENCE_AGE_SECONDS - 100
        result = check_fresh_evidence(meta)
        self.assertFalse(result.passed)
        self.assertIn("STALE_EVIDENCE", result.issues[0])

    def test_no_stale_evidence_pass(self):
        evidence = make_valid_evidence()
        prior = {"different_hash"}
        result = check_no_stale_evidence(evidence, prior)
        self.assertTrue(result.passed, f"Expected PASS, got issues: {result.issues}")

    def test_no_stale_evidence_fail_hash_match(self):
        evidence = make_valid_evidence()
        prior = {evidence.capture_metadata["sha256"]}
        result = check_no_stale_evidence(evidence, prior)
        self.assertFalse(result.passed)
        self.assertIn("STALE_FRAME_DETECTED", result.issues[0])

    def test_no_stale_evidence_fail_metadata_flag(self):
        meta = dict(make_valid_evidence().capture_metadata)
        meta["stale"] = True
        evidence = make_valid_evidence(capture_meta=meta)
        result = check_no_stale_evidence(evidence, set())
        self.assertFalse(result.passed)
        self.assertIn("CAPTURE_METADATA_FLAGS_STALE", result.issues[0])

    def test_western_frontier_readability_pass(self):
        evidence = make_valid_evidence()
        result = check_western_frontier_readability(evidence)
        self.assertTrue(result.passed, f"Expected PASS, got issues: {result.issues}")

    def test_western_frontier_readability_fail_insufficient_env(self):
        actors = [
            make_actor("AIVIDO_Heidi_01", "AIVIDO_Heidi", "BP_HeidiCharacter"),
            make_actor("Worker_01", "Worker", "BP_Worker"),
            make_actor("Worker_02", "Worker", "BP_Worker"),
            make_actor("Worker_03", "Worker", "BP_Worker"),
        ] + [make_actor(f"Env_{i}", f"Env_{i}", "SM_Env") for i in range(3)]  # only 3 env
        evidence = make_valid_evidence(actors=actors)
        result = check_western_frontier_readability(evidence)
        self.assertFalse(result.passed)
        self.assertIn("INSUFFICIENT_ENVIRONMENT_ACTORS", result.issues[0])

    def test_western_frontier_readability_fail_class_dominance(self):
        actors = [
            make_actor("AIVIDO_Heidi_01", "AIVIDO_Heidi", "BP_HeidiCharacter"),
            make_actor("Worker_01", "Worker", "BP_Worker"),
            make_actor("Worker_02", "Worker", "BP_Worker"),
            make_actor("Worker_03", "Worker", "BP_Worker"),
        ] + [make_actor(f"Cube_{i}", f"Cube_{i}", "Cube") for i in range(20)]  # 20 cubes = 83%
        evidence = make_valid_evidence(actors=actors)
        result = check_western_frontier_readability(evidence)
        self.assertFalse(result.passed)
        self.assertIn("CLASS_DOMINANCE", result.issues[0])


class TestAggregatedRunner(unittest.TestCase):
    """Tests for the aggregated check runner."""

    def test_run_all_pass(self):
        evidence = make_valid_evidence()
        result = run_all_deterministic_checks(evidence)
        self.assertTrue(result["overall_passed"])
        self.assertEqual(result["summary"]["total"], 10)
        self.assertEqual(result["summary"]["passed"], 10)
        self.assertEqual(result["summary"]["failed"], 0)

    def test_run_all_fail_aggregates(self):
        evidence = make_valid_evidence(actors=[
            make_actor("AIVIDO_Heidi_01", "AIVIDO_Heidi", "BP_HeidiCharacter"),
            make_actor("Worker_01", "Worker", "BP_Worker"),
        ])  # Missing workers, stations, etc.
        result = run_all_deterministic_checks(evidence)
        self.assertFalse(result["overall_passed"])
        self.assertEqual(result["summary"]["total"], 10)
        self.assertGreater(result["summary"]["failed"], 0)

    def test_run_all_with_prior_hashes(self):
        evidence = make_valid_evidence()
        prior = {evidence.capture_metadata["sha256"]}
        result = run_all_deterministic_checks(evidence, prior_hashes=prior)
        self.assertFalse(result["overall_passed"])
        # Find the stale evidence check
        stale_check = next(c for c in result["checks"] if c["check_id"] == "NO_STALE_EVIDENCE")
        self.assertFalse(stale_check["passed"])


class TestConstantsAndContracts(unittest.TestCase):
    """Tests that verify constants and contracts are well-defined."""

    def test_required_actor_labels_defined(self):
        self.assertIn("heidi", REQUIRED_ACTOR_LABELS)
        self.assertIn("worker", REQUIRED_ACTOR_LABELS)
        self.assertIn("station", REQUIRED_ACTOR_LABELS)

    def test_min_counts_positive(self):
        self.assertGreater(MIN_HEIDI_COUNT, 0)
        self.assertGreater(MIN_WORKER_COUNT, 0)
        self.assertGreater(MIN_STATION_COUNT, 0)

    def test_worker_role_markers_comprehensive(self):
        self.assertIn("miner", WORKER_ROLE_MARKERS)
        self.assertIn("engineer", WORKER_ROLE_MARKERS)
        self.assertIn("prospector", WORKER_ROLE_MARKERS)
        self.assertGreaterEqual(len(WORKER_ROLE_MARKERS), 8)

    def test_required_worker_states_complete(self):
        self.assertEqual(set(REQUIRED_WORKER_STATES), {"IDLE", "WALK", "WORK"})

    def test_task_handoff_markers_defined(self):
        self.assertIn("task_", TASK_HANDOFF_MARKERS)
        self.assertIn("handoff", TASK_HANDOFF_MARKERS)
        self.assertIn("assign", TASK_HANDOFF_MARKERS)

    def test_placeholder_indicators_comprehensive(self):
        self.assertIn("cube", PLACEHOLDER_INDICATORS)
        self.assertIn("sphere", PLACEHOLDER_INDICATORS)
        self.assertIn("placeholder", PLACEHOLDER_INDICATORS)
        self.assertIn("graybox", PLACEHOLDER_INDICATORS)
        self.assertGreaterEqual(len(PLACEHOLDER_INDICATORS), 15)

    def test_required_map_substring(self):
        self.assertEqual(REQUIRED_MAP_SUBSTRING, "/Game/AIVIDO_Showcase")

    def test_max_evidence_age_reasonable(self):
        self.assertEqual(MAX_EVIDENCE_AGE_SECONDS, 300)  # 5 minutes

    def test_required_capture_metadata_keys_complete(self):
        expected = {"frame", "path", "sha256", "size_bytes", "captured_at_epoch", "map", "source"}
        self.assertEqual(set(REQUIRED_CAPTURE_METADATA_KEYS), expected)


class TestVisualRCGateStatic(unittest.TestCase):
    """Static analysis tests for the Visual RC Gate tool."""

    def test_gate_tool_exists(self):
        gate_path = ROOT / "tools" / "visual_rc" / "aivido_visual_rc_gate.py"
        self.assertTrue(gate_path.exists(), "Visual RC Gate tool must exist")

    def test_gate_tool_has_main(self):
        gate_path = ROOT / "tools" / "visual_rc" / "aivido_visual_rc_gate.py"
        content = gate_path.read_text()
        self.assertIn("def main()", content)
        self.assertIn("if __name__ == \"__main__\"", content)

    def test_gate_tool_has_all_checks(self):
        gate_path = ROOT / "tools" / "visual_rc" / "aivido_visual_rc_gate.py"
        content = gate_path.read_text()
        for check_id in CHECK_NAMES:
            self.assertIn(check_id, content, f"Missing check {check_id} in gate tool")

    def test_scene_criteria_module_importable(self):
        from tools.visual_rc import scene_criteria
        self.assertTrue(hasattr(scene_criteria, "run_all_deterministic_checks"))


# Import CHECK_NAMES from gate for static test
from tools.visual_rc.aivido_visual_rc_gate import CHECK_NAMES


if __name__ == "__main__":
    unittest.main(verbosity=2)