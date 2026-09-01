"""Regression tests for core.visual_director — natural-language intent ->
VisualTarget, defect->action mapping, bounded deltas, reference-image spec,
art direction and evidence-based self-critique. The simple-user regression
tests here enforce the PRODUCT RULE: the normal user never provides (and the
visual target never contains) Unreal technical parameters."""
from __future__ import annotations

import json

from core.visual_director import (
    art_direct,
    choose_bounded_delta,
    defect_to_action,
    parse_intent,
    reference_spec,
    self_critique,
)

FORBIDDEN_TERMS = ("fov", "exposure", "intensity", "lumens", "umg",
                   "viewport", "pie", "actor", "material",
                   "camera position", "roll degree")


def _dump(target) -> str:
    """The measurable goal surface only — art_direction intentionally holds
    implementation routing decisions (blender_agent, tool_routes) that the
    user never sees, so it is excluded from the no-technical-terms check."""
    core = {k: v for k, v in target.items() if k != "art_direction"}
    return json.dumps(core, default=str).lower()


# --------------------------------------------------------------------------
# intent parsing
# --------------------------------------------------------------------------

def test_graduation_prompt_parses_to_full_target():
    target = parse_intent(
        "Create a premium cinematic live AI chat screen. "
        "Use a female AI assistant on the left, a beautiful futuristic "
        "environment, and a modern glass chat interface on the right. "
        "It should look like a finished product, not a prototype. "
        "The chat must work with the local AI.")
    assert target["subject"]["type"] == "female_ai_avatar"
    assert target["subject"]["screen_position"] == "left"
    assert target["subject"]["head_fully_visible"] is True
    assert target["ui"]["present"] is True
    assert target["ui"]["placement"] == "right"
    assert target["ui"]["style"] == "premium dark glass"
    assert target["ui"]["live_chat"] is True
    assert target["environment"]["style"].startswith("premium")
    assert target["environment"].get("accent") == "cyan" or \
        "futuristic" in target["environment"]["style"]
    assert "ollama" in target["art_direction"]["tool_routes"]
    assert target["art_direction"]["ui_placement"] == "right"
    # premium/cinematic moods get the tighter clipping budget
    assert target["lighting"]["highlight_clipping_max"] == 0.05
    assert target["lighting"]["shadow_crush_max"] == 0.10


def test_simple_user_prompts_never_contain_technical_terms():
    prompts = [
        "Make me a beautiful futuristic room with a woman standing in it.",
        "Build a professional live AI chat screen.",
        "Make this scene feel more expensive and cinematic.",
        "Make the character look good on camera.",
    ]
    for p in prompts:
        target = parse_intent(p)
        dumped = _dump(target)
        for term in FORBIDDEN_TERMS:
            assert term not in dumped, (p, term)


def test_room_with_woman_is_female_character_scene():
    target = parse_intent(
        "Make me a beautiful futuristic room with a woman standing in it.")
    assert target["subject"]["type"] == "female_character"
    assert target["subject"]["target_screen_coverage"] != []
    assert target["art_direction"]["palette"] == "cool_cyan_accents"


def test_make_character_look_good_on_camera():
    target = parse_intent("Make the character look good on camera.")
    assert target["subject"]["importance"] == "hero"
    assert target["subject"]["head_fully_visible"] is True


def test_expensive_cinematic_maps_to_premium():
    target = parse_intent("Make this scene feel more expensive and cinematic.")
    assert target["environment"]["style"].startswith("premium")
    assert target["lighting"]["style"] == "premium cinematic"


def test_live_chat_routes_ollama_but_room_does_not():
    chat = parse_intent("Build a professional live AI chat screen.")
    room = parse_intent("Make me a beautiful futuristic room.")
    assert "ollama" in chat["art_direction"]["tool_routes"]
    assert "ollama" not in room["art_direction"]["tool_routes"]


def test_required_elements_and_coverage_always_structurally_present():
    for p in ("a cozy room", "a bright minimal product scene",
              "a futuristic facility, wide shot"):
        target = parse_intent(p)
        assert isinstance(target["subject"]["target_screen_coverage"], list)
        assert len(target["subject"]["target_screen_coverage"]) == 2
        assert isinstance(target["ui"]["screen_coverage"], list)
        assert "required_elements" in target["ui"]
        assert "art_direction" in target and target["art_direction"]


# --------------------------------------------------------------------------
# defect -> action
# --------------------------------------------------------------------------

