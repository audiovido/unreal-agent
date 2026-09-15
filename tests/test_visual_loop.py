"""Regression tests for core.visual_loop — the autonomous capture -> measure
-> score -> fix -> recapture loop. Fully offline: a fake stage renders
synthetic PNGs and simulates runtime fixes, so defect routing, changed
strategy, stale-hash detection, the technical+visual completion gate and
external-blocker honesty are all tested deterministically."""
from __future__ import annotations

from core.visual_loop import AutonomousVisualLoop
from tests.img_helpers import hero_locator, make_scene, right_panel_locator

LOCATORS = {"subject_locator": hero_locator,
            "ui_locator": right_panel_locator}

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


class FakeStage:
    """Simulated runtime: the visible subject window shrinks with
    camera_pull_back and is re-framed exactly by camera_framing_recompute."""

    def __init__(self, tmp_path, pull=0.80, fixes=True):
        self.out = tmp_path
        self.n = 0
        self.pull = pull
        self.fixes = fixes
        self.subj = (0.12, 0.56, 60, 460)   # deliberately SUBJECT_TOO_LARGE

    def capture(self) -> str:
        p = str(self.out / f"pass_{self.n}.png")
        make_scene(subject=self.subj).save(p, format="PNG")
        self.n += 1
        return p

    def apply(self, action, metrics, score, target, index):
        if not self.fixes:
            return f"{action}: (adapter ignoring)"
        if action == "camera_pull_back":
            x0, x1, y0, y1 = self.subj
            self.subj = (x0, x1 + (y0 + (x1 - x0)) * 0, y0,
                         y0 + (y1 - y0) * self.pull)
            self.subj = (x0, x0 + (x1 - x0) * self.pull, y0,
                         y0 + (y1 - y0) * self.pull)
            return "camera_pull_back: distance x0.80"
        if action == "camera_framing_recompute":
            self.subj = (0.12, 0.46, 60, 360)
            return "camera_framing_recompute: exact target framing"
        if action == "capture_force_fresh":
            return "capture_force_fresh: presentation reset requested"
        return f"{action}: applied"


def test_loop_converges_by_pulling_back(tmp_path):
    stage = FakeStage(tmp_path)
    loop = AutonomousVisualLoop(TARGET, capture=stage.capture,
                                apply=stage.apply, max_passes=8, **LOCATORS)
    res = loop.run()
    assert res["status"] == "COMPLETE"
    assert len(res["passes"]) == 2
    assert res["passes"][0]["verdict"] == "REVISE"
    assert res["passes"][0]["defects"] == ["SUBJECT_TOO_LARGE"]
    assert res["passes"][0]["actions"] == ["camera_pull_back"]
    assert res["passes"][1]["verdict"] == "PASS"
    assert res["passes"][1]["defects"] == []
    assert res["final"]["score"]["overall"] >= 8.0
    # changed-strategy log contract
    log = res["action_logs"][0]
    assert log["problem"] == "SUBJECT_TOO_LARGE"
    assert log["change"].startswith("camera_pull_back")
    assert log["before"]["subject_coverage"] > log["after"]["subject_coverage"]
    assert log["result"] == "RESOLVED"
    # self critique accepts the delivered frame
    assert res["self_critique"]["verdict"] == "ACCEPT"
    assert res["completion_gate"]["product_complete"] is True


def test_changed_strategy_when_first_fix_insufficient(tmp_path):
    stage = FakeStage(tmp_path, pull=0.97)   # too weak: subject stays too large
    loop = AutonomousVisualLoop(TARGET, capture=stage.capture,
                                apply=stage.apply, max_passes=8, **LOCATORS)
    res = loop.run()
    assert res["status"] == "COMPLETE"
    assert res["passes"][-1]["verdict"] == "PASS"
    changes = [log["change"] for log in res["action_logs"]]
    assert changes[0].startswith("camera_pull_back")
    assert changes[1].startswith("camera_framing_recompute")
    assert changes[0] != changes[1]          # strategy advanced, not repeated
    assert res["action_logs"][-1]["result"] == "RESOLVED"


def test_loop_stops_on_stale_frozen_presentation(tmp_path):
    stage = FakeStage(tmp_path, fixes=False)
    loop = AutonomousVisualLoop(TARGET, capture=stage.capture,
                                apply=stage.apply, max_passes=8, **LOCATORS)
    res = loop.run()
    assert res["status"] == "PARTIAL"
    assert len(res["passes"]) == 3           # never loops forever on a freeze
    assert res["passes"][1]["defects"][0] == "STALE_CAPTURE"
    problems = [log["problem"] for log in res["action_logs"]]
    assert problems == ["SUBJECT_TOO_LARGE", "STALE_CAPTURE"]
    assert res["self_critique"]["verdict"] == "REVISE"


def test_technical_gate_blocks_completion_even_when_visual_passes(tmp_path):
    stage = FakeStage(tmp_path)
    loop = AutonomousVisualLoop(
        TARGET, capture=stage.capture, apply=stage.apply, max_passes=8,
        technical_ok=lambda: (False, {"reason": "runtime check failed"}),
        **LOCATORS)
    res = loop.run()
    assert res["final"]["score"]["overall"] >= 8.0   # visual passed...
    assert res["status"] == "PARTIAL"                 # ...but product did not
    assert res["completion_gate"]["technical_pass"] is False
    assert res["completion_gate"]["visual_pass"] is True
    assert res["completion_gate"]["product_complete"] is False


