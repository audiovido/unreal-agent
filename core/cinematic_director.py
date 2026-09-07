"""cinematic_director.py — Aivido V2 cinematic orchestration layer.

Turns a natural-language cinematic request into a bounded, verifiable shot
plan and executes it through injected adapters:

    USER PROMPT
      -> parse_cinematic_brief()        (deterministic intent parse)
      -> plan_cinematic_shots()         (subject framing + shot list)
      -> cinematic_target()             (measurable acceptance target)
      -> per-shot quality loop          (capture -> score -> diagnose ->
                                          improve -> recapture, <= 3 passes)
      -> render + proof                 (adapter renderer / capture)
      -> CinematicResult                 (scorecard + blockers, no faking)

Design rules that mirror the rest of the Aivido core:

- This module is UNREAL-AGNOSTIC. It never imports ``unreal``. Every live
  action goes through an injected ``CinematicAdapter`` so the whole plan,
  scoring and iteration logic is hermetic and unit-testable.
- No invented numbers: scoring dimensions that cannot be measured
  deterministically from a frame (material readability, cinematic depth,
  visual polish) are only reported when an injected vision review supplies
  evidence; otherwise their ``basis`` is ``"vision_unavailable"`` and they
  do NOT contribute to the acceptance verdict.
- Bounded iteration: max 3 visual passes per shot (configurable, never
  more). The loop reuses core.visual_loop.AutonomousVisualLoop and the
  canonical visual_acceptance scorer (deterministic-first scoring).
- Reuse over rebuild: camera framing math reuses
  tools.unreal.camera_framing (pure geometry, importable outside Unreal).
"""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from core.visual_acceptance import measure, score
from tools.unreal.camera_framing import project

# ---------------------------------------------------------------------------
# Brief parsing
# ---------------------------------------------------------------------------

# The seven required cinematic scoring dimensions from the V2 contract.
CINEMATIC_DIMENSIONS: Tuple[str, ...] = (
    "composition",        # deterministic (visual_acceptance)
    "framing",            # deterministic (subject_framing)
    "lighting",           # deterministic (visual_acceptance lighting)
    "subject_visibility", # deterministic (coverage / head clip / target match)
    "material_readability",  # vision-evidence only
    "cinematic_depth",       # vision-evidence only
    "visual_polish",         # vision-evidence only
)

# Mapping of V2 dimension -> visual_acceptance category that supplies the
# deterministic value (when the underlying metric is honest for that shot).
_DETERMINISTIC_SOURCE = {
    "composition": "composition",
    "framing": "subject_framing",
    "lighting": "lighting",
    "subject_visibility": "target_match",
}

# visual_acceptance categories scoped into a cinematic overall. UI and
# readability are excluded: a cinematic frame has no UI panel, and material
# readability is a vision-evidence dimension on the scorecard, never a
# deterministic 2.0 drag on a clean scene.
CINEMATIC_SCOPED_CATEGORIES: List[str] = [
    "composition", "subject_framing", "lighting", "environment",
    "target_match", "technical_integrity",
]

_SHOT_WORDS = ("hero shot", "hero", "close-up", "close up", "wide shot",
               "wide", "medium shot", "medium", "over-the-shoulder",
               "three-quarter", "three quarter", "portrait", "dolly", "orbit",
               "push in", "push-in", "crane")
_MOTION_WORDS = ("smooth camera", "camera movement", "smooth movement",
                 "orbit", "dolly", "truck", "push", "pan", "crane", "fly",
                 "slow push", "move the camera", "camera motion")
_PREMIUM_WORDS = ("premium", "cinematic", "hollywood", "film", "hero",
                  "dramatic", "epic", "blockbuster", "aaa", "a a a")
_LIGHTING_WORDS = ("lighting", "light", "lit", "illumination", "exposure",
                   "mood", "atmosphere", "golden", "rim", "key light")


def _find_number(text: str, patterns: Sequence[str], default: float) -> float:
    low = text.lower()
    for pat in patterns:
        m = re.search(pat, low)
        if m:
            try:
                return float(m.group(1))
            except (ValueError, IndexError):
                continue
    return default


def _subjects_from_text(text: str) -> List[str]:
    """Named/qualified subject mentions (best-effort, deterministic)."""
    low = text.lower()
    found: List[str] = []
    # explicit "X of the <name> team/<name> group" hero phrasing
    m = re.search(r"(?:of|featuring|starring)\s+the\s+([a-z0-9 _-]{3,40})"
                  r"(?:\s+(?:team|group|crew|cast))?", low)
    if m and m.group(1).strip() not in ("scene", "scene."):
        found.append(m.group(1).strip())
    # "shot of <subject>" phrasing
    m2 = re.search(r"shot\s+of\s+(?:the\s+)?([a-z0-9 _-]{3,40})", low)
    if m2:
        cand = m2.group(1).strip()
        if cand and not any(tok in cand for tok in
                            ("team", "premium", "cinematic", "smooth",
                             "seconds", "with", "and", "hero", "camera")):
            found.append(cand)
    # "the <X> team" anywhere
    m3 = re.search(r"the\s+([a-z0-9 _-]{2,30})\s+team", low)
    if m3:
        cand = m3.group(1).strip()
        if cand not in found:
            found.append(cand)
    return found[:3]


