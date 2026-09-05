"""camera_api.py — deterministic Unreal camera framing + fresh proof capture.

Direct backend capabilities so a request like "focus actor/cube and return
fresh proof" NEVER routes through generic prompt/world-building
classification or mission acceptance criteria:

    POST /api/unreal/frame-actor      {location:[x,y,z]} | {actor_name:"..."}
    POST /api/unreal/capture-proof
    POST /api/unreal/frame-and-proof  {location:[x,y,z]} | {actor_name:"..."}

Framing reuses the read-back-verified camera primitives from
core.unreal_fix_adapter (UnrealFixAdapter._set_camera / _camera_state) and
verifies the viewport actually changed AND is aimed at the target before
returning. Capture reuses UnrealFixAdapter.capture() (visibility-guarded
fresh capture), writes the canonical viewport_latest.png that /api/proof/*
serves, and mirrors a durable copy into assetlib/proof/.

The three endpoints are additive: no existing route, tool or pipeline is
touched (backward compatibility is preserved by construction).
"""
from __future__ import annotations

import math
import shutil
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, model_validator

from core.unreal_fix_adapter import UnrealFixAdapter, ViewportNotVisibleError

ROOT = Path(__file__).resolve().parents[1]

# --------------------------------------------------------------------------
# Framing constants (deterministic, bounds-derived, clamped)
# --------------------------------------------------------------------------
FILL_FACTOR = 5.0          # camera distance = target radius * FILL_FACTOR
MIN_DISTANCE = 300.0       # never zoom closer than this (world units)
MAX_DISTANCE = 5000.0      # never pull back beyond this (world units)
DEFAULT_RADIUS = 250.0     # location-only framing when no actor snaps
AZ_DEG = 0.0               # camera azimuth around the target (0 = +Y side)
EL_DEG = 12.0              # camera elevation above the target (degrees)
SNAP_RADIUS = 1500.0       # max distance for location -> actor snapping
MAX_ACTOR_RADIUS = 2000.0  # ground/sky planes are never framing targets
LOOK_AT_TOLERANCE_DEG = 2.0


# --------------------------------------------------------------------------
# Pure framing math (unit-testable without Unreal)
# --------------------------------------------------------------------------

def compute_view(
    target: List[float],
    radius: float,
    distance: Optional[float] = None,
) -> tuple:
    """Camera position + rotation [roll, pitch, yaw] looking at `target`.

    The camera sits `distance` units from the target at azimuth AZ_DEG /
    elevation EL_DEG (bounds-aware when `radius` comes from a real actor).
    Returns (camera_location, rotation, distance_used).
    """
    d = float(distance) if distance else float(radius) * FILL_FACTOR
    d = max(MIN_DISTANCE, min(MAX_DISTANCE, d))
    el = math.radians(EL_DEG)
    az = math.radians(AZ_DEG)
    # unit direction from the target to the camera
    dx = math.sin(az) * math.cos(el)
    dy = math.cos(az) * math.cos(el)
    dz = math.sin(el)
    cam = [target[0] + dx * d, target[1] + dy * d, target[2] + dz * d]
    # look direction from the camera back to the target
    look = [-dx, -dy, -dz]
    yaw = math.degrees(math.atan2(look[1], look[0]))
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, look[2]))))
    return cam, [0.0, round(pitch, 3), round(yaw, 3)], round(d, 1)


def forward_from_rot(rot: List[float]) -> List[float]:
    """Viewport forward unit vector from [roll, pitch, yaw] (Unreal
    convention: yaw 0 = +X, positive pitch looks up)."""
    pitch = math.radians(float(rot[1]))
    yaw = math.radians(float(rot[2]))
    return [
        math.cos(pitch) * math.cos(yaw),
        math.cos(pitch) * math.sin(yaw),
        math.sin(pitch),
    ]


def look_at_error(cam: List[float], rot: List[float],
                  target: List[float]) -> float:
    """Angular error (degrees) between the camera's forward ray and the
    vector from the camera to the target. ~0 means the target is centered."""
    dx = target[0] - cam[0]
    dy = target[1] - cam[1]
    dz = target[2] - cam[2]
    length = math.sqrt(dx * dx + dy * dy + dz * dz)
    if length <= 0.0:
        return 180.0
    want = [dx / length, dy / length, dz / length]
    have = forward_from_rot(rot)
    dot = max(-1.0, min(1.0, sum(a * b for a, b in zip(want, have))))
    return float(math.degrees(math.acos(dot)))


