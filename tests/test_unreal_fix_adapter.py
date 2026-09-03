"""Offline tests for core.unreal_fix_adapter using a recording fake bridge:
operation selection, bounded factors, read-back verification, world save and
rollback-on-regression are exercised without any Unreal editor.
"""
from __future__ import annotations

from types import SimpleNamespace

from core.unreal_fix_adapter import UnrealFixAdapter, ViewportNotVisibleError

SUN = {"label": "ACC_Sun", "path": "/Game/ShowcaseMap.ACC_Sun",
       "class": "DirectionalLight", "intensity": 500.0}


class FakeBridge:
    """Responds to the adapter's generated python snippets with structured
    readbacks so the adapter's verification paths run end to end."""

    def __init__(self):
        self.calls = []
        self.sun_intensity = 500.0

    def execute_python(self, code):
        self.calls.append(code)
        if "RedrawAllViewports" in code:
            return {"ok": True, "result": {"ok": True}}
        if "save_dirty_packages" in code:
            return {"ok": True, "result": {"ok": True, "saved": True}}
        if '"lights": lights' in code:
            return {"ok": True,
                    "result": {"lights": [dict(SUN, intensity=self.sun_intensity)]}}
        if 'set_editor_property("intensity"' in code:
            before = float(self.sun_intensity)
            # parse the requested new value from the generated snippet
            import re
            m = re.search(r"newv = min\(float\(\d+\.?\d*\), max\(0\.5, before \* float\(([\d.]+)\)\)\)", code)
            factor = float(m.group(1)) if m else 0.5
            after = min(5000.0, max(0.5, before * factor))
            self.sun_intensity = after
            return {"ok": True, "result": {"ok": True, "before": before,
                                           "after": round(after, 2),
                                           "label": "ACC_Sun",
                                           "class": "DirectionalLight"}}
        if "get_level_viewport_camera_info" in code and "set_level_viewport" in code:
            return {"ok": True, "result": {"ok": True, "loc": [1.0, 2.0, 3.0],
                                           "rot": [0.0, -1.0, 70.0]}}
        return {"ok": True, "result": {"ok": True}}


def m(overall=7.0, **kw):
    base = dict(ok=True, subject_coverage=0.3486, head_clipped=False,
                stale=False, bands=[], roll_deg=0.0, mean_luma=131.0,
                pct_white=0.3, pct_black=0.05, issues=[], ui_bbox=[1, 2, 3, 4])
    base.update(kw)
    return SimpleNamespace(**base)


def s(overall=7.0):
    return SimpleNamespace(overall=overall)


def test_unsupported_action_is_honest():
    bridge = FakeBridge()
    a = UnrealFixAdapter(bridge)
    rec = a.apply("do_something_crazy", m(), s())
    assert rec["ok"] is False
    assert "unsupported" in rec["error"]
    assert rec["note"]


def test_light_reduction_op_readback_and_save(tmp_path):
    bridge = FakeBridge()
    a = UnrealFixAdapter(bridge)
    rec = a.apply("exposure_reduce_highlights", m(pct_white=0.4), s(6.5))
    assert rec["ok"] is True
    assert rec["world_saved"] is True
    assert rec["ops"][0]["op"] == "light_intensity_scale"
    factor = rec["ops"][0]["factor"]
    assert 0.0 < factor < 1.0
    # fake bridge read back before/after
    assert rec["readback"]["after"] < rec["readback"]["before"]
    assert bridge.sun_intensity < 500.0
    assert rec["note"]
    # history grew and snapshots recorded for rollback
    assert len(a.history) == 1
    assert rec["snapshot"]["type"] == "light"
    assert rec["snapshot"]["path"] == SUN["path"]


def test_rollback_on_regression(tmp_path):
    bridge = FakeBridge()
    a = UnrealFixAdapter(bridge)
    # simulate a previous successful op that regressed the frame
    a.history.append({
        "ok": True,
        "action": "lighting_raise_key",
        "snapshot": {"type": "light", "path": SUN["path"], "intensity": 500.0},
        "score_before": 6.0,
        "defects_before": ["WHITE_CLIPPING"],
    })
    rec = a.apply("exposure_reduce_highlights", m(pct_white=0.4), s(5.5),
                  pass_index=2)
    assert rec["rollback"] is True
    # the restore ran through the same verified light op path
    assert any(op["op"] == "rollback" for op in rec["ops"])


def test_camera_roll_reset(tmp_path):
    bridge = FakeBridge()
    a = UnrealFixAdapter(bridge)
    rec = a.apply("camera_roll_reset", m(roll_deg=8.0), s(6.0))
    assert rec["ok"] is True
    assert rec["ops"][0]["op"] == "viewport_camera_roll_reset"


def test_capture_rejects_hidden_viewport():
    class HiddenBridge(FakeBridge):
        def execute_python(self, code):
            self.calls.append(code)
            if "capture_active_viewport_detailed" in code:
                return {"ok": True, "result": {
                    "ok": True,
                    "diag": ("OK|source=LevelViewport[1]|perspective=1"
                             "|visible=0|width=1994|height=735|bytes=1"),
                    "size": -1}}
            return super().execute_python(code)

    import pytest
    bridge = HiddenBridge()
    a = UnrealFixAdapter(bridge, visible_retries=0)
    with pytest.raises(ViewportNotVisibleError):
        a.capture("does/not/exist.png")
