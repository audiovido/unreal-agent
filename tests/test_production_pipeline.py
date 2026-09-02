from __future__ import annotations

import time

from core.production_pipeline import (
    build_visual_brief,
    discover_reuse_candidates,
    is_visual_task,
    production_preflight,
    select_reuse_strategy,
    visual_scorecard,
)


def test_visual_brief_covers_collaborating_roles_and_reference_contract():
    brief = build_visual_brief("Create a premium cinematic dashboard with glass UI and a futuristic room")
    data = brief.to_dict()
    assert data["task_type"] == "application_ui"
    assert "Creative Director" in data["collaborators"]
    assert data["visual_hierarchy"]
    for key in ("composition", "spacing", "typography", "palette", "materials", "lighting", "camera", "motion", "storytelling", "ux_flow"):
        assert data[key]


def test_reuse_router_priority_and_modes():
    candidates = [{"name": "WBP_Existing", "kind": "widget", "score": 10}]
    fast = select_reuse_strategy("Build a fast dashboard", candidates)
    assert fast.mode == "fast" and fast.strategy == "reuse"
    balanced = select_reuse_strategy("Build a premium dashboard", candidates)
    assert balanced.mode == "balanced" and balanced.strategy == "modify"
    custom = select_reuse_strategy("Build a bespoke hero asset from scratch", candidates)
    assert custom.mode == "custom" and custom.strategy in {"modify", "combine"}
    fresh = select_reuse_strategy("Build a dashboard", [])
    assert fresh.strategy == "generate"


def test_parallel_discovery_and_cache(tmp_path, monkeypatch):
    import core.production_pipeline as pipeline
    monkeypatch.setattr(pipeline, "CACHE_FILE", tmp_path / "cache.json")
    calls = []

    def provider(name):
        def run(request, context):
            time.sleep(0.03)
            calls.append(name)
            return [{"name": name, "kind": "asset", "score": 5}]
        return run

    started = time.perf_counter()
    first = discover_reuse_candidates("dashboard", providers={"a": provider("a"), "b": provider("b")})
    elapsed = time.perf_counter() - started
    assert {x["name"] for x in first} == {"a", "b"}
    assert elapsed < 0.09
    second = discover_reuse_candidates("dashboard", providers={"a": provider("a"), "b": provider("b")})
    assert second == first
    assert calls == ["a", "b"]


def test_preflight_is_nonvisual_fast_and_visual_complete():
    assert is_visual_task("Fix a Python parser") is False
    nonvisual = production_preflight("Fix a Python parser")
    assert nonvisual["visual_task"] is False
    assert nonvisual["brief"]["mood"] == "n/a"
    visual = production_preflight("Create a cinematic room UI")
    assert visual["visual_task"] is True
    assert visual["brief"]["task_type"] in {"environment", "unreal_ui"}
    assert "creative_direction" in visual["pipeline"]


def test_visual_scorecard_exposes_requested_dimensions():
    card = visual_scorecard({"composition": 9, "subject_framing": 8, "lighting": 9, "environment": 8, "ui": 9, "readability": 8, "target_match": 8, "technical_integrity": 9, "overall": 9.1})
    for key in ("composition", "visual_hierarchy", "spacing", "typography", "materials", "lighting", "camera", "motion", "usability", "uniqueness", "premium_feel"):
        assert key in card
    assert card["target"] == 9.0
    assert card["accepted"] is True
