"""Offline regression tests for core.release_director — the deterministic
release gate, defect diagnosis and bounded fix-planning logic used by the
autonomous Visual Director graduation loop.  No editor, no network.

The synthetic metrics mirror real measured values from the release scene so
the gate/plan semantics are exercised on the production shapes.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.release_director import (
    RELEASE_COVERAGE_BAND,
    decide_rollback,
    detect_defects,
    dolly_factor,
    light_factor,
    parse_capture_diag,
    plan_fixes,
    release_accept,
)


def metrics(**over):
    base = dict(
        ok=True, width=1994, height=735, mean_luma=131.0, std_luma=60.0,
        entropy=6.95, pct_white=0.0053, pct_black=0.0939, bands=[],
        subject_bbox=[39, 346, 1435, 712], subject_coverage=0.3486,
        head_clipped=False, ui_bbox=[1240, 36, 1522, 276],
        ui_screen_coverage=0.0462, empty_space_ratio=0.3,
        hash_md5_12="abc", stale=False, roll_deg=0.0, issues=[],
    )
    base.update(over)
    return SimpleNamespace(**base)


def score(overall=8.66, **cats):
    c = dict(composition=8.0, subject_framing=10.0, lighting=10.0,
             environment=10.0, ui=8.0, readability=5.0, target_match=7.0,
             technical_integrity=10.0)
    c.update(cats)
    return SimpleNamespace(overall=overall, **c)


class TestReleaseAccept:
    def test_accepts_clean_release_frame(self):
        assert release_accept(metrics(), score()) is True

    def test_rejects_below_floor(self):
        assert release_accept(metrics(), score(8.49)) is False
        assert release_accept(metrics(), score(8.5)) is True

    def test_rejects_measured_issues(self):
        assert release_accept(metrics(issues=["HEAD_CROPPED"]), score()) is False
        assert release_accept(metrics(head_clipped=True), score()) is False

    def test_rejects_camera_roll(self):
        assert release_accept(metrics(roll_deg=6.2), score()) is False

    def test_rejects_out_of_band_coverage(self):
        lo, hi = RELEASE_COVERAGE_BAND
        assert release_accept(metrics(subject_coverage=hi + 0.05), score()) is False
        assert release_accept(metrics(subject_coverage=lo - 0.05), score()) is False
        assert release_accept(metrics(subject_coverage=(lo + hi) / 2), score()) is True

    def test_require_ui(self):
        assert release_accept(metrics(ui_bbox=None), score(), require_ui=True) is False
        assert release_accept(metrics(), score(), require_ui=True) is True

    def test_rejects_stale_and_bands(self):
        assert release_accept(metrics(stale=True), score()) is False
        assert release_accept(metrics(bands=["top"]), score()) is False


class TestDetectAndPlan:
    def test_detect_ranking_uses_loop_vocabulary(self):
        m = metrics(subject_coverage=0.85, pct_white=0.4)
        defects = detect_defects(m, score(6.0))
        assert "SUBJECT_TOO_LARGE" in defects
        assert "WHITE_CLIPPING" in defects

    def test_plan_produces_ranked_problems_and_why(self):
        m = metrics(subject_coverage=0.85)
        plan = plan_fixes(m, score(6.4), max_fixes=3)
        assert plan["problems"] and plan["fixes"]
        top = plan["fixes"][0]
        assert top["defect"] == "SUBJECT_TOO_LARGE"
        assert top["action"].startswith("camera_")
        assert "expected_impact" in top and "why" in top
        assert plan["strategy"] == top["action"]

    def test_plan_exposure_problem(self):
        m = metrics(pct_white=0.45)
        plan = plan_fixes(m, score(6.0))
        assert any("WHITE" in f["defect"] for f in plan["fixes"])
        assert any("exposure_reduce_highlights" == f["action"]
                   for f in plan["fixes"])

    def test_clean_frame_has_no_problems(self):
        plan = plan_fixes(metrics(), score())
        assert plan["problems"] == []
        assert plan["fixes"] == []
        assert plan["defects"] == []


class TestHelpers:
    def test_parse_capture_diag(self):
        ok = parse_capture_diag(
            "OK|source=LevelViewport[1]|perspective=1|visible=1|width=1994"
            "|height=735|bytes=1422827")
        assert ok["ok"] is True and ok["visible"] is True
        assert ok["width"] == 1994 and ok["height"] == 735
        hidden = parse_capture_diag(
            "OK|source=LevelViewport[1]|perspective=1|visible=0|width=1994"
            "|height=735|bytes=1422827")
        assert hidden["ok"] is False and hidden["visible"] is False
        assert parse_capture_diag("ERROR")["ok"] is False

    def test_decide_rollback(self):
        assert decide_rollback(8.6, 7.9, [], [], ["camera_pull_back"]) is True
        assert decide_rollback(7.5, 7.5, ["WHITE_CLIPPING"],
                               ["WHITE_CLIPPING"], ["x"]) is True
        assert decide_rollback(7.5, 7.9, ["WHITE_CLIPPING"], [], ["x"]) is False
        assert decide_rollback(None, 8.0, [], [], []) is False

    def test_dolly_factor_bounded_direction(self):
        f = dolly_factor("camera_pull_back", 0.85, target_coverage=0.40)
        assert f > 1.4
        assert dolly_factor("camera_pull_back", 0.20) == 1.0  # wrong direction
        f2 = dolly_factor("camera_move_closer", 0.15)
        assert 0.0 < f2 < 0.75
        assert dolly_factor("camera_move_closer", 0.5) == 1.0

    def test_light_factor_sizes_from_measured_excess(self):
        # frozen issue tolerance: highlight budget 0.08 + 0.02 = 0.10
        assert light_factor("exposure_reduce_highlights",
                            metrics(pct_white=0.40)) < 0.5
        assert light_factor("exposure_reduce_highlights",
                            metrics(pct_white=0.12)) < 0.9
        assert light_factor("exposure_reduce_highlights",
                            metrics(pct_white=0.005)) == pytest.approx(0.85)
        # frozen shadow tolerance: 0.12 + 0.03 = 0.15
        assert light_factor("exposure_raise_blacks",
                            metrics(pct_black=0.5)) > 2.0
        assert light_factor("exposure_raise_blacks",
                            metrics(pct_black=0.05, mean_luma=120)) == 1.2
