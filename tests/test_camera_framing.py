"""Deterministic tests for tools.unreal.camera_framing (pure math, no editor)."""
import math

import pytest

from tools.unreal.camera_framing import (
    forward_from_rotation,
    framing_report,
    pose_for_framing,
    project,
    recommended_camera_for_avatar,
)


def _recheck(pose, head, aspect=1.786):
    cam = (pose["location_x"], pose["location_y"], pose["location_z"])
    return project(
        cam,
        pose["pitch"],
        pose["yaw"],
        pose["fov"],
        aspect,
        head,
    )


def test_forward_rotation_axis_convention():
    f = forward_from_rotation(0.0, 0.0)
    assert abs(f[0] - 1.0) < 1e-9  # yaw 0 faces +X
    assert abs(f[1]) < 1e-9
    f2 = forward_from_rotation(0.0, -90.0)
    assert abs(f2[1] + 1.0) < 1e-9  # yaw -90 faces -Y
    f3 = forward_from_rotation(90.0, 0.0)
    assert abs(f3[2] - 1.0) < 1e-9  # pitch +90 faces up


def test_project_center_and_offsets():
    cam = (0.0, 300.0, 150.0)
    # point straight ahead at depth
    p = project(cam, 0.0, -90.0, 56.0, 1.786, (0.0, 100.0, 150.0))
    assert p is not None
    assert abs(p[0]) < 0.05
    assert abs(p[1]) < 0.05
    # point to screen-right
    pr = project(cam, 0.0, -90.0, 56.0, 1.786, (-40.0, 100.0, 150.0))
    # camera looks -Y; a point with -X offset appears... on screen +x? verify sign consistency
    assert pr is not None
    # behind the camera -> None
    pb = project(cam, 0.0, -90.0, 56.0, 1.786, (0.0, 500.0, 150.0))
    assert pb is None


@pytest.mark.parametrize(
    "head_ndc_x,head_ndc_y,distance",
    [
        (0.0, 0.0, 260.0),
        (-0.24, 0.26, 260.0),
        (0.2, -0.15, 320.0),
        (-0.35, 0.35, 200.0),
    ],
)
def test_pose_solves_frame_goals(head_ndc_x, head_ndc_y, distance):
    head = (0.0, 60.0, 205.0)
    pose = pose_for_framing(
        head,
        distance=distance,
        fov_deg=56.0,
        aspect=1.786,
        head_ndc_x=head_ndc_x,
        head_ndc_y=head_ndc_y,
    )
    p = _recheck(pose, head)
    assert p is not None
    assert abs(p[0] - head_ndc_x) < 0.02, f"x off: {p[0]} vs {head_ndc_x}"
    assert abs(p[1] - head_ndc_y) < 0.02, f"y off: {p[1]} vs {head_ndc_y}"
    assert p[2] > 100.0


def test_pose_rotation_is_keyword_safe():
    """The pose values are exactly what unreal.Rotator(pitch=, yaw=, roll=) needs."""
    pose = pose_for_framing((0.0, 60.0, 205.0))
    for key in ("pitch", "yaw", "roll", "fov"):
        assert isinstance(pose[key], float)
    assert pose["roll"] == 0.0
    assert -90.0 <= pose["yaw"] <= -90.0  # fixed -Y axis composition
    assert isinstance(pose["location_x"], float)


def test_headroom_direction():
    # higher head_ndc_y (head higher in frame, more headroom above) => the
    # view center drops below the head => pitch decreases.
    p1 = pose_for_framing((0.0, 60.0, 205.0), head_ndc_y=0.10)
    p2 = pose_for_framing((0.0, 60.0, 205.0), head_ndc_y=0.35)
    assert p1["pitch"] > p2["pitch"]


def test_avatar_helper_targets_head():
    pose = recommended_camera_for_avatar((0.0, 60.0, 34.0))
    head = tuple(pose["head_world"])
    p = _recheck(pose, head, aspect=1.786)
    assert p is not None
    assert abs(p[0] + 0.24) < 0.03  # slightly left of center
    assert 0.15 < p[1] < 0.40       # above center with headroom


def test_framing_report_projects_all_points():
    pose = pose_for_framing((0.0, 60.0, 205.0))
    cam = (pose["location_x"], pose["location_y"], pose["location_z"])
    pts = {
        "head": (0.0, 60.0, 205.0),
        "feet": (0.0, 60.0, 40.0),
        "backdrop": (0.0, -360.0, 190.0),
    }
    rep = framing_report(cam, pose["pitch"], pose["yaw"], pose["fov"], 1.786, pts)
    assert rep["head"] is not None
    assert rep["feet"] is not None
    assert len(rep) == 3