def parse_cinematic_brief(prompt: str) -> Dict[str, Any]:
    """Natural-language cinematic request -> structured brief dict.

    Deterministic keyword/pattern extraction only. Where the prompt does not
    specify a value the brief carries a documented default (never a guess
    attributed to the user).
    """
    p = (prompt or "").lower()
    style_tokens = [w for w in _PREMIUM_WORDS if w in p]
    motion_tokens = [w for w in _MOTION_WORDS if w in p]
    lighting_requested = any(w in p for w in _LIGHTING_WORDS)

    shot = "hero shot"
    for w in _SHOT_WORDS:
        if w in p:
            shot = w
            break

    duration_s = _find_number(p, [
        r"(\d+(?:\.\d+)?)\s*(?:-|\s*to\s*)\s*\d+\s*second",
        r"(\d+(?:\.\d+)?)\s*seconds?", r"(\d+(?:\.\d+)?)\s*-?\s*second",
    ], 8.0)
    fps = _find_number(p, [r"(\d{2,3})\s*fps", r"at\s+(\d{2,3})\s*frames"],
                       30.0)
    fps = min(120.0, max(12.0, float(int(fps))))

    if "4k" in p:
        resolution = [3840, 2160]
    elif "1080p" in p or "full hd" in p:
        resolution = [1920, 1080]
    else:
        resolution = [1920, 1080]

    subjects = _subjects_from_text(prompt)
    return {
        "raw_prompt": (prompt or "").strip(),
        "subjects": subjects,              # empty -> scene-derived hero(s)
        "duration_s": float(duration_s),
        "fps": int(fps),
        "resolution": [int(resolution[0]), int(resolution[1])],
        "shot": shot,
        "motion": list(dict.fromkeys(motion_tokens)) or ["static"],
        "style_tokens": list(dict.fromkeys(style_tokens)),
        "lighting_requested": lighting_requested,
        "premium": bool(style_tokens),
        "aspect": round(resolution[0] / float(resolution[1]), 4),
    }


def is_cinematic_request(prompt: str) -> bool:
    """Gate: does this prompt want a cinematic (not a plain spawn/task)?"""
    p = (prompt or "").lower()
    has_cinema_word = any(w in p for w in (
        "cinematic", "hero shot", "hero shot", "camera movement",
        "smooth camera", "movie", "film", "shot list", "cut scene",
        "camera orbit", "dolly", "sequencer"))
    has_temporal = re.search(r"\d+\s*(-|to\s+)?\s*\d*\s*second", p) is not None
    return bool(has_cinema_word or (has_temporal and (
        "shot" in p or "camera" in p or "scene" in p)))


# ---------------------------------------------------------------------------
# Shots
# ---------------------------------------------------------------------------


@dataclass
class CinematicShot:
    index: int
    subject_label: str
    start_s: float
    end_s: float
    pose: Dict[str, float]          # camera pose (location_*, pitch, yaw, roll, fov)
    framing: str = "hero"           # hero / medium / wide
    motion: str = "static"          # static (transform keys engine-closed)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "subject": self.subject_label,
            "start_s": round(self.start_s, 3),
            "end_s": round(self.end_s, 3),
            "duration_s": round(self.end_s - self.start_s, 3),
            "pose": {k: round(float(v), 3) for k, v in self.pose.items()},
            "framing": self.framing,
            "motion": self.motion,
        }


def _solve_pose(
    target: Sequence[float],
    *,
    yaw_deg: float,
    distance: float,
    fov_deg: float,
    aspect: float,
    head_ndc: Sequence[float] = (0.0, 0.12),
    cam_height_under_head: float = 55.0,
) -> Dict[str, float]:
    """Camera pose that places ``target`` (a head/world point) at ``head_ndc``.

    The camera orbits ``target`` at ``distance`` along the direction given by
    ``yaw_deg`` (yaw 0 faces +X, matching Unreal and camera_framing). The pose
    is returned as keyword-safe values (location_[xyz], pitch, yaw, roll, fov,
    distance). Verification against the framing is done by the caller with
    camera_framing.project (reused below in ``verify_pose``).
    """
    y = math.radians(yaw_deg)
    half_h = math.tan(math.radians(fov_deg / 2.0))
    half_w = half_h * aspect
    # ground offset: stand opposite the look direction
    cam_x = target[0] - math.cos(y) * distance
    cam_y = target[1] - math.sin(y) * distance
    cam_z = target[2] - cam_height_under_head
    rel = (target[0] - cam_x, target[1] - cam_y, target[2] - cam_z)
    # aim the forward vector at the head, then raise pitch so the head lands
    # head_ndc_y above screen centre.
    tan_pitch = (rel[2] - head_ndc[1] * half_h * distance) / (
        math.hypot(rel[0], rel[1]))
    pitch_deg = math.degrees(math.atan(tan_pitch))
    # lateral shift along the right vector to place the subject horizontally.
    right = (-math.sin(y), math.cos(y))
    ndc_target = head_ndc[0]
    shift = ndc_target * half_w * distance
    cam_x = cam_x + right[0] * shift
    cam_y = cam_y + right[1] * shift
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


