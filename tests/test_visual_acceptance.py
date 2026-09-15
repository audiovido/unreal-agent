"""Regression tests for core.visual_acceptance — deterministic, offline (no
editor). Covers measurement (bboxes, coverage, clipping, bands, stale hash,
roll), scoring, the >=8/>=7 product gates, blocker waivers, and the
technical+visual completion gate."""
from __future__ import annotations

import copy

import pytest
from PIL import Image

from core.visual_acceptance import (
    VisualScore,
    accepts,
    combine_with_vision,
    completion_gate,
    detect_camera_roll,
    measure,
    score,
)
from tests.img_helpers import (
    hero_locator,
    make_scene,
    right_panel_locator,
    save_scene,
)

# A target equivalent to the one the VisualDirector produces for the
# AvaLive graduation prompt (hero female left, premium glass UI right).
TARGET = {
    "subject": {
        "type": "female_ai_avatar",
        "screen_position": "left_center",
        "target_screen_coverage": [0.20, 0.26],
        "head_fully_visible": True,
        "max_head_top_frac": 0.07,
    },
    "lighting": {"highlight_clipping_max": 0.08, "shadow_crush_max": 0.12},
    "ui": {"present": True, "placement": "right",
           "screen_coverage": [0.20, 0.45],
           "required_elements": ["title", "status", "history", "input", "send"]},
}


def _passing_score() -> VisualScore:
    s = VisualScore()
    for name in ("composition", "subject_framing", "lighting", "environment",
                 "ui", "readability", "target_match", "technical_integrity"):
        setattr(s, name, 8.5)
    s.overall = 8.6
    return s


# --------------------------------------------------------------------------
# measurement
# --------------------------------------------------------------------------

def test_measure_normal_scene(tmp_path):
    m = measure(save_scene(tmp_path, "a.png"), TARGET,
                subject_locator=hero_locator, ui_locator=right_panel_locator)
    assert m.ok
    assert len(m.hash_md5_12) == 12
    assert m.width == 900 and m.height == 500
    assert not m.bands and not m.stale
    assert m.subject_bbox is not None
    assert m.ui_bbox is not None
    assert 0.20 <= m.subject_coverage <= 0.28
    assert 0.20 <= m.ui_screen_coverage <= 0.45


def test_subject_and_ui_locators_agree_with_layout(tmp_path):
    img = make_scene()
    sb = hero_locator(img)
    ub = right_panel_locator(img)
    assert sb is not None and ub is not None
    # panel strictly to the right of the subject
    assert ub[0] > sb[2]


def test_stale_hash_detected(tmp_path):
    path = save_scene(tmp_path, "stale.png")
    m1 = measure(path, TARGET, subject_locator=hero_locator,
                 ui_locator=right_panel_locator)
    m2 = measure(path, TARGET, reference_hash=m1.hash_md5_12,
                 subject_locator=hero_locator, ui_locator=right_panel_locator)
    assert m2.stale is True
    assert "STALE_CAPTURE" in m2.issues


def test_black_bands_detected(tmp_path):
    m = measure(save_scene(tmp_path, "band.png", bands=True), TARGET,
                subject_locator=hero_locator, ui_locator=right_panel_locator)
    assert m.bands
    assert any("BLACK_BAND" in i for i in m.issues)


def test_white_frame_clipped(tmp_path):
    m = measure(save_scene(tmp_path, "w.png", white=True), TARGET)
    assert m.pct_white > 0.9
    assert "WHITE_CLIPPING" in m.issues
    s = score(m, TARGET)
    assert s.lighting < 4.0


def test_head_clip_detected(tmp_path):
    m = measure(save_scene(tmp_path, "clip.png",
                           subject=(0.12, 0.36, 0, 460)), TARGET,
                subject_locator=hero_locator, ui_locator=right_panel_locator)
    assert m.head_clipped is True
    assert "HEAD_CROPPED" in m.issues
    s = score(m, TARGET)
    assert s.subject_framing <= 3.5


