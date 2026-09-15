"""Explicit-brief planning: prohibitions must never hijack the plan.

Regression anchor for the real E2E production mission: a brief that says
"Do NOT use Blender. Do NOT create cubes" contains the keyword planner's
trigger words. The plan executed the canned blender demo pipeline instead of
the dictated set_actor_property steps, so the honest gates stalled on
light:exists while the scene accumulated forbidden demo actors.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api import (  # noqa: E402
    _brief_actor_universe,
    _brief_explicit_steps,
    _has_task_steps,
    _strip_negated_clauses,
    normalize_execution_plan,
)

BRIEF = """Production-safe materials and lighting pass on the EXISTING scene /Game/AIVIDO_Showcase only.

The scene already contains actors including AIVIDO_Floor, AIVIDO_RearWall, AIVIDO_LeftWall, AIVIDO_RightWall, AIVIDO_CommandDais, AIVIDO_Console_A, AIVIDO_Console_B, AIVIDO_VisualCore, AIVIDO_Worker_AV, AIVIDO_Worker_ASSET, AIVIDO_Worker_UA, AIVIDO_Worker_AU, lights AIVIDO_KeyWarm, AIVIDO_FillCool, AIVIDO_RimGold, AIVIDO_Practical_0..3, AIVIDO_PostProcess, AIVIDO_HeroCamera.

HARD RULES:
- Do NOT spawn, duplicate, delete, or rename any actor. Do NOT import assets. Do NOT use Blender. Do NOT create cubes or placeholders.
- Do NOT create, duplicate, rename, save-as, or switch maps. Operate ONLY on /Game/AIVIDO_Showcase.
- Keep at least 20 live actors. Do not touch any other project.

TASK - use ONLY the tool set_actor_property on the listed existing actors, then verify each change with get_actor:
1. Apply material /Game/Cinema/Materials/M_Cinema_Floor to AIVIDO_Floor.
2. Apply material /Game/Cinema/Materials/M_Cinema_Surface to AIVIDO_CommandDais, AIVIDO_Console_A, AIVIDO_Console_B.
3. Apply material /Game/Cinema/Materials/M_Cinema_Seat to the four AIVIDO_Worker actors.
4. Apply material /Game/Cinema/Materials/M_Cinema_Emissive to AIVIDO_VisualCore.
5. Set light_color of AIVIDO_KeyWarm to [1.0, 0.72, 0.42] and light_intensity to 3200.
6. Set light_color of AIVIDO_FillCool to [0.45, 0.62, 1.0] and light_intensity to 900.
7. Set light_color of AIVIDO_RimGold to [1.0, 0.84, 0.5] and light_intensity to 1400.
8. Set the four AIVIDO_Practical lights to [1.0, 0.78, 0.5] intensity 650.
Finish with save_level and capture_unreal_viewport."""


def test_negation_strip_removes_prohibitions_but_keeps_instructions():
    stripped = _strip_negated_clauses(
        "Do NOT use Blender. Do NOT create cubes or placeholders. Apply warm materials and edit lights."
    )
    low = stripped.lower()
    assert "blender" not in low
    assert "create cubes" not in low
    assert "apply warm materials" in low
    assert "edit lights" in low


def test_brief_actor_universe_expands_range_token():
    universe = _brief_actor_universe(BRIEF)
    # The range token AIVIDO_Practical_0..3 contains a period; the universe
    # must survive it and still include every other named actor.
    for label in (
        "AIVIDO_Floor",
        "AIVIDO_Worker_ASSET",
        "AIVIDO_KeyWarm",
        "AIVIDO_Practical_0",
        "AIVIDO_Practical_3",
        "AIVIDO_HeroCamera",
    ):
        assert label in universe, f"{label} missing from {universe}"


def test_brief_parses_material_steps_with_clean_actor_names():
    steps = _brief_explicit_steps(BRIEF)
    mat = [s for s in steps if s["parameters"].get("property") == "material"]
    actors = [s["parameters"]["actor_name"] for s in mat]
    assert actors == [
        "AIVIDO_Floor",
        "AIVIDO_CommandDais",
        "AIVIDO_Console_A",
        "AIVIDO_Console_B",
        "AIVIDO_Worker_AV",
        "AIVIDO_Worker_ASSET",
        "AIVIDO_Worker_UA",
        "AIVIDO_Worker_AU",
        "AIVIDO_VisualCore",
    ]
    assert all(
        s["parameters"]["material_asset"].startswith("/Game/Cinema/Materials/M_Cinema_")
        for s in mat
    )
    # No punctuation leaked into identifiers.
    assert all(a.replace("_", "").isalnum() for a in actors)


def test_brief_parses_light_pairs_and_practical_expansion():
    steps = _brief_explicit_steps(BRIEF)
    light = [s for s in steps if s["parameters"].get("property") in ("light_color", "light_intensity")]
    by_actor = {}
    for s in light:
        by_actor.setdefault(s["parameters"]["actor_name"], set()).add(s["parameters"]["property"])
    assert set(by_actor) == {
        "AIVIDO_KeyWarm",
        "AIVIDO_FillCool",
        "AIVIDO_RimGold",
        "AIVIDO_Practical_0",
        "AIVIDO_Practical_1",
        "AIVIDO_Practical_2",
        "AIVIDO_Practical_3",
    }
    assert all(v == {"light_color", "light_intensity"} for v in by_actor.values())
    warm = next(
        s for s in light
        if s["parameters"]["actor_name"] == "AIVIDO_KeyWarm"
        and s["parameters"]["property"] == "light_intensity"
    )
    assert warm["parameters"]["value"] == 3200.0


def test_brief_parses_validation_save_and_evidence_tail():
    steps = _brief_explicit_steps(BRIEF)
    validations = [s for s in steps if s["preferred_tool"] == "get_actor"]
    assert {s["parameters"]["actor_name"] for s in validations} == {
        "AIVIDO_KeyWarm",
        "AIVIDO_FillCool",
        "AIVIDO_RimGold",
        "AIVIDO_Practical_0",
        "AIVIDO_Practical_1",
        "AIVIDO_Practical_2",
        "AIVIDO_Practical_3",
    }
    tail = [s["preferred_tool"] for s in steps[-2:]]
    assert tail == ["save_level", "capture_unreal_viewport"]
    # Every step carries a sanitized step_id.
    assert all(s["step_id"] and all(c.isalnum() or c == "_" for c in s["step_id"]) for s in steps)


def test_normalize_brief_bypasses_keyword_hijack():
    plan = normalize_execution_plan(BRIEF, None)
    tools = [s["preferred_tool"] for s in plan["steps"]]
    # The canned demo pipeline the brief explicitly forbids.
    forbidden = {
        "blender_create_asset", "import_blender_output", "spawn_blender_output",
        "spawn_actor", "blender_status", "inspect_project", "unreal_ping",
    }
    assert not (set(tools) & forbidden), f"brief was hijacked: {tools}"
    assert tools.count("set_actor_property") == 23  # 9 materials + 14 light edits
    assert tools[-2:] == ["save_level", "capture_unreal_viewport"]


def test_non_brief_requests_keep_existing_planning():
    assert _brief_explicit_steps("create a cube in the scene with a light") == []
    assert _brief_explicit_steps("") == []


def test_health_only_plan_is_not_task_work():
    health = [
        {"step_id": "inspect_project"},
        {"step_id": "ping"},
        {"step_id": "blender_status"},
    ]
    assert _has_task_steps(health) is False
    assert _has_task_steps(health + [{"step_id": "real_work"}]) is True