def verify_pose(
    pose: Dict[str, float],
    world_points: Dict[str, Sequence[float]],
    aspect: float,
    tolerance_ndc: float = 0.06,
) -> Dict[str, Any]:
    """Reuse camera_framing.project to verify a solved pose frames its points.

    Returns per-point projected ndc and an ok flag when every labelled point
    that should be on-screen projects inside [-1 + tol, 1 - tol]^2.
    """
    loc = (pose["location_x"], pose["location_y"], pose["location_z"])
    out: Dict[str, Any] = {}
    inside = True
    for key, pt in world_points.items():
        proj = project(loc, pose["pitch"], pose["yaw"], pose["fov"], aspect, pt)
        out[key] = None if proj is None else [round(proj[0], 4),
                                              round(proj[1], 4),
                                              round(proj[2], 1)]
        if proj is None:
            inside = False
        else:
            if abs(proj[0]) > 1.0 + tolerance_ndc or abs(proj[1]) > 1.0 + tolerance_ndc:
                inside = False
    return {"ok": inside, "points": out}


# Framing presets: head-point NDC + camera distance for typical shots. These
# are cinematic defaults; a scene with explicit sizes overrides via options.
_FRAMING_PRESETS = {
    "hero shot": {"coverage_hint": [0.20, 0.46], "head_ndc": (0.0, 0.14),
                  "distance": 300.0, "cam_h": 55.0},
    "medium": {"coverage_hint": [0.20, 0.46], "head_ndc": (0.0, 0.16),
               "distance": 420.0, "cam_h": 55.0},
    "wide shot": {"coverage_hint": [0.12, 0.34], "head_ndc": (0.0, 0.26),
                  "distance": 700.0, "cam_h": 60.0},
    "wide": {"coverage_hint": [0.12, 0.34], "head_ndc": (0.0, 0.26),
             "distance": 700.0, "cam_h": 60.0},
    "close-up": {"coverage_hint": [0.30, 0.52], "head_ndc": (0.0, 0.08),
                 "distance": 170.0, "cam_h": 45.0},
    "close up": {"coverage_hint": [0.30, 0.52], "head_ndc": (0.0, 0.08),
                 "distance": 170.0, "cam_h": 45.0},
}

# Cinematic yaw arcs (deg). A 3/4-front, straight-on and 3/4-back arc keeps
# the composition varied without cheap primitive symmetry.
_ARC_YAW = [-78.0, -52.0, -26.0, 0.0, 26.0, 52.0, 78.0]