def test_camera_roll_detected(tmp_path):
    img = make_scene().rotate(15, resample=Image.BICUBIC,
                              fillcolor=(25, 25, 25))
    assert detect_camera_roll(img) > 4.0


def test_missing_file_not_ok(tmp_path):
    m = measure(str(tmp_path / "nope.png"), TARGET)
    assert not m.ok
    assert m.issues
# --------------------------------------------------------------------------
# scoring + gates
# --------------------------------------------------------------------------

def test_score_passes_good_scene(tmp_path):
    m = measure(save_scene(tmp_path, "good.png"), TARGET,
                subject_locator=hero_locator, ui_locator=right_panel_locator)
    s = score(m, TARGET)
    d = s.to_dict()
    assert set(d) == {"composition", "subject_framing", "lighting",
                      "environment", "ui", "readability", "target_match",
                      "technical_integrity", "overall"}
    assert s.overall >= 8.0
    assert accepts(s, TARGET)


def test_accepts_rejects_low_overall():
    s = _passing_score()
    s.overall = 7.9
    assert not accepts(s, TARGET)


def test_accepts_rejects_mandatory_category():
    s = _passing_score()
    s.subject_framing = 6.9
    assert not accepts(s, TARGET)


def test_accepts_external_blocker_waives_subject_category():
    s = _passing_score()
    s.subject_framing = 5.0
    assert not accepts(s, TARGET)
    assert accepts(s, TARGET, allow_external_blocker=True)


def test_completion_gate_requires_both():
    assert completion_gate(True, True)["product_complete"] is True
    assert completion_gate(True, False)["product_complete"] is False
    assert completion_gate(False, True)["product_complete"] is False
    g = completion_gate(True, False)
    assert g["technical_pass"] is True and g["visual_pass"] is False


def test_combine_with_vision_blends_and_penalizes():
    s = _passing_score()
    vision = {"score": 4.0, "pass": False, "issues": ["UI_LOW_CONTRAST",
                                                      "SUBJECT_TOO_LARGE"]}
    out = combine_with_vision(copy.deepcopy(s), dict(vision),
                              vision_weight=0.35)
    assert out.overall < s.overall
    assert out.ui < 8.5
    assert out.subject_framing < 8.5


def test_lighting_budget_aligns_with_loop_trigger(tmp_path):
    """The scoring curve must align with the loop's WHITE_CLIPPING trigger:
    a frame within the target's clipping budget passes, a frame at or beyond
    the trigger keeps failing acceptance AND keeps being flagged, so the loop
    can never stop while acceptance still fails."""
    from PIL import ImageDraw

    premium = {"lighting": {"highlight_clipping_max": 0.05,
                            "shadow_crush_max": 0.10}}
    w, h = 900, 500

    def measure_white(pct):
        img = make_scene()
        d = ImageDraw.Draw(img)
        d.rectangle([0, 0, w, max(1, int(h * pct))], fill=(250, 250, 250))
        p = tmp_path / f"w{int(pct * 100)}.png"
        img.save(p)
        m = measure(str(p), premium, subject_locator=hero_locator,
                    ui_locator=right_panel_locator)
        return m, score(m, dict(premium))

    # 4% blown: inside the 0.05 budget -> lighting unpenalized, no flag
    m4, s4 = measure_white(0.04)
    assert m4.pct_white >= 0.03
    assert s4.lighting >= 9.0
    assert "WHITE_CLIPPING" not in m4.issues

    # 15% blown: beyond trigger (0.07) and budget -> flag + acceptance fails
    m15, s15 = measure_white(0.15)
    assert "WHITE_CLIPPING" in m15.issues
    assert s15.lighting < 7.0


def test_combine_with_vision_noop_without_review():
    s = _passing_score()
    assert combine_with_vision(s, None).overall == s.overall