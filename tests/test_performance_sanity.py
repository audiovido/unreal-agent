"""UNREAL CODER — Phase R: performance / latency sanity.

Measures the deterministic path (parsing -> intent -> expansion -> planning)
and flags obvious pathologies. These are sanity bounds for regression
detection, not micro-benchmarks.
"""
import statistics
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def timed(fn, repeats=20):
    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000.0)
    return {
        "median_ms": round(statistics.median(samples), 2),
        "p95_ms": round(sorted(samples)[int(len(samples) * 0.95) - 1], 2),
        "max_ms": round(max(samples), 2),
    }


class TestLatencySanity:
    def test_intent_routing_is_fast(self):
        from core.universal_intent import interpret_intent
        stats = timed(lambda: interpret_intent(
            "make me a beautiful photorealistic sci-fi main menu with "
            "cinematic lighting"))
        assert stats["p95_ms"] < 20, stats

    def test_requirement_expansion_is_fast(self):
        from core.universal_intent import expand_requirements, interpret_intent
        intent = interpret_intent("build a third person shooter prototype")
        stats = timed(lambda: expand_requirements(intent))
        assert stats["p95_ms"] < 20, stats

    def test_planning_is_fast(self):
        from core.universal_intent import expand_requirements, interpret_intent
        from core.universal_planner import build_universal_planner
        from core.tool_registry import build_registry
        from tools.unreal.project_manager import (
            create_project, discover_projects, inspect_project, open_project,
        )
        from tools.unreal.unreal_bridge import UnrealBridge
        registry = build_registry(
            discover_projects, inspect_project, open_project, create_project,
            lambda **k: {}, lambda **k: {}, lambda **k: {}, lambda **k: {},
            bridge=UnrealBridge(),
        )
        planner = build_universal_planner(registry)
        intent = interpret_intent(
            "create a polished sci-fi main menu with a cinematic intro")
        requirements = expand_requirements(intent)
        stats = timed(lambda: planner.build_plan(intent, requirements, None))
        assert stats["p95_ms"] < 100, stats

    def test_full_deterministic_path_under_150ms(self):
        from core.universal_intent import expand_requirements, interpret_intent
        from core.universal_planner import build_universal_planner
        from core.tool_registry import build_registry
        from tools.unreal.project_manager import (
            create_project, discover_projects, inspect_project, open_project,
        )
        from tools.unreal.unreal_bridge import UnrealBridge
        registry = build_registry(
            discover_projects, inspect_project, open_project, create_project,
            lambda **k: {}, lambda **k: {}, lambda **k: {}, lambda **k: {},
            bridge=UnrealBridge(),
        )
        planner = build_universal_planner(registry)

        def full_path():
            intent = interpret_intent("make this scene look cinematic")
            req = expand_requirements(intent)
            return planner.build_plan(intent, req, None)

        stats = timed(full_path)
        assert stats["p95_ms"] < 150, stats

    def test_visual_measurement_of_synthetic_frame_is_bounded(self,
                                                              tmp_path):
        """Deterministic image analysis on a 1280x720 frame stays bounded."""
        from PIL import Image, ImageDraw
        path = tmp_path / "perf_frame.png"
        img = Image.new("RGB", (1280, 720), (70, 90, 120))
        draw = ImageDraw.Draw(img)
        for i in range(0, 1280, 24):
            draw.line([(i, 0), (i, 719)], fill=(90 + i % 50, 110, 130))
        draw.rectangle([200, 150, 620, 650], fill=(160, 170, 190))
        img.save(path)
        from core.visual_acceptance import measure, score
        stats = timed(lambda: score(measure(str(path))), repeats=5)
        # The pixel-scan locators are the known heavy part; bounded sanity.
        assert stats["median_ms"] < 5000, stats


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