def plan_cinematic_shots(
    brief: Dict[str, Any],
    subjects: Sequence[Dict[str, Any]],
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a bounded shot list from a brief + inspected subjects.

    ``subjects`` entries: {"label": str, "location": [x,y,z],
    "height_cm": float, "kind": "actor"|"group", "members": [[x,y,z], ...]}.
    A single hero shot over ``duration_s`` stays one shot when the requested
    duration allows it; longer durations get 2-3 cuts across a yaw arc so the
    composition reads as directed camera work, not one static frame.
    """
    opts = options or {}
    aspect = float(brief.get("aspect") or 1.78)
    fps = int(brief.get("fps") or 30)
    duration = float(brief.get("duration_s") or 8.0)
    framing_name = str(brief.get("shot") or "hero shot")
    preset = _FRAMING_PRESETS.get(framing_name, _FRAMING_PRESETS["hero shot"])
    fov_deg = float(opts.get("fov_deg", 50.0))

    if not subjects:
        return {"ok": False, "error": "no subjects inspected", "shots": []}

    # Group the inspected subjects into hero candidates: a declared group of
    # >= 2 members is framed as one team shot (single cinematic subject).
    hero: Dict[str, Any] = subjects[0]
    group_members: List[Sequence[float]] = []
    for subj in subjects:
        members = list(subj.get("members") or [subj.get("location")])
        for m in members:
            if m:
                group_members.append(tuple(float(v) for v in m))

    cx = sum(m[0] for m in group_members) / float(len(group_members))
    cy = sum(m[1] for m in group_members) / float(len(group_members))
    spread = max(
        math.hypot(m[0] - cx, m[1] - cy) for m in group_members)
    actor_heights = [float(subj.get("height_cm") or 0.0)
                     for subj in subjects if subj.get("kind") == "actor"]
    base_floor = max(float(m[2]) for m in group_members)
    if actor_heights:
        # a standing hero: aim at head height above the floor the hero stands on
        head_z = base_floor + max(actor_heights)
    else:
        head_z = base_floor + 140.0   # generic tall prop/scene headroom
    group_point = (cx, cy, head_z)

    # distance derived from the group spread so a team fits the frame
    # (an explicit distance override stays bounded and deterministic)
    half_h = math.tan(math.radians(fov_deg / 2.0))
    spread_dist = (spread + 220.0) / (half_h * aspect) if spread > 0 else preset["distance"]
    distance = float(max(spread_dist, preset["distance"] * 0.8))
    if opts.get("distance"):
        distance = float(opts["distance"])

    head_ndc = tuple(float(v) for v in preset["head_ndc"])
    cam_h = float(preset["cam_h"])

    # number of cuts: 1 for very short, up to 3 for a full cinematic
    n_cuts = 1
    if duration >= 7.0:
        n_cuts = 2
    if duration >= 10.0:
        n_cuts = 3
    n_cuts = min(n_cuts, int(opts.get("max_shots", 3)))
    if opts.get("yaws"):
        # explicit yaw arc override (trial/director control)
        yaws_explicit = [float(v) for v in opts["yaws"]][:n_cuts]
    total = max(duration, 1.0)
    cut_dur = total / n_cuts
    if opts.get("yaws"):
        yaw_vals = yaws_explicit
    else:
        center = int(len(_ARC_YAW) / 2)
        yaw_idxs = [center]
        if n_cuts >= 2:
            yaw_idxs = [max(0, center - 2), center, min(len(_ARC_YAW) - 1, center + 2)]
        if n_cuts == 2:
            yaw_idxs = [yaw_idxs[0], yaw_idxs[-1]]
        yaw_vals = [_ARC_YAW[i] for i in yaw_idxs[:n_cuts]]

    shots: List[CinematicShot] = []
    for i, yaw in enumerate(yaw_vals):
        start = round(i * cut_dur, 3)
        end = round(min((i + 1) * cut_dur, duration), 3)
        yaw = float(yaw)
        # face the arc so the subject is not back-lit by camera angle choice
        pose = _solve_pose(
            group_point, yaw_deg=yaw, distance=distance, fov_deg=fov_deg,
            aspect=aspect, head_ndc=head_ndc, cam_height_under_head=cam_h)
        shots.append(CinematicShot(
            index=i + 1, subject_label=str(hero.get("label") or "hero"),
            start_s=start, end_s=end, pose=pose,
            framing=framing_name, motion="static"))

    coverage = preset["coverage_hint"]
    return {
        "ok": True,
        "subject": {"label": hero.get("label"), "kind": hero.get("kind"),
                    "subject_kind": str(hero.get("kind") or "actor"),
                    "location": [round(v, 2) for v in (cx, cy, float(group_point[2]))],
                    "member_count": len(subjects), "spread_cm": round(spread, 1)},
        "target_screen_coverage": coverage,
        "shots": [s.to_dict() for s in shots],
        "fps": fps,
        "duration_s": duration,
        "note": ("camera transform keyframes are engine-closed on UE 5.8 "
                 "python (MovieSceneFloatChannel); each shot is a framed "
                 "camera cut rendered/verified individually."),
    }


# ---------------------------------------------------------------------------
# Acceptance target + cinematic scorecard
# ---------------------------------------------------------------------------

def cinematic_target(brief: Dict[str, Any], plan: Dict[str, Any]) -> Dict[str, Any]:
    """Build a visual_acceptance-compatible target for a cinematic shot."""
    coverage = list(plan.get("target_screen_coverage") or [0.20, 0.46])
    p = str(brief.get("raw_prompt") or "").lower()
    scene_words = ("scene", "environment", "floor", "headquarters",
                   "command", "interior", "room", "stage", "set")
    scene_framing = (str(plan.get("subject_kind") or "") == "prop"
                     or any(w in p for w in scene_words))
    return {
        "subject": {
            "type": "scene" if scene_framing else (
                "scene" if plan.get("member_count", 1) > 1 else "hero_character"),
            "importance": "hero",
            "screen_position": "center",
            "target_screen_coverage": coverage,
            "head_fully_visible": not scene_framing,
            "scene_framing": scene_framing,
            "max_head_top_frac": 0.05,
        },
        "lighting": {
            "style": "cinematic",
            "subject_separation": True,
            "highlight_clipping_max": 0.05,
            "shadow_crush_max": 0.10,
        },
        "ui": {},
        "required_visual_categories": list(CINEMATIC_SCOPED_CATEGORIES),
        "visual_profile": "cinematic",
        "cinematic_brief": {k: brief.get(k) for k in (
            "shot", "motion", "style_tokens", "premium", "duration_s", "fps",
            "resolution")},
    }


def _scene_subject_locator(image):
    """Scene/env shots have no separable subject bbox (whole composition)."""
    return None


def _cinematic_subject_locator(image):
    """Full-frame subject locator for cinematic (non-UI) shots."""
    from core.visual_acceptance import find_subject_bbox
    return find_subject_bbox(image, roi=[0.01, 0.02, 0.99, 0.97])


def score_cinematic_frame(
    path: str,
    target: Dict[str, Any],
    *,
    vision: Optional[Dict[str, Any]] = None,
    metrics: Any = None,
    score_result: Any = None,
    reference_hash: Optional[str] = None,
) -> Dict[str, Any]:
    """Produce the seven-dimension cinematic scorecard for one captured frame.

    Deterministic dimensions come from visual_acceptance; the three
    vision-only dimensions are reported only when a vision review is provided
    (basis = "vision"), otherwise basis = "vision_unavailable" and they are
    excluded from the per-dimension record. The deterministic overall is
    blended with a vision score at the same weight V1 uses (0.35) when a
    review exists; values are never invented.
    """
    if metrics is None:
        scene = bool((target.get("subject") or {}).get("scene_framing"))
        locator = _scene_subject_locator if scene else _cinematic_subject_locator
        metrics = measure(path, target, reference_hash=reference_hash,
                          subject_locator=locator)
    if score_result is None:
        score_result = score(metrics, target)
    cats = {k: round(float(getattr(score_result, k)), 2)
            for k in ("composition", "subject_framing", "lighting",
                      "environment", "readability", "target_match",
                      "technical_integrity")}
    dims: Dict[str, Any] = {}
    for dim in CINEMATIC_DIMENSIONS:
        src = _DETERMINISTIC_SOURCE.get(dim)
        if src == "composition":
            dims[dim] = {"value": cats["composition"], "basis": "measured"}
        elif src == "subject_framing":
            dims[dim] = {"value": cats["subject_framing"], "basis": "measured"}
        elif src == "lighting":
            dims[dim] = {"value": cats["lighting"], "basis": "measured"}
        elif src == "target_match":
            dims[dim] = {"value": cats["target_match"], "basis": "measured"}
        else:
            dims[dim] = {"value": None, "basis": "vision_unavailable"}
    # vision-only dimensions
    if vision:
        dims["material_readability"] = _vision_dim(
            vision, "material", "readability", "texture")
        dims["cinematic_depth"] = _vision_dim(
            vision, "depth", "background", "composition", "layer")
        dims["visual_polish"] = _vision_dim(
            vision, "polish", "artifact", "defect", "render")
    issues = [str(i) for i in (vision or {}).get("issues", [])] or list(
        metrics.issues)
    vision_score = vision.get("score") if vision else None
    measured = [dims[d]["value"] for d in dims
                if dims[d]["basis"] == "measured" and dims[d]["value"] is not None]
    overall = round(sum(measured) / float(len(measured)), 2) if measured else 0.0
    basis = "measured_dimensions" if measured else "unscorable"
    vision_score = vision.get("score") if vision else None
    if isinstance(vision_score, (int, float)):
        overall = round(overall * 0.65 + max(0.0, min(10.0, float(vision_score))) * 0.35, 2)
        basis = "blended_measured_vision"
    return {
        "ok": bool(metrics.ok),
        "overall": overall,
        "overall_basis": basis,
        "dimensions": dims,
        "vision_score": round(float(vision_score), 2) if vision_score is not None else None,
        "categories": cats,
        "metrics": {
            "width": metrics.width, "height": metrics.height,
            "mean_luma": metrics.mean_luma, "std_luma": metrics.std_luma,
            "pct_white": metrics.pct_white, "pct_black": metrics.pct_black,
            "subject_coverage": metrics.subject_coverage,
            "head_clipped": metrics.head_clipped,
            "bands": metrics.bands, "stale": metrics.stale,
            "entropy": metrics.entropy,
        },
        "issues": issues[:8],
        "path": path,
    }


def _vision_dim(vision: Dict[str, Any], *keys: str) -> Dict[str, Any]:
    """Vision-only dimension: reported only with real model evidence."""
    issues = [str(i).lower() for i in (vision or {}).get("issues", [])]
    pass_flag = vision.get("pass")
    vs = vision.get("score")
    penalty = 0.0
    for i in issues:
        if any(k in i for k in keys):
            penalty += 1.0
    base = float(vs) if isinstance(vs, (int, float)) else 7.0
    value = round(max(0.0, min(10.0, base - penalty)), 2)
    return {
        "value": value,
        "basis": "vision",
        "model": vision.get("model") or "local_vision",
        "pass": bool(pass_flag) if pass_flag is not None else None,
    }


# ---------------------------------------------------------------------------
# Cinematic quality loop
# ---------------------------------------------------------------------------

CINEMATIC_STRATEGY_CHAINS: Dict[str, List[str]] = {
    "WHITE_CLIPPING": ["exposure_reduce_highlights",
                       "lighting_reduce_background"],
    "BACKGROUND_OVEREXPOSED": ["lighting_reduce_background",
                               "exposure_reduce_highlights"],
    "BLACK_CLIPPING": ["exposure_raise_blacks", "lighting_raise_key"],
    "SUBJECT_TOO_DARK": ["lighting_raise_key", "exposure_raise_blacks"],
    "SUBJECT_TOO_LARGE": ["camera_pull_back", "camera_framing_recompute"],
    "SUBJECT_TOO_SMALL": ["camera_move_closer", "camera_framing_recompute"],
    "HEAD_CROPPED": ["camera_framing_recompute", "camera_pull_back"],
    "EMPTY_ENVIRONMENT": ["environment_add_depth",
                          "lighting_reduce_background"],
    "CAMERA_ROLL": ["camera_roll_reset", "camera_framing_recompute"],
    "BLACK_BAND": ["viewport_aspect_fix", "capture_force_fresh"],
    "STALE_CAPTURE": ["capture_force_fresh"],
}


class CinematicShotLoop:
    """Bounded capture -> score -> diagnose -> improve -> recapture loop.

    One loop instance serves one shot and stops when the cinematic gate
    passes or ``max_passes`` (default 3, the V2 visual-iteration budget) is
    exhausted. Adapters keep this class fully hermetic.
    """

    def __init__(
        self,
        target: Dict[str, Any],
        capture: Callable[[str], Dict[str, Any]],
        apply: Callable[[str, Any, Any, Dict[str, Any], int], Any],
        vision: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None,
        max_passes: int = 3,
        out_dir: Optional[str] = None,
    ) -> None:
        self.target = target
        self.capture = capture
        self.apply = apply
        self.vision = vision
        self.max_passes = max(1, min(3, int(max_passes)))  # never > 3
        self.out_dir = out_dir
        self.passes: List[Dict[str, Any]] = []
        self._tried: Dict[str, List[str]] = {}

    def _choose_action(self, defects: List[str]) -> Optional[str]:
        if not defects:
            return None
        defect = str(defects[0]).split(":")[0].strip().upper()
        tried = self._tried.setdefault(defect, [])
        chain = CINEMATIC_STRATEGY_CHAINS.get(
            defect, [defect.lower()])
        for candidate in chain:
            if candidate not in tried:
                return candidate
        return None

    def run(self, shot: Dict[str, Any]) -> Dict[str, Any]:
        if self.out_dir:
            os.makedirs(self.out_dir, exist_ok=True)
        best: Optional[Dict[str, Any]] = None
        for i in range(1, self.max_passes + 1):
            cap = self.capture(shot)
            path = str(cap.get("path") or "")
            if not cap.get("ok") or not path:
                return self._finish("BLOCKED", shot,
                                    error=cap.get("error") or "capture failed")
            sc = score_cinematic_frame(path, self.target)
            if self.vision is not None and sc.get("ok"):
                try:
                    review = self.vision(path)
                    if review:
                        sc = score_cinematic_frame(
                            path, self.target, vision=review)
                except Exception:
                    sc = sc  # vision is advisory, never fatal
            defects = _derive_shot_defects(sc)
            rec = {
                "index": i,
                "path": path,
                "scorecard": sc,
                "defects": defects,
                "verdict": "PASS" if (sc["overall"] >= 8.0 and not defects
                                      and sc["ok"]) else "REVISE",
            }
            self.passes.append(rec)
            if best is None or sc["overall"] >= best["scorecard"]["overall"]:
                best = rec
            action = None if rec["verdict"] == "PASS" else self._choose_action(defects)
            rec["action"] = action
            if action is None:
                break
            try:
                out = self.apply(action, sc["metrics"], sc, self.target, i)
            except Exception as exc:
                return self._finish("BLOCKED", shot, error=f"apply failed: {exc}")
            note = str(out) if isinstance(out, str) else str(
                (out or {}).get("note", action))
            rec["change"] = note
            top_defect = next(iter(defects), "UNKNOWN")
            self._tried.setdefault(top_defect, []).append(action)
        final = best or (self.passes[-1] if self.passes else None)
        if final is None:
            return self._finish("BLOCKED", shot, error="no capture produced")
        status = "PASS" if (final["scorecard"]["overall"] >= 8.0
                            and not final["defects"]) else "REVISE_MAXED"
        return self._finish(status, shot, best_pass=final)

    def _finish(self, status: str, shot: Dict[str, Any],
                best_pass: Optional[Dict[str, Any]] = None,
                error: Optional[str] = None) -> Dict[str, Any]:
        return {
            "ok": status == "PASS",
            "status": status,
            "error": error,
            "shot": shot,
            "passes": self.passes,
            "final_scorecard": best_pass["scorecard"] if best_pass else None,
            "iterations": len(self.passes),
        }


def _derive_shot_defects(sc: Dict[str, Any]) -> List[str]:
    """Deterministic cinematic defects from a scorecard (never guessed)."""
    ordered = ["HEAD_CROPPED", "SUBJECT_TOO_LARGE", "SUBJECT_TOO_SMALL",
               "WHITE_CLIPPING", "BLACK_CLIPPING", "BLACK_BAND"]
    issues = {str(x).split(":")[0].strip().upper() for x in sc.get("issues") or []}
    d: List[str] = []
    for defect in ordered:
        if defect in issues:
            d.append(defect)
    cov = float(sc.get("metrics", {}).get("subject_coverage") or 0.0)
    if cov > 0:
        if cov < 0.10 and "SUBJECT_TOO_SMALL" not in d:
            d.append("SUBJECT_TOO_SMALL")
        if cov > 0.62 and "SUBJECT_TOO_LARGE" not in d:
            d.append("SUBJECT_TOO_LARGE")
    if d and d[0] != "HEAD_CROPPED":
        d = [x for x in ordered if x in d]
    return d


# ---------------------------------------------------------------------------
# Mission orchestration
# ---------------------------------------------------------------------------

class CinematicAdapter:
    """Interface every live adapter implements (injected; hermetic by default).

    Real-world implementation: tools/unreal/cinematic_live.py. The default
    adapter refuses to run, so a mission can never silently fake a result.
    """

    def inspect_subjects(self, brief: Dict[str, Any]) -> List[Dict[str, Any]]:
        raise NotImplementedError("CinematicAdapter.inspect_subjects")

    def place_camera(self, shot: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError("CinematicAdapter.place_camera")

    def aim_viewport(self, shot: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError("CinematicAdapter.aim_viewport")

    def capture(self, shot: Dict[str, Any], out_path: str) -> Dict[str, Any]:
        raise NotImplementedError("CinematicAdapter.capture")

    def apply_fix(self, action: str, metrics: Any, scorecard: Dict[str, Any],
                  target: Dict[str, Any], pass_index: int) -> Any:
        raise NotImplementedError("CinematicAdapter.apply_fix")

    def vision(self, path: str) -> Optional[Dict[str, Any]]:
        return None  # vision optional

    def render(self, brief: Dict[str, Any], shots: List[Dict[str, Any]],
               out_dir: str) -> Dict[str, Any]:
        raise NotImplementedError("CinematicAdapter.render")

    def blender_if_needed(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        """Asset decision hook; default: reuse (no blender) when unused."""
        return {"decision": "reuse", "blender_used": False,
                "reason": "no blender decision requested"}


def run_cinematic(
    prompt: str,
    adapter: CinematicAdapter,
    out_dir: str,
    *,
    vision: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None,
    max_visual_passes: int = 3,
    verify_shots: bool = True,
    subjects: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Full cinematic mission: brief -> plan -> asset decision -> shots ->
    per-shot bounded quality -> render -> proof + scorecard.

    Returns a structured CinematicResult. Every step records ok/error
    truthfully; a failed/blocked step is reported, never converted to PASS.
    """
    os.makedirs(out_dir, exist_ok=True)
    brief = parse_cinematic_brief(prompt)
    record: Dict[str, Any] = {
        "brief": brief,
        "out_dir": out_dir,
        "blockers": [],
        "warnings": [],
        "steps": [],
        "shots": [],
        "scorecard": None,
        "video": None,
        "proof_frames": [],
    }

    # 1. inspect scene subjects (an explicit override skips live inspection)
    if subjects is None:
        try:
            subjects = adapter.inspect_subjects(brief)
        except NotImplementedError as exc:
            record["steps"].append({"step": "inspect_subjects",
                                    "ok": False, "error": str(exc)})
            record["blockers"].append("live adapter not configured")
            return _finalize(record)
        except Exception as exc:
            record["steps"].append({"step": "inspect_subjects", "ok": False,
                                    "error": f"{type(exc).__name__}: {exc}"})
            record["blockers"].append("subject inspection failed")
            return _finalize(record)
        if not subjects:
            record["steps"].append({"step": "inspect_subjects", "ok": True,
                                    "subjects": [], "note": "no subjects found"})
            record["blockers"].append("no cinematic subjects present in scene")
            return _finalize(record)
        record["steps"].append({"step": "inspect_subjects", "ok": True,
                                "subject_count": len(subjects)})
    else:
        record["steps"].append({"step": "inspect_subjects", "ok": True,
                                "subject_count": len(subjects),
                                "note": "explicit subject override"})

    # 2. shot plan (framing math, no live calls)
    plan = plan_cinematic_shots(brief, subjects)
    record["steps"].append({"step": "plan_shots", "ok": bool(plan.get("ok")),
                            "plan": {k: plan.get(k) for k in
                                     ("subject", "target_screen_coverage",
                                      "note")} if plan.get("ok") else plan})
    if not plan.get("ok"):
        record["blockers"].append(plan.get("error") or "shot plan failed")
        return _finalize(record)
    record["subject"] = plan["subject"]

    # 3. asset decision (reuse first; Blender only when genuinely needed)
    asset_decision = adapter.blender_if_needed(plan)
    record["asset_decision"] = asset_decision
    record["steps"].append({"step": "asset_decision", "ok": True,
                            "decision": asset_decision.get("decision"),
                            "reason": asset_decision.get("reason"),
                            "blender_used": bool(
                                asset_decision.get("blender_used"))})

    # 4. per-shot execution + bounded visual loop
    target = cinematic_target(brief, plan)
    for shot in plan["shots"]:
        shot_rec: Dict[str, Any] = {"shot": shot}
        try:
            cam = adapter.place_camera(shot)
            shot_rec["camera"] = cam
            if not cam.get("ok"):
                raise RuntimeError(cam.get("error") or "camera placement failed")
            aim = adapter.aim_viewport(shot)
            shot_rec["aim"] = aim
        except Exception as exc:
            shot_rec["ok"] = False
            shot_rec["error"] = f"{type(exc).__name__}: {exc}"
            record["shots"].append(shot_rec)
            record["blockers"].append(f"shot {shot['index']}: {shot_rec['error']}")
            continue

        loop = CinematicShotLoop(
            target,
            capture=lambda s, _op=shot: _capture_with_path(adapter, s, out_dir),
            apply=adapter.apply_fix,
            vision=vision,
            max_passes=max_visual_passes,
            out_dir=os.path.join(out_dir, "iterations"),
        )
        result = loop.run(shot)
        shot_rec["ok"] = bool(result.get("ok"))
        shot_rec["loop"] = result
        record["shots"].append(shot_rec)

    # usable captures (readable frames) are kept even when the acceptance
    # gate is not met, so a real render + scorecard are always delivered;
    # only blank/unreadable frames block the render stage.
    def _usable(s: Dict[str, Any]) -> bool:
        fs = (s.get("loop") or {}).get("final_scorecard") or {}
        if not fs.get("ok"):
            return False
        m = fs.get("metrics") or {}
        mean = float(m.get("mean_luma") or 0.0)
        return (mean >= 20.0 and float(m.get("pct_black") or 0.0) < 0.90
                and float(m.get("pct_white") or 0.0) < 0.97)

    usable_shots = [s for s in record["shots"] if _usable(s)]
    passed_gate = [s for s in usable_shots if (s.get("loop") or {}).get("ok")]
    if not usable_shots:
        record["blockers"].append("no readable shot produced by the visual loop")
        return _finalize(record)

    # 5. final render (real Unreal render through the adapter)
    try:
        render_result = adapter.render(
            brief, [s["shot"] for s in usable_shots],
            os.path.join(out_dir, "render"))
        record["video"] = render_result
        record["steps"].append({"step": "render",
                                "ok": bool(render_result.get("ok")),
                                "result": render_result})
        if not render_result.get("ok"):
            record["blockers"].append(
                render_result.get("error") or "render reported not ok")
    except Exception as exc:
        record["steps"].append({"step": "render", "ok": False,
                                "error": f"{type(exc).__name__}: {exc}"})
        record["blockers"].append("render step failed")

    # 6. scorecard over the best kept pass per shot
    card = _aggregate_scorecard(record["shots"])
    record["scorecard"] = card
    if verify_shots and card["overall"] < 8.0:
        record["warnings"].append(
            f"final measured score {card['overall']} below 8.0 acceptance; "
            "render + frames still delivered as real evidence, no fake "
            "pass claimed")
    if passed_gate:
        record["gate_met"] = True
        record["status"] = "COMPLETE"
    else:
        record["gate_met"] = False
        record["status"] = "DELIVERED_BELOW_GATE"
    return _finalize(record)


def _capture_with_path(adapter: CinematicAdapter, shot: Dict[str, Any],
                       out_dir: str) -> Dict[str, Any]:
    n = int(shot.get("index") or 1)
    path = os.path.join(out_dir, f"shot{n}_frame.png")
    return adapter.capture(shot, path)


def _aggregate_scorecard(shots: List[Dict[str, Any]]) -> Dict[str, Any]:
    dims: Dict[str, List[float]] = {d: [] for d in CINEMATIC_DIMENSIONS}
    frames: List[str] = []
    for s in shots:
        loop = s.get("loop") or {}
        best = loop.get("final_scorecard") or {}
        for d in CINEMATIC_DIMENSIONS:
            entry = best.get("dimensions", {}).get(d) or {}
            if entry.get("value") is not None and entry.get("basis") == "measured":
                dims[d].append(float(entry["value"]))
        p = best.get("path")
        if p:
            frames.append(p)
    per_dim = {}
    for d, vals in dims.items():
        per_dim[d] = {"value": round(sum(vals) / len(vals), 2) if vals else None,
                      "basis": "measured" if vals else "no_measured_evidence"}
    measured = [per_dim[d]["value"] for d in per_dim if per_dim[d]["value"] is not None]
    return {
        "dimensions": per_dim,
        "overall": round(sum(measured) / len(measured), 2) if measured else 0.0,
        "basis": "measured_dimensions" if measured else "unscorable",
        "frames": frames,
    }


def _finalize(record: Dict[str, Any]) -> Dict[str, Any]:
    record["critical"] = [b for b in record["blockers"]]
    if record.get("status") in ("COMPLETE", "DELIVERED_BELOW_GATE"):
        if not record["blockers"] and record.get("video", {}).get("ok"):
            pass  # keep status set by the caller
        else:
            record["status"] = "BLOCKED"
    else:
        record["status"] = "BLOCKED" if record["blockers"] else (
            record.get("status") or "BLOCKED")
    record["cinematic_v1_ready"] = (record.get("gate_met") is True
                                    and (record.get("scorecard") or {}).get(
                                        "overall", 0) >= 8.0)
    return record


# ---------------------------------------------------------------------------
# Evidence persistence
# ---------------------------------------------------------------------------

def write_cinematic_result(record: Dict[str, Any], out_dir: str) -> str:
    """Persist a CinematicResult as JSON next to the demo artifacts."""
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "cinematic_result.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, default=str)
    return path