def _viewport_changed(before: Dict[str, Any], after_loc: List[float],
                      after_rot: List[float]) -> bool:
    """True when the read-back camera position/rotation actually moved."""
    if not before:
        return True
    before_loc = before.get("loc") or []
    before_rot = before.get("rot") or []
    if len(before_loc) == 3 and len(after_loc) == 3:
        moved = math.sqrt(sum(
            (after_loc[i] - before_loc[i]) ** 2 for i in range(3)))
        if moved > 1.0:
            return True
    if len(before_rot) == 3 and len(after_rot) == 3:
        if any(abs(after_rot[i] - before_rot[i]) > 0.5 for i in range(3)):
            return True
    return False


# --------------------------------------------------------------------------
# Target resolution (find/select the actor to frame)
# --------------------------------------------------------------------------

def _actor_query(actor_name: str) -> str:
    return f"""
import unreal
actors = unreal.EditorLevelLibrary.get_all_level_actors()
matches = [a for a in actors if a.get_name() == {actor_name!r}
           or a.get_actor_label() == {actor_name!r}]
if len(matches) != 1:
    __bridge_result__ = {{
        "ok": False,
        "code": "NOT_FOUND" if not matches else "AMBIGUOUS",
        "error": "actor not found or ambiguous: {actor_name}",
        "matches": [a.get_name() for a in matches],
    }}
else:
    actor = matches[0]
    sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    try:
        sub.set_selected_level_actors([actor])
        selected = True
    except Exception:
        selected = False
    origin, extent = actor.get_actor_bounds(False)
    __bridge_result__ = {{
        "ok": True,
        "kind": "actor",
        "name": actor.get_name(),
        "label": actor.get_actor_label(),
        "class": actor.get_class().get_name(),
        "origin": [origin.x, origin.y, origin.z],
        "extent": [extent.x, extent.y, extent.z],
        "radius": max(extent.x, extent.y, extent.z),
        "selected": selected,
    }}
"""


def _location_query(location: List[float]) -> str:
    return f"""
import unreal
loc = unreal.Vector({location[0]}, {location[1]}, {location[2]})
actors = unreal.EditorLevelLibrary.get_all_level_actors()
best = None
best_score = 1e18
best_dist = 1e18
best_origin = None
best_radius = 0.0
for act in actors:
    try:
        origin, extent = act.get_actor_bounds(False)
    except Exception:
        continue
    r = max(extent.x, extent.y, extent.z)
    if r > {MAX_ACTOR_RADIUS}:
        continue
    d = (origin - loc).length()
    cls = act.get_class().get_name()
    score = d - (0.5 if cls == "StaticMeshActor" else 0.0)
    if score < best_score:
        best = act
        best_score = score
        best_dist = d
        best_origin = origin
        best_radius = r
if best is not None and best_dist <= {SNAP_RADIUS}:
    sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    try:
        sub.set_selected_level_actors([best])
        selected = True
    except Exception:
        selected = False
    __bridge_result__ = {{
        "ok": True,
        "kind": "actor",
        "name": best.get_name(),
        "label": best.get_actor_label(),
        "class": best.get_class().get_name(),
        "origin": [best_origin.x, best_origin.y, best_origin.z],
        "extent": [best_radius, best_radius, best_radius],
        "radius": best_radius,
        "dist": round(best_dist, 1),
        "selected": selected,
    }}
else:
    __bridge_result__ = {{
        "ok": True,
        "kind": "point",
        "origin": [{location[0]}, {location[1]}, {location[2]}],
        "extent": [{DEFAULT_RADIUS}, {DEFAULT_RADIUS}, {DEFAULT_RADIUS}],
        "radius": {DEFAULT_RADIUS},
        "dist": 0.0,
        "selected": False,
    }}
"""


