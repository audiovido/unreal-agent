"""Hermetic regression tests for the Creative Director (Phase D).

Engine-agnostic: no live editor, no network, no Blender. Every assertion
exercises the deterministic creative-intent layer that runs BEFORE execution.
"""
from __future__ import annotations

from core.creative_director import (
    CreativeDirection,
    consistency_report,
    direct_scene,
)
from core.production_pipeline import production_preflight

# ---------------------------------------------------------------------------
# Production briefs: vague request -> structured creative intent
# ---------------------------------------------------------------------------


def test_vague_sci_fi_lobby_becomes_structured_creative_brief():
    direction = direct_scene("make this look like a premium sci-fi AAA lobby")
    data = direction.to_dict()
    assert data["task_type"] == "environment"
    assert data["mood"] in ("premium", "futuristic", "cinematic")
    assert data["visual_language"] == "sci_fi"
    assert data["visual_language_evidence"]  # the prompt evidence that drove it
    assert data["composition_strategy"]
    assert data["composition_detail"]
    assert data["lighting_philosophy"]
    assert data["camera_language"]
    assert data["palette_direction"]
    assert data["storytelling_priorities"]  # ordered
    assert data["consistency_rules"]  # explicit rules the pipeline must honor
    # Rationale is auditable: every choice names its evidence.
    assert data["rationale"]["visual_language"] == data["visual_language_evidence"]


def test_direction_is_deterministic_and_hash_stable():
    first = direct_scene("make a calm cozy bedroom with warm lighting")
    second = direct_scene("make a calm cozy bedroom with warm lighting")
    assert first.to_dict() == second.to_dict()
    assert first.brief_hash() == second.brief_hash()
    assert len(first.brief_hash()) == 16


def test_different_domains_select_different_languages():
    ui = direct_scene("build a clean corporate dashboard app with glass panels")
    env = direct_scene("build a dark neo-noir rainy city street")
    cinematic = direct_scene("make a sweeping cinematic trailer shot of a spaceship")
    assert ui.task_type in ("application_ui", "unreal_ui")
    assert env.visual_language == "neo_noir"
    assert env.mood == "dark"
    assert cinematic.task_type == "cinematic"
    assert cinematic.camera_language  # sweeping/establishing language selected
    # Distinct creative intents must not collapse onto one language.
    assert ui.visual_language != env.visual_language


# ---------------------------------------------------------------------------
# Reference direction is evidence-only (never invented availability)
# ---------------------------------------------------------------------------


def test_reference_direction_never_invents_availability():
    no_ref = direct_scene("make a premium lobby")
    assert no_ref.reference_direction is None
    assert no_ref.reference_proven is False


def test_existing_reference_is_proven_and_missing_is_not(tmp_path):
    existing = tmp_path / "ref.png"
    existing.write_bytes(b"fake png")
    proven = direct_scene("match this reference C:/nope/missing.png in a lobby")
    assert proven.reference_direction is None
    assert proven.reference_proven is False
    with_ref = direct_scene("match this style", reference=str(existing))
    assert with_ref.reference_direction == str(existing.resolve())
    assert with_ref.reference_proven is True


# ---------------------------------------------------------------------------
# Consistency enforcement: no random art-direction drift across a mission
# ---------------------------------------------------------------------------


def test_consistency_report_flags_mood_and_language_drift():
    first = direct_scene("build a premium sci-fi lobby")
    drifted = direct_scene("actually make it a cozy warm cabin")
    report = consistency_report(drifted, [first.to_dict()])
    assert report["consistent"] is False
    kinds = {c["kind"] for c in report["conflicts"]}
    assert "visual_language_drift" in kinds
    assert "mood_drift" in kinds
    assert "palette_conflict" in kinds


def test_consistency_report_passes_for_consistent_briefs():
    first = direct_scene("build a premium sci-fi lobby")
    second = direct_scene("add a holo-terminal to the premium sci-fi lobby")
    report = consistency_report(second, [first.to_dict()])
    assert report["consistent"] is True
    assert report["conflicts"] == []


def test_consistency_report_detects_duplicate_creative_work():
    first = direct_scene("build a premium sci-fi lobby")
    report = consistency_report(first, [first.to_dict()])
    assert any(w["kind"] == "duplicate_brief" for w in report["warnings"])


# ---------------------------------------------------------------------------
# Context merging and serialization
# ---------------------------------------------------------------------------


def test_context_domains_are_merged_not_trusted_over_request():
    direction = direct_scene("build a lobby", context={"domains": ["environment_art", "lighting"]})
    assert "environment_art" in direction.domains
    assert "lighting" in direction.domains


def test_roundtrip_preserves_every_field():
    direction = direct_scene("make a dark energetic arcade with neon lighting and orbit camera")
    restored = CreativeDirection.from_dict(direction.to_dict())
    assert restored.to_dict() == direction.to_dict()
    assert restored.brief_hash() == direction.brief_hash()


# ---------------------------------------------------------------------------
# Pipeline integration: preflight carries the creative direction
# ---------------------------------------------------------------------------


def test_production_preflight_includes_creative_direction_for_visual():
    preflight = production_preflight("make this look like a premium sci-fi AAA lobby")
    assert preflight["visual_task"] is True
    direction = preflight["creative_direction"]
    for key in ("mood", "visual_language", "composition_strategy", "lighting_philosophy",
                "camera_language", "palette_direction", "storytelling_priorities",
                "consistency_rules", "reference_proven"):
        assert key in direction, key
    assert direction["visual_language"] == "sci_fi"
    # The pipeline stage list already promised creative_direction; now it is real.
    assert "creative_direction" in preflight["pipeline"]


def test_production_preflight_nonvisual_keeps_previous_shape():
    preflight = production_preflight("execute the automated regression pass")
    assert preflight["visual_task"] is False
    assert "creative_direction" not in preflight
    assert "brief" in preflight


def test_consistency_rules_prevent_random_asset_placement():
    env = direct_scene("make a premium sci-fi lobby")
    env_rules = " ".join(env.consistency_rules)
    assert "no random asset placement" in env_rules or any(
        "placement" in rule for rule in env.consistency_rules
    )
    ui = direct_scene("build a clean dashboard")
    assert any("spacing" in rule for rule in ui.consistency_rules)