def test_defect_to_action_mapping():
    assert defect_to_action("HEAD_CROPPED") == "camera_framing_recompute"
    assert defect_to_action("SUBJECT_TOO_LARGE") == "camera_pull_back"
    assert defect_to_action("SUBJECT_TOO_SMALL") == "camera_move_closer"
    assert defect_to_action("WHITE_CLIPPING") == "exposure_reduce_highlights"
    assert defect_to_action("BACKGROUND_OVEREXPOSED") == \
        "lighting_reduce_background"
    assert defect_to_action("SUBJECT_TOO_DARK") == "lighting_raise_key"
    assert defect_to_action("UI_TOO_SMALL") == "ui_scale_up"
    assert defect_to_action("UI_LOW_CONTRAST") == "ui_raise_contrast"
    assert defect_to_action("UI_OFF_SCREEN") == "ui_relayout_runtime"
    assert defect_to_action("STALE_CAPTURE") == "capture_force_fresh"
    assert defect_to_action("CAMERA_ROLL") == "camera_roll_reset"
    assert defect_to_action("EMPTY_ENVIRONMENT") == "environment_add_depth"
    assert defect_to_action("CHEAP_PRIMITIVE_LOOK") == \
        "blender_or_materials_upgrade"
    # band defects carry the band description after a colon
    assert defect_to_action("BLACK_BAND:bottom letterbox band") == \
        "viewport_aspect_fix"


def test_choose_bounded_delta_is_bounded():
    for mag, sign in ((0.5, 1), (0.5, -1), (2.0, 1), (0.02, -1)):
        d = choose_bounded_delta("any", magnitude=mag, direction_sign=sign)
        assert 0.55 <= d <= 1.45
        assert (d > 1.0) == (sign > 0)


# --------------------------------------------------------------------------
# reference image support
# --------------------------------------------------------------------------

def test_reference_spec_uses_vision_dict(tmp_path):
    ref = tmp_path / "ref.png"
    ref.write_bytes(b"x")
    vision = lambda path: {  # noqa: E731
        "composition": "hero", "subject_position": "left",
        "subject_coverage": 0.42, "ui_position": "right",
        "ui_coverage": 0.28, "palette": "cool",
        "lighting_style": "cinematic", "background_depth": "high",
        "contrast": "high", "brightness": "moody",
        "major_geometry": "ring", "visual_hierarchy": "hero left + ui right",
    }
    spec = reference_spec(str(ref), vision=vision)
    assert spec["method"] == "vision"
    assert spec["composition"] == "hero"
    assert spec["subject_position"] == "left"
    assert spec["subject_coverage"] == 0.42
    assert spec["ui_position"] == "right"
    assert spec["ui_position_frac"] == [0.6, 0.99]


def test_reference_spec_parses_json_string_vision(tmp_path):
    ref = tmp_path / "ref.png"
    ref.write_bytes(b"x")
    vision = lambda path: (  # noqa: E731
        '{"composition": "centered", "subject_position": "center", '
        '"subject_coverage": 0.3, "ui_position": "bottom", '
        '"ui_coverage": 0.15, "background_depth": "low"}'
    )
    spec = reference_spec(str(ref), vision=vision)
    assert spec["composition"] == "centered"
    assert spec["subject_position"] == "center"
    assert spec["ui_position"] == "bottom"


def test_reference_spec_falls_back_when_missing_file():
    assert reference_spec("") == {"unavailable": True}


def test_reference_used_as_acceptance_target_override(tmp_path):
    ref = tmp_path / "ref.png"
    ref.write_bytes(b"x")
    vision = lambda path: {"subject_position": "center",  # noqa: E731
                           "ui_position": "bottom"}
    target = parse_intent("Create something similar to this reference image.",
                          ref_image=str(ref), vision=vision)
    assert target["reference"]["subject_position"] == "center"
    assert "art_direction" in target


# --------------------------------------------------------------------------
# art direction
# --------------------------------------------------------------------------

def test_art_direct_realistic_human_routes_blender():
    target = parse_intent("A realistic human presenter on camera.")
    d = art_direct(target)
    assert d.needs_blender is True
    assert "blender_agent" in d.tool_routes
    assert any("photoreal" in n.lower() or "realistic" in n.lower()
               for n in d.notes)


# --------------------------------------------------------------------------
# self critique (evidence-based, never language-only)
# --------------------------------------------------------------------------

class _FakeMetrics:
    issues = []
    head_clipped = False
    stale = False
    bands = []
    pct_white = 0.02
    pct_black = 0.01
    subject_coverage = 0.24
    ui_screen_coverage = 0.30


class _FakeScore:
    overall = 8.6


def test_self_critique_accepts_clean_frame():
    c = self_critique("x.png", _FakeMetrics(), _FakeScore(),
                      vision_review={"pass": True, "issues": []})
    assert c["verdict"] == "ACCEPT"
    assert c["evidence"]["head_clipped"] is False


def test_self_critique_revises_head_clip():
    m = _FakeMetrics()
    m.head_clipped = True
    m.issues = ["HEAD_CROPPED"]
    c = self_critique("x.png", m, _FakeScore(),
                      vision_review={"pass": True, "issues": []})
    assert c["verdict"] == "REVISE"


def test_self_critique_revises_low_score_or_stale():
    s = _FakeScore()
    s.overall = 7.2
    assert self_critique("x.png", _FakeMetrics(), s)["verdict"] == "REVISE"
    s2 = _FakeMetrics()
    s2.stale = True
    s2.issues = ["STALE_CAPTURE"]
    assert self_critique("x.png", s2, _FakeScore())["verdict"] == "REVISE"