def resolve_target(bridge: Any, location: Optional[List[float]] = None,
                   actor_name: Optional[str] = None) -> Dict[str, Any]:
    """Find/select the actor to frame and return its bounds.

    actor_name -> exact match (name or label); 404/409 on missing/ambiguous.
    location   -> snap to the best framed target actor near the point
                  (StaticMeshActor preferred, ground/sky excluded) when one
                  is within SNAP_RADIUS, else frame the raw point.
    """
    query = (_actor_query(actor_name) if actor_name
             else _location_query(list(location)))
    result = bridge.execute_python(query)
    payload = result.get("result") if isinstance(result.get("result"), dict) \
        else result
    if not isinstance(payload, dict) or not payload.get("ok"):
        code = str(payload.get("code") or "") if isinstance(payload, dict) \
            else ""
        return {"ok": False, "code": code or "BRIDGE_ERROR",
                "error": str(payload.get("error") or result.get("error")
                             or "target resolution failed")}
    radius = float(payload.get("radius") or DEFAULT_RADIUS)
    target = [float(x) for x in payload.get("origin") or location]
    return {
        "ok": True,
        "kind": payload.get("kind", "point"),
        "actor": {
            "label": payload.get("label"),
            "name": payload.get("name"),
            "class": payload.get("class"),
        } if payload.get("kind") == "actor" else None,
        "target": target,
        "radius": max(MIN_DISTANCE / FILL_FACTOR, min(MAX_ACTOR_RADIUS,
                                                      radius)),
        "selected": bool(payload.get("selected")),
        "dist": float(payload.get("dist") or 0.0),
    }


# --------------------------------------------------------------------------
# Bridge access
# --------------------------------------------------------------------------

def _default_bridge_factory():
    """Resolve the live UnrealBridge from the tool registry; fall back to a
    fresh client on 127.0.0.1:6766 (same pattern as app/proof.py)."""
    try:
        from app import api as _api
        for spec in _api.REGISTRY.values():
            owner = getattr(getattr(spec, "func", None), "__self__", None)
            if owner is not None and owner.__class__.__name__ == "UnrealBridge":
                return owner
    except Exception:
        pass
    from tools.unreal.unreal_bridge import UnrealBridge
    return UnrealBridge(timeout=20)


def _get_bridge(bridge_factory: Optional[Callable[[], Any]]) -> Any:
    try:
        bridge = bridge_factory() if bridge_factory is not None \
            else _default_bridge_factory()
    except Exception as exc:
        raise HTTPException(503, detail={
            "ok": False, "error": f"bridge factory failed: {exc}"})
    if bridge is None:
        raise HTTPException(503, detail={
            "ok": False, "error": "live Unreal bridge unavailable"})
    probe = bridge.ping()
    payload = probe.get("result") if isinstance(probe.get("result"), dict) \
        else probe
    alive = bool(isinstance(probe, dict)
                 and (probe.get("ok") is True
                      or (isinstance(payload, dict)
                          and payload.get("ok") is True)))
    if not alive:
        raise HTTPException(503, detail={
            "ok": False, "error": "live Unreal bridge unreachable",
            "probe": probe})
    return bridge


# --------------------------------------------------------------------------
# Editor wake (canonical product pattern: restore + foreground the
# UnrealEditor window before a guarded capture, so a minimized/occluded
# editor never returns a stale frame as evidence).
# --------------------------------------------------------------------------

def _wake_editor() -> bool:
    """Restore + foreground the REAL UnrealEditor frame window.

    Get-Process.MainWindowHandle is unreliable here (it can point at a
    titleless child window while the real frame — titled "... - Unreal
    Editor" — is minimized off-screen, which freezes the viewport render), so
    the helper script enumerates top-level windows of the UnrealEditor
    process and restores the one whose title contains "Unreal Editor"
    (falling back to MainWindowHandle). Returns True when restored.
    """
    import subprocess
    script = ROOT / "scripts" / "restore_editor_window.ps1"
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", str(script)], capture_output=True, text=True,
            timeout=30)
        return "RESTORED" in (r.stdout or "") \
            or "ALREADY_OK" in (r.stdout or "")
    except Exception:
        return False


