"""Pure-geometry camera framing math for Unreal Engine cameras.

No dependency on the ``unreal`` Python module: this file is importable and
unit-testable on the backend host, and its functions can also be executed
verbatim inside the editor's Python via the bridge.

Conventions (match Unreal):
- world axes: X (forward-ish), Y (right), Z (up)
- camera rotation: yaw 0 = +X, yaw 90 = +Y (Unreal left-handed); pitch + = up
- screen space: ndc x/y in [-1, 1]; +x is screen-right, +y is screen-up
- fov is the VERTICAL field of view in degrees

Only keyword-based rotations are produced (never positional Rotator tuples).
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

Vec3 = Sequence[float]


def forward_from_rotation(pitch_deg: float, yaw_deg: float) -> Tuple[float, float, float]:
    p = math.radians(pitch_deg)
    y = math.radians(yaw_deg)
    fx = math.cos(p) * math.cos(y)
    fy = math.cos(p) * math.sin(y)
    fz = math.sin(p)
    return fx, fy, fz


def project(
    cam_pos: Vec3,
    pitch_deg: float,
    yaw_deg: float,
    fov_deg: float,
    aspect: float,
    world_pt: Vec3,
) -> Optional[Tuple[float, float, float]]:
    """Project a world point to (ndc_x, ndc_y, depth). None if behind the camera."""
    fwd = forward_from_rotation(pitch_deg, yaw_deg)
    y = math.radians(yaw_deg)
    right = (-math.sin(y), math.cos(y), 0.0)
    # Screen-up is fwd x right in UE handedness (verified against world +Z
    # when the camera looks -Y: right=(+X), up=(+Z)).
    up = (
        fwd[1] * right[2] - fwd[2] * right[1],
        fwd[2] * right[0] - fwd[0] * right[2],
        fwd[0] * right[1] - fwd[1] * right[0],
    )
    rel = (world_pt[0] - cam_pos[0], world_pt[1] - cam_pos[1], world_pt[2] - cam_pos[2])
    depth = fwd[0] * rel[0] + fwd[1] * rel[1] + fwd[2] * rel[2]
    if depth <= 0.001:
        return None
    half_h = math.tan(math.radians(fov_deg / 2.0))
    half_w = half_h * aspect
    sx = (right[0] * rel[0] + right[1] * rel[1] + right[2] * rel[2]) / (depth * half_w)
    sy = (up[0] * rel[0] + up[1] * rel[1] + up[2] * rel[2]) / (depth * half_h)
    return sx, sy, depth


def pose_for_framing(
    head_world: Vec3,
    *,
    distance: float = 260.0,
    fov_deg: float = 56.0,
    aspect: float = 1.79,
    head_ndc_x: float = -0.26,
    head_ndc_y: float = 0.28,
    yaw_deg: float = -90.0,
) -> Dict[str, float]:
    """Solve a camera pose that places ``head_world`` at a target screen spot.

    The camera keeps the given (fixed) yaw so the composition axis is stable;
    position + pitch are solved so the head lands at ``head_ndc`` on screen.

    head_ndc_y > 0 means the head sits ABOVE screen center (headroom above it).
    Returns dict with location [x,y,z], pitch, yaw, fov — all keyword-safe
    inputs for unreal.Rotator(pitch=..., yaw=..., roll=0).
    """
    half_h = math.tan(math.radians(fov_deg / 2.0))
    half_w = half_h * aspect
    # horizontal: moving the camera opposite the target ndc shifts the subject
    cam_x = head_world[0] - head_ndc_x * half_w * distance
    cam_y = head_world[1] + distance  # +Y : camera sits "north" of the subject
    # vertical: pick a comfortable camera height just under the head, then solve
    # pitch so the head lands at head_ndc_y above center.
    cam_z = head_world[2] - 52.0
    tan_pitch = (head_world[2] - cam_z - head_ndc_y * half_h * distance) / distance
    pitch_deg = math.degrees(math.atan(tan_pitch))
    return {
        "location_x": cam_x,
        "location_y": cam_y,
        "location_z": cam_z,
        "pitch": pitch_deg,
        "yaw": yaw_deg,
        "roll": 0.0,
        "fov": fov_deg,
        "distance": distance,
    }


def framing_report(
    cam_pos: Vec3,
    pitch_deg: float,
    yaw_deg: float,
    fov_deg: float,
    aspect: float,
    points: Dict[str, Vec3],
) -> Dict[str, object]:
    """Project labelled world points for a camera; used to VERIFY a pose."""
    out: Dict[str, object] = {}
    for key, pt in points.items():
        proj = project(cam_pos, pitch_deg, yaw_deg, fov_deg, aspect, pt)
        out[key] = None if proj is None else [round(proj[0], 4), round(proj[1], 4), round(proj[2], 1)]
    return out


def recommended_camera_for_avatar(
    avatar_loc: Vec3,
    *,
    head_height_cm: float = 175.0,
    distance: float = 260.0,
    fov_deg: float = 56.0,
    aspect: float = 1.786,
) -> Dict[str, object]:
    """One-call helper: camera pose for a standing character at avatar_loc.

    Head assumed at avatar_loc.z + head_height_cm. Targets: head at 28% above
    center, slightly left of center (chat panel keeps the right side).
    """
    head = (avatar_loc[0], avatar_loc[1], avatar_loc[2] + head_height_cm)
    pose = pose_for_framing(
        head,
        distance=distance,
        fov_deg=fov_deg,
        aspect=aspect,
        head_ndc_x=-0.24,
        head_ndc_y=0.26,
    )
    pose["head_world"] = [round(v, 2) for v in head]
    return pose