def test_passing_frame_finishes_in_one_pass(tmp_path):
    stage = FakeStage(tmp_path)
    stage.subj = (0.12, 0.46, 60, 360)       # already at target framing
    loop = AutonomousVisualLoop(TARGET, capture=stage.capture,
                                apply=stage.apply, max_passes=8, **LOCATORS)
    res = loop.run()
    assert res["status"] == "COMPLETE"
    assert len(res["passes"]) == 1
    assert res["passes"][0]["verdict"] == "PASS"
    assert res["iterations"] == 1


def test_external_blocker_reported_honestly(tmp_path):
    stage = FakeStage(tmp_path, fixes=False)
    loop = AutonomousVisualLoop(
        TARGET, capture=stage.capture, apply=stage.apply, max_passes=8,
        external_blocker="PHOTOREAL_CHARACTER_SOURCE_REQUIRED", **LOCATORS)
    res = loop.run()
    assert res["external_blocker"] == "PHOTOREAL_CHARACTER_SOURCE_REQUIRED"
    # blocker waives only impossible categories — never fabricates success
    assert res["status"] in ("PARTIAL", "BLOCKED")
    assert res["final"]["score"]["overall"] < 8.0


def test_blocker_does_not_block_otherwise_complete_work(tmp_path):
    stage = FakeStage(tmp_path)
    loop = AutonomousVisualLoop(
        TARGET, capture=stage.capture, apply=stage.apply, max_passes=8,
        external_blocker="PHOTOREAL_CHARACTER_SOURCE_REQUIRED", **LOCATORS)
    res = loop.run()
    assert res["status"] == "COMPLETE"
    assert res["external_blocker"] == "PHOTOREAL_CHARACTER_SOURCE_REQUIRED"


def test_post_measure_hook_applies_ground_truth(tmp_path):
    """The _post_measure hook runs after measurement and before defect
    derivation, so adapters can correct proxy artifacts (e.g. zero an
    image-derived roll when the runtime reads level)."""
    calls = []

    class GT(AutonomousVisualLoop):
        def _post_measure(self, m):
            calls.append(m.hash_md5_12)
            m.roll_deg = 0.0
            m.issues[:] = [i for i in m.issues if "CAMERA_ROLL" not in i]

    stage = FakeStage(tmp_path)          # framing is passable out of the box
    stage.subj = (0.12, 0.46, 60, 360)
    loop = GT(TARGET, capture=stage.capture, apply=stage.apply,
              max_passes=8, **LOCATORS)
    res = loop.run()
    assert calls and res["status"] == "COMPLETE"
    assert res["passes"][0]["defects"] == []


def test_derive_white_clipping_threshold(tmp_path):
    """WHITE_CLIPPING must trigger at the highlight_clipping_max bound, not
    at a relaxed 2x bound (so the loop actually fixes blown frames)."""
    from types import SimpleNamespace

    target = dict(TARGET)
    target["lighting"] = {"highlight_clipping_max": 0.08,
                           "shadow_crush_max": 0.12}

    def make_loop(white):
        class _L(AutonomousVisualLoop):
            def __init__(self):
                super().__init__(target, capture=lambda: "x.png",
                                 apply=lambda *a, **k: "noop")

        loop = _L()
        m = SimpleNamespace(
            stale=False, bands=[], head_clipped=False,
            subject_bbox=[100, 40, 400, 380], subject_coverage=0.24,
            pct_white=white, pct_black=0.0, ui_bbox=[540, 30, 880, 470],
            ui_screen_coverage=0.30, roll_deg=0.0, entropy=7.0,
            std_luma=60.0, mean_luma=90.0)
        s = SimpleNamespace(lighting=8.0)
        return loop, m, s

    # trigger line: highlight_clipping_max + 0.02 == 0.10
    loop, m, s = make_loop(0.12)         # 12% blown -> flagged
    assert "WHITE_CLIPPING" in loop._derive_defects(m, s)
    loop, m, s = make_loop(0.11)         # just over the line -> flagged
    assert "WHITE_CLIPPING" in loop._derive_defects(m, s)
    loop, m, s = make_loop(0.09)         # just under the line -> clean
    assert "WHITE_CLIPPING" not in loop._derive_defects(m, s)

    # a premium target (0.05 budget) must flag at the tighter 0.07 line
    ptarget = dict(TARGET)
    ptarget["lighting"] = {"highlight_clipping_max": 0.05,
                           "shadow_crush_max": 0.10}

    class _P(AutonomousVisualLoop):
        def __init__(self):
            super().__init__(ptarget, capture=lambda: "x.png",
                             apply=lambda *a, **k: "noop")

    loop2 = _P()
    m2 = SimpleNamespace(
        stale=False, bands=[], head_clipped=False,
        subject_bbox=[100, 40, 400, 380], subject_coverage=0.24,
        pct_white=0.09, pct_black=0.0, ui_bbox=[540, 30, 880, 470],
        ui_screen_coverage=0.30, roll_deg=0.0, entropy=7.0,
        std_luma=60.0, mean_luma=90.0)
    assert "WHITE_CLIPPING" in loop2._derive_defects(m2, SimpleNamespace(lighting=8.0))


def test_vision_review_integrated_into_loop(tmp_path):
    stage = FakeStage(tmp_path)
    vision_calls = []

    def vision(path):
        vision_calls.append(path)
        return {"score": 9.0, "pass": True, "issues": []}

    loop = AutonomousVisualLoop(TARGET, capture=stage.capture,
                                apply=stage.apply, vision=vision, max_passes=8,
                                **LOCATORS)
    res = loop.run()
    assert res["status"] == "COMPLETE"
    assert vision_calls
    assert res["passes"][-1]["vision"]["pass"] is True