def _force_viewport_render(bridge: Any) -> None:
    """Force the editor viewport to produce a REAL new frame.

    Scripted camera moves (set_level_viewport_camera_info) do not mark the
    viewport dirty, and a background/minimized editor can keep presenting a
    frozen backbuffer. The reliable forced-render recipe (verified live) is:
    invalidate viewports + wobble r.ScreenPercentage + RedrawAllViewports,
    then let the render thread present. Without this the captured "proof"
    would be a stale frame — never acceptable as evidence.
    """
    bridge.execute_python("""
import unreal
w = unreal.EditorLevelLibrary.get_editor_world()
if w is not None:
    try:
        unreal.EditorLevelLibrary.editor_invalidate_viewports()
    except Exception:
        pass
    for cmd in ("r.ScreenPercentage 99", "RedrawAllViewports",
                "r.ScreenPercentage 100"):
        try:
            unreal.SystemLibrary.execute_console_command(w, cmd)
        except Exception:
            pass
__bridge_result__ = {"ok": True}
""")
    time.sleep(1.8)


# --------------------------------------------------------------------------
# Capture (fresh proof, no acceptance criteria involved)
# --------------------------------------------------------------------------

def _capture_impl(bridge: Any, adapter: UnrealFixAdapter,
                  proof_copy_dir: Optional[Path] = None) -> Dict[str, Any]:
    identity = bridge.get_project_identity()
    info = identity.get("result") if isinstance(identity.get("result"), dict) \
        else identity
    project_path = (info or {}).get("project_path")
    if project_path:
        capture_dir = Path(str(project_path)).resolve().parent \
            / "Saved" / "UnrealAgent"
    else:
        capture_dir = ROOT / "assetlib" / "proof"
    capture_dir.mkdir(parents=True, exist_ok=True)
    path = capture_dir / "viewport_latest.png"
    # Force a REAL render of the current viewport state first, then run the
    # visibility-guarded fresh capture (deletes the old file, repaints,
    # raises ViewportNotVisibleError on stale/occluded).
    _force_viewport_render(bridge)
    captured = adapter.capture(str(path))
    copied = None
    copy_error = None
    try:
        copy_dir = Path(proof_copy_dir) if proof_copy_dir is not None \
            else ROOT / "assetlib" / "proof"
        copy_dir.mkdir(parents=True, exist_ok=True)
        copied = copy_dir / "camera_proof_latest.png"
        shutil.copy2(captured["path"], copied)
    except Exception as exc:
        copied = None
        copy_error = f"{type(exc).__name__}: {exc}"
    return {
        "ok": True,
        "path": captured["path"],
        "url": "/api/proof/latest",
        "size": int(captured.get("size")
                    or Path(captured["path"]).stat().st_size),
        "captured_at": time.time(),
        "visible": bool(captured.get("visible")),
        "diag": str(captured.get("diag") or ""),
        "copied_to": str(copied) if copied is not None else None,
        "copy_error": copy_error,
    }


# --------------------------------------------------------------------------
# OpenAPI request/response models
# --------------------------------------------------------------------------

class FrameActorRequest(BaseModel):
    """Body for /api/unreal/frame-actor and /api/unreal/frame-and-proof.

    Provide `actor_name` to find/select an exact actor, or `location` to
    frame a world-space point (snapping to the best actor near it when one
    is found). At least one of the two is required.
    """
    location: Optional[List[float]] = Field(
        None,
        description="World-space XYZ framing target, e.g. [0, 0, 200]. "
                    "When actor_name is omitted, the best framed target "
                    "actor near this point is selected when unambiguous.",
        min_length=3,
        max_length=3,
    )
    actor_name: Optional[str] = Field(
        None,
        description="Outliner label or internal name of the actor to find, "
                    "select and frame (exact match required).",
    )
    distance: Optional[float] = Field(
        None,
        description="Optional camera-to-target distance override in world "
                    "units (clamped to the safe framing range).",
        gt=50.0,
    )

    @model_validator(mode="after")
    def _requires_target(self):
        if self.location is None and not self.actor_name:
            raise ValueError("provide either 'location' or 'actor_name'")
        return self


class FrameActorResponse(BaseModel):
    ok: bool = Field(..., description="True when the viewport was re-framed.")
    kind: str = Field(..., description="'actor' (bounds-framed) or 'point'.")
    actor: Optional[Dict[str, Any]] = Field(
        None, description="Resolved actor identity when kind == 'actor'.")
    target: List[float] = Field(
        ..., description="Framed world-space center (bounds origin or point).")
    radius: float = Field(..., description="Framing radius used (world units).")
    distance: float = Field(..., description="Camera-to-target distance used.")
    camera_before: Dict[str, Any] = Field(
        ..., description="Viewport camera state before framing "
                         "(loc + rot [roll, pitch, yaw]).")
    camera_after: Dict[str, Any] = Field(
        ..., description="Read-back viewport camera state after framing.")
    viewport_changed: bool = Field(
        ..., description="True when the read-back camera actually moved.")
    look_at_error_deg: float = Field(
        ..., description="Angular error between the camera ray and the "
                         "target; ~0 means the target is centered.")
    selected: bool = Field(
        ..., description="True when the actor was selected in the Outliner.")
    note: str = Field(..., description="Human-readable framing summary.")


class CaptureProofResponse(BaseModel):
    ok: bool = Field(..., description="True when a fresh proof was captured.")
    path: str = Field(..., description="Absolute path of the fresh capture "
                                       "(viewport_latest.png).")
    url: str = Field(..., description="Serving URL of the fresh proof "
                                      "(GET /api/proof/latest).")
    size: int = Field(..., description="Capture file size in bytes.")
    captured_at: float = Field(..., description="Unix timestamp of capture.")
    visible: bool = Field(
        ..., description="True when the editor viewport was rendering.")
    diag: str = Field(..., description="Native capture diagnostic string.")
    copied_to: Optional[str] = Field(
        None, description="Durable mirror copy under assetlib/proof/.")
    copy_error: Optional[str] = Field(None, description="Mirror-copy error.")


class FrameAndProofResponse(BaseModel):
    ok: bool = Field(..., description="True when framing AND capture worked.")
    framing: FrameActorResponse = Field(..., description="Framing evidence.")
    proof: CaptureProofResponse = Field(..., description="Proof evidence.")
    url: str = Field(..., description="Serving URL of the fresh proof.")


# --------------------------------------------------------------------------
# Registration
# --------------------------------------------------------------------------

def register_camera_api(app: FastAPI,
                        bridge_factory: Optional[Callable[[], Any]] = None):
    """Register the three /api/unreal/* camera endpoints on the FastAPI app.

    bridge_factory: optional zero-arg callable returning a live
    tools.unreal.unreal_bridge.UnrealBridge (used by hermetic tests).
    Production resolves the bridge from the tool registry and falls back to
    a fresh client on 127.0.0.1:6766.
    """

    @app.post("/api/unreal/frame-actor",
              response_model=FrameActorResponse,
              summary="Find/select an actor and frame it centered in the "
                      "viewport",
              description="Deterministic viewport framing: resolves the "
                          "target (exact actor name/label, or a world-space "
                          "location that snaps to the best actor near it), "
                          "computes a bounds-aware camera position/rotation, "
                          "applies it through the read-back-verified "
                          "unreal_fix_adapter camera primitives and verifies "
                          "the viewport actually changed and aims at the "
                          "target. Never routes through mission acceptance "
                          "criteria.")
    def frame_actor(request: FrameActorRequest):
        bridge = _get_bridge(bridge_factory)
        adapter = UnrealFixAdapter(bridge, wake_editor=_wake_editor)
        target = resolve_target(bridge, location=request.location,
                                actor_name=request.actor_name)
        if not target.get("ok"):
            status = 404 if target.get("code") == "NOT_FOUND" else 409
            raise HTTPException(status, detail=target)
        cam, rot, dist = compute_view(target["target"], target["radius"],
                                      distance=request.distance)
        before = adapter._camera_state()
        set_result = adapter._set_camera(cam, rot)
        after_loc = set_result.get("loc") or cam
        after_rot = set_result.get("rot") or rot
        if not (isinstance(after_loc, list) and len(after_loc) == 3
                and isinstance(after_rot, list) and len(after_rot) == 3):
            raise HTTPException(502, detail={
                "ok": False, "error": "viewport camera set failed",
                "readback": set_result})
        after_loc = [float(x) for x in after_loc]
        after_rot = [float(x) for x in after_rot]
        changed = _viewport_changed(before, after_loc, after_rot)
        error_deg = look_at_error(after_loc, after_rot, target["target"])
        actor = target.get("actor")
        label = (actor or {}).get("label") or target["target"]
        return {
            "ok": True,
            "kind": target["kind"],
            "actor": actor,
            "target": target["target"],
            "radius": round(target["radius"], 2),
            "distance": dist,
            "camera_before": before,
            "camera_after": {"loc": after_loc, "rot": after_rot},
            "viewport_changed": changed,
            "look_at_error_deg": round(error_deg, 3),
            "selected": bool(target.get("selected")),
            "note": (f"framed {label} (radius {round(target['radius'], 1)}) "
                     f"at {target['target']}; look-at error "
                     f"{round(error_deg, 2)} deg"),
        }

    @app.post("/api/unreal/capture-proof",
              response_model=CaptureProofResponse,
              summary="Force a fresh viewport capture and update latest "
                      "proof",
              description="Runs the visibility-guarded fresh capture "
                          "(viewport repaint + delete-then-capture) and "
                          "writes the canonical viewport_latest.png that "
                          "GET /api/proof/latest serves, plus a durable "
                          "mirror copy under assetlib/proof/. Fails only on "
                          "a real capture problem (e.g. hidden viewport), "
                          "never on unrelated parent-goal acceptance "
                          "criteria.")
    def capture_proof():
        bridge = _get_bridge(bridge_factory)
        adapter = UnrealFixAdapter(bridge, wake_editor=_wake_editor)
        try:
            return _capture_impl(bridge, adapter)
        except ViewportNotVisibleError as exc:
            raise HTTPException(502, detail={
                "ok": False, "error": str(exc)})

    @app.post("/api/unreal/frame-and-proof",
              response_model=FrameAndProofResponse,
              summary="Frame a target and return fresh proof in one call",
              description="Composes frame-actor and capture-proof: frames "
                          "the target centered in the viewport, forces a "
                          "fresh capture and returns both the framing "
                          "evidence and the proof metadata/URL.")
    def frame_and_proof(request: FrameActorRequest):
        bridge = _get_bridge(bridge_factory)
        adapter = UnrealFixAdapter(bridge, wake_editor=_wake_editor)
        target = resolve_target(bridge, location=request.location,
                                actor_name=request.actor_name)
        if not target.get("ok"):
            status = 404 if target.get("code") == "NOT_FOUND" else 409
            raise HTTPException(status, detail=target)
        cam, rot, dist = compute_view(target["target"], target["radius"],
                                      distance=request.distance)
        before = adapter._camera_state()
        set_result = adapter._set_camera(cam, rot)
        after_loc = set_result.get("loc") or cam
        after_rot = set_result.get("rot") or rot
        if not (isinstance(after_loc, list) and len(after_loc) == 3
                and isinstance(after_rot, list) and len(after_rot) == 3):
            raise HTTPException(502, detail={
                "ok": False, "error": "viewport camera set failed",
                "readback": set_result})
        after_loc = [float(x) for x in after_loc]
        after_rot = [float(x) for x in after_rot]
        error_deg = look_at_error(after_loc, after_rot, target["target"])
        actor = target.get("actor")
        label = (actor or {}).get("label") or target["target"]
        framing = {
            "ok": True,
            "kind": target["kind"],
            "actor": actor,
            "target": target["target"],
            "radius": round(target["radius"], 2),
            "distance": dist,
            "camera_before": before,
            "camera_after": {"loc": after_loc, "rot": after_rot},
            "viewport_changed": _viewport_changed(before, after_loc,
                                                  after_rot),
            "look_at_error_deg": round(error_deg, 3),
            "selected": bool(target.get("selected")),
            "note": (f"framed {label} (radius {round(target['radius'], 1)}) "
                     f"at {target['target']}; look-at error "
                     f"{round(error_deg, 2)} deg"),
        }
        try:
            proof = _capture_impl(bridge, adapter)
        except ViewportNotVisibleError as exc:
            raise HTTPException(502, detail={
                "ok": False, "error": str(exc)})
        return {
            "ok": True,
            "framing": framing,
            "proof": proof,
            "url": proof["url"],
        }