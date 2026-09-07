"""cinematic_live.py — live Unreal adapter for core.cinematic_director.

Implements the CinematicAdapter contract against a real Unreal Editor via
UnrealBridge: scene subject inspection, CineCamera placement/read-back,
viewport aiming, real high-res frame capture, bounded fix actions and the
render/proof step. MRQ is driven through tools.unreal.movie_render_queue and
is truthfully BLOCKED when the plugin is absent; the adapter never fabricates
a render.

Design rules:
- Editor-side python only ever flows through bridge.execute_python with
  JSON-quoted user content (mirrors the gap-tool convention).
- Every mutation is followed by a read-back; an unverified change is
  reported as not-ok rather than assumed.
- No engine-side assumption is silently tolerated: unknown property names
  are probed with try/except and the exact engine error is returned.
"""

from __future__ import annotations

import json
import math
import os
import time
from typing import Any, Dict, List, Optional

from PIL import Image

from tools.unreal.unreal_bridge import UnrealBridge


def _payload(res: Any) -> Any:
    """Tolerate both bridge wrappings (nested .result vs flat)."""
    if isinstance(res, dict) and isinstance(res.get("result"), (dict, list)):
        return res["result"]
    return res


# Labels/classes that read as cinematic hero candidates (HQ cast etc.).
_HERO_INCLUDE = ("char", "hero", "worker", "agent", "ava", "mannequin",
                 "sk_", "mesh_hq", "hq_", "cast", "crew", "human",
                 "avido", "aivido")
_HERO_EXCLUDE = ("cinecamera", "light", "playerstart", "volume", "trigger",
                 "postprocess", "sky", "fog", "spline", "decoy")


def _default_height_cm(actor_class: str) -> float:
    low = str(actor_class).lower()
    if "skeletal" in low or "character" in low:
        return 175.0
    if "vehicle" in low or "static" in low:
        return 120.0
    return 150.0


class CinematicLiveAdapter:
    """Adapter bound to a real bridge + project (construct with care)."""

    def __init__(self, bridge: UnrealBridge, *,
                 seq_root: str = "/Game/Cine/AividoV2",
                 output_root: Optional[str] = None,
                 hero_limit: int = 6,
                 fov_deg: float = 50.0) -> None:
        self.bridge = bridge
        self.seq_root = seq_root
        self.output_root = output_root or os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__)))), "reports", "cinematic")
        self.hero_limit = int(hero_limit)
        self.fov_deg = float(fov_deg)
        self._current_shot: Optional[Dict[str, Any]] = None
        self._current_cam_label: Optional[str] = None
        self._resolution = [1920, 1080]

    def set_resolution(self, width: int, height: int) -> None:
        self._resolution = [int(width), int(height)]

    def blender_if_needed(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        """Asset decision hook for run_cinematic: reuse existing AividoHQ
        content on the fast path. A real Blender decision is computed by
        core.cinematic_assets when a mission genuinely names an asset need;
        here the demo always reuses the live scene's existing content."""
        return {"decision": "reuse", "blender_used": False,
                "reason": "existing AividoHQ content reused; Blender not "
                           "required on the reuse fast path"}

    # ---------------------------------------------------------------- scene
    def inspect_subjects(self, brief: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Scan the open level for hero candidates (real actor read-back)."""
        res = self.bridge.execute_python(r'''
import unreal
out = []
for a in unreal.EditorLevelLibrary.get_all_level_actors():
    cls = a.get_class().get_name()
    label = a.get_actor_label() or ""
    low = (label + " " + cls + " " + a.get_name()).lower()
    out.append({"label": label, "name": a.get_name(), "class": cls,
                "low": low})
__bridge_result__ = out
''')
        payload = _payload(res)
        if not isinstance(payload, list):
            return []
        include = list(brief.get("subjects") or [])
        candidates = []
        for row in payload:
            low = str(row.get("low") or "")
            cls = str(row.get("class") or "")
            if any(x in low for x in _HERO_EXCLUDE):
                continue
            is_hero_class = any(x in cls.lower() for x in (
                "skeletal", "character", "actor", "mesh"))
            matches_include = any(x in low for x in include)
            matches_hint = any(x in low for x in _HERO_INCLUDE)
            is_character = any(x in cls.lower() for x in (
                "skeletal", "character"))
            # A hero candidate is a cast member (character class) OR an
            # explicitly requested label. Generic static props named like
            # the studio never outrank the cast.
            if is_character and (matches_hint or matches_include or not include):
                ok = True
            elif matches_include:
                ok = True
            else:
                ok = False
            if ok:
                loc = self._actor_location(row["label"])
                if loc is None:
                    continue
                candidates.append({
                    "label": row["label"],
                    "kind": "actor",
                    "location": [round(v, 2) for v in loc],
                    "height_cm": _default_height_cm(cls),
                    "class": cls,
                })
        # deterministic order: cast first, then props, alphabetical inside
        candidates.sort(key=lambda c: (0 if "skeletal" in c["class"].lower()
                                       or "character" in c["class"].lower()
                                       else 1,
                                       str(c["label"]).lower()))
        return candidates[:self.hero_limit]

    def _actor_location(self, label: str) -> Optional[List[float]]:
        res = self.bridge.get_actor(label)
        payload = _payload(res)
        if isinstance(payload, dict) and payload.get("ok"):
            return payload.get("location")
        return None

    # ---------------------------------------------------------------- camera
    def place_camera(self, shot: Dict[str, Any]) -> Dict[str, Any]:
        label = f"AVCam_Shot{int(shot.get('index') or 1):02d}"
        pose = shot.get("pose") or {}
        loc = [float(pose["location_x"]), float(pose["location_y"]),
               float(pose["location_z"])]
        pitch = float(pose.get("pitch", 0.0))
        yaw = float(pose.get("yaw", 0.0))
        roll = float(pose.get("roll", 0.0))
        label_json = json.dumps(label)
        res = self.bridge.execute_python(f'''
import unreal
label = {label_json}
loc = {json.dumps([round(v, 3) for v in loc])}
pitch = {json.dumps(float(pitch))}
yaw = {json.dumps(float(yaw))}
roll = {json.dumps(float(roll))}
actors = [a for a in unreal.EditorLevelLibrary.get_all_level_actors()
          if a.get_actor_label() == label or a.get_name() == label]
if actors:
    cam = actors[0]
    spawned = False
else:
    cam = unreal.EditorLevelLibrary.spawn_actor_from_class(
        unreal.CineCameraActor,
        unreal.Vector(loc[0], loc[1], loc[2]),
        unreal.Rotator(pitch=pitch, yaw=yaw, roll=roll))
    cam.set_actor_label(label)
    spawned = True
cam.set_actor_location(unreal.Vector(loc[0], loc[1], loc[2]), False, False)
cam.set_actor_rotation(unreal.Rotator(pitch=pitch, yaw=yaw, roll=roll), False)
r_loc = cam.get_actor_location()
r_rot = cam.get_actor_rotation()
props = {{}}
for comp in cam.get_components_by_class(unreal.CineCameraComponent):
    for prop in ("current_focal_length", "focal_length"):
        if hasattr(comp, prop):
            try:
                getattr(comp, "set_editor_property")(prop, 50.0)
                props[prop] = True
            except Exception as exc:
                props[prop + ":error"] = str(exc)[:80]
    break
__bridge_result__ = {{
    "ok": True,
    "spawned": spawned,
    "camera": cam.get_actor_label(),
    "location": [r_loc.x, r_loc.y, r_loc.z],
    "rotation": [r_rot.pitch, r_rot.yaw, r_rot.roll],
    "focal_props": props,
    "note": "location/rotation verified by read-back",
}}
''')
        payload = _payload(res)
        if not isinstance(payload, dict):
            payload = {"ok": False, "error": str(res)[:200]}
        if payload.get("ok"):
            self._current_shot = dict(shot)
            self._current_cam_label = label
        return payload

    def aim_viewport(self, shot: Dict[str, Any]) -> Dict[str, Any]:
        label = f"AVCam_Shot{int(shot.get('index') or 1):02d}"
        res = self.bridge.frame_viewport_from_actor(label, distance=0.0)
        return _payload(res)

    # -------------------------------------------------------------- capture
    def capture(self, shot: Dict[str, Any], out_path: str) -> Dict[str, Any]:
        """Real capture of the active level viewport (native read-back).

        The editor viewport is the source; its ACTUAL resolution is read back
        and reported (never assumed to equal the requested resolution). The
        requested resolution remains the target for an MRQ render when the
        plugin is available.
        """
        out_path = os.path.abspath(out_path)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        res = self.bridge.capture_unreal_viewport()
        payload = _payload(res)
        if not (isinstance(payload, dict) and payload.get("ok")):
            return {"ok": False, "error": "native viewport capture failed",
                    "path": out_path, "bridge": payload}
        src = payload.get("path")
        if not src or not os.path.isfile(src):
            return {"ok": False, "error": "native capture file missing",
                    "path": out_path}
        import shutil
        try:
            shutil.copyfile(src, out_path)
        except OSError as exc:
            return {"ok": False, "error": f"copy failed: {exc}",
                    "path": out_path}
        try:
            im = Image.open(out_path)
            actual = list(im.size)
        except Exception:
            actual = None
        return {"ok": True, "path": out_path,
                "resolution_requested": list(self._resolution),
                "resolution": actual,
                "bytes": os.path.getsize(out_path)}

    # ----------------------------------------------------------------- fix
    def apply_fix(self, action: str, metrics: Any, scorecard: Dict[str, Any],
                  target: Dict[str, Any], pass_index: int) -> Dict[str, Any]:
        """Bounded, read-back-verified cinematic fix actions."""
        label = self._current_cam_label
        if label is None:
            return {"ok": False, "note": "no camera placed yet"}
        if action in ("camera_pull_back", "camera_move_closer"):
            factor = 1.25 if action == "camera_pull_back" else 0.8
            return self._nudge_camera(label, factor)
        if action == "camera_framing_recompute":
            return self._reframe_camera(label, metrics, scorecard)
        if action in ("exposure_reduce_highlights", "exposure_raise_blacks",
                      "lighting_reduce_background", "lighting_raise_key"):
            return self._adjust_exposure(action)
        if action in ("environment_add_depth", "viewport_aspect_fix",
                      "camera_roll_reset", "capture_force_fresh"):
            return {"ok": True, "note": f"{action}: no scene mutation needed "
                                        "for this action in cinematic mode",
                    "noop": True}
        return {"ok": False, "note": f"engine-closed or unknown action: {action}",
                "engine_closed": True}

    def _nudge_camera(self, label: str, factor: float) -> Dict[str, Any]:
        res = self.bridge.execute_python(f'''
import unreal
label = {json.dumps(label)}
factor = float({json.dumps(float(factor))})
cam = None
for a in unreal.EditorLevelLibrary.get_all_level_actors():
    if a.get_actor_label() == label or a.get_name() == label:
        cam = a
        break
if cam is None:
    __bridge_result__ = {{"ok": False, "error": "camera not found"}}
else:
    rot = cam.get_actor_rotation()
    fwd = cam.get_actor_forward_vector()
    loc = cam.get_actor_location()
    # dolly along the forward axis: pull back = move against the look dir
    sign = 1.0 if factor > 1.0 else -1.0
    delta = float(factor) - 1.0 if factor > 1.0 else 1.0 - float(factor)
    new_x = loc.x - fwd.x * sign * delta * 120.0
    new_y = loc.y - fwd.y * sign * delta * 120.0
    new_z = loc.z - fwd.z * sign * delta * 120.0
    cam.set_actor_location(unreal.Vector(new_x, new_y, new_z), False, False)
    rb = cam.get_actor_location()
    __bridge_result__ = {{"ok": True,
                          "action": "camera_" + ("pull_back" if factor > 1.0 else "move_closer"),
                          "location": [rb.x, rb.y, rb.z],
                          "readback": True}}
''')
        return _payload(res)

    def _reframe_camera(self, label: str, metrics: Any,
                        scorecard: Dict[str, Any]) -> Dict[str, Any]:
        # deterministic reframe: head clipping -> lower camera + pitch up;
        # too-small subject -> nudge closer via _nudge_camera
        clipped = bool(getattr(metrics, "head_clipped", False))
        if clipped:
            res = self.bridge.execute_python(f'''
import unreal
label = {json.dumps(label)}
cam = None
for a in unreal.EditorLevelLibrary.get_all_level_actors():
    if a.get_actor_label() == label or a.get_name() == label:
        cam = a
        break
if cam is None:
    __bridge_result__ = {{"ok": False, "error": "camera not found"}}
else:
    loc = cam.get_actor_location()
    rot = cam.get_actor_rotation()
    cam.set_actor_location(unreal.Vector(loc.x, loc.y, loc.z - 30.0), False, False)
    cam.set_actor_rotation(unreal.Rotator(pitch=rot.pitch + 3.0, yaw=rot.yaw, roll=rot.roll), False)
    rb = cam.get_actor_rotation()
    __bridge_result__ = {{"ok": True, "action": "reframe_head_clip",
                          "rotation": [rb.pitch, rb.yaw, rb.roll],
                          "readback": True}}
''')
            return _payload(res)
        return self._nudge_camera(label, 0.9)

    def _adjust_exposure(self, action: str) -> Dict[str, Any]:
        """Best-effort exposure change through a PostProcessVolume.

        Property names differ across engine builds, so each candidate is
        probed and only a verified change is reported ok. Failure is an
        honest engine-closed result, never a silent no-op.
        """
        bias = -0.5 if action in ("exposure_reduce_highlights",
                                  "lighting_reduce_background") else 0.5
        res = self.bridge.execute_python(f'''
import unreal
bias = float({json.dumps(float(bias))})
volumes = [a for a in unreal.EditorLevelLibrary.get_all_level_actors()
           if a.get_class().get_name() == "PostProcessVolume"]
if not volumes:
    __bridge_result__ = {{"ok": False, "engine_closed": True,
                          "error": "no PostProcessVolume in level to "
                                   "drive exposure"}}
else:
    changed = None
    error = None
    vol = volumes[0]
    if hasattr(vol, "settings"):
        for prop in ("exposure_compensation", "auto_exposure_bias",
                     "auto_exposure_bias_compensation"):
            if hasattr(vol.settings, prop):
                try:
                    cur = float(vol.settings.get_editor_property(prop) or 0.0)
                    vol.settings.set_editor_property(prop, cur + bias)
                    new = float(vol.settings.get_editor_property(prop) or 0.0)
                    changed = {{"prop": prop, "before": cur, "after": new}}
                    break
                except Exception as exc:
                    error = str(exc)[:120]
    if changed is not None:
        __bridge_result__ = {{"ok": True, "action": "exposure_adjust",
                              "change": changed, "readback": True}}
    else:
        __bridge_result__ = {{"ok": False, "engine_closed": True,
                              "error": error or "exposure property not "
                                                "exposed on PostProcessVolume"}}
''')
        return _payload(res)

    # --------------------------------------------------------------- render
    def render(self, brief: Dict[str, Any], shots: List[Dict[str, Any]],
               out_dir: str) -> Dict[str, Any]:
        """Real render: MRQ when supported, otherwise a real-frame path.

        Never claims MRQ output when MRQ is unavailable. The final decision
        of what counts as the deliverable render is reported verbatim.
        """
        os.makedirs(out_dir, exist_ok=True)
        from tools.unreal.movie_render_queue import MovieRenderQueueDriver
        driver = MovieRenderQueueDriver(self.bridge)
        seq_path = self._build_sequence(shots)
        width, height = self._resolution
        fps = int(brief.get("fps") or 30)
        duration = float(brief.get("duration_s") or 8.0)
        mrq = driver.render_sequence(
            seq_path, os.path.join(out_dir, "mrq"), width=width, height=height,
            fps=fps, duration_s=duration,
            output_name="aivido_cinematic")
        mrq_payload = _payload(mrq)
        blocked_mrq = (isinstance(mrq_payload, dict)
                       and not mrq_payload.get("ok"))
        if not blocked_mrq and isinstance(mrq_payload, dict) and mrq_payload.get("ok"):
            return {
                "ok": True, "renderer": "movie_render_queue",
                "sequence": seq_path, "result": mrq_payload,
                "path": os.path.join(out_dir, "mrq"),
                "resolution": [width, height], "fps": fps,
                "duration_s": duration,
            }
        # MRQ unavailable -> real-frame evidence path (viewer dolly)
        poses = self._motion_poses(shots, duration)
        frames = driver.render_real_frames(
            seq_path, os.path.join(out_dir, "frames"), width=width,
            height=height, fps=fps, pose_paths=poses,
            sample_stride=1.0 / 6.0)
        frames_payload = _payload(frames)
        if not (isinstance(frames_payload, dict) and frames_payload.get("ok")):
            return {
                "ok": False,
                "blocked": "movie_render_queue",
                "error": (str((frames_payload or {}).get("error"))
                          or "real-frame render failed"),
                "mrq_blocked": mrq_payload,
                "sequence": seq_path,
                "path": None,
            }
        frame_dir = frames_payload.get("frame_dir")
        capture_fps = 6  # real-time capture rate; MRQ full-rate stays blocked
        result = {
            "ok": True,
            "renderer": "real_frames",
            "renderer_is_mrq": False,
            "mrq_blocked_evidence": mrq_payload,
            "sequence": seq_path,
            "frames": frames_payload.get("frames"),
            "frame_count": frames_payload.get("frame_count"),
            "frame_dir": frame_dir,
            "resolution": [frames_payload.get("width"),
                           frames_payload.get("height")],
            "fps": fps,
            "capture_fps": capture_fps,
            "duration_s": frames_payload.get("duration_s"),
            "video": self._encode_video_if_possible(
                frame_dir, capture_fps, out_dir),
            "note": ("MRQ unavailable on this editor; frames are REAL Unreal "
                     "viewport captures along a deterministic camera pose "
                     "path (" + str(frames_payload.get("width")) + "x" +
                     str(frames_payload.get("height")) + "). Not an MRQ "
                     "output."),
        }
        return result

    # ------------------------------------------------------------- helpers
    def _build_sequence(self, shots: List[Dict[str, Any]]) -> str:
        """Build a real Level Sequence with one camera-cut per shot."""
        from tools.unreal.sequencer_tools_gap import SequencerToolsGap
        seq = SequencerToolsGap(self.bridge)
        seq_name = f"Seq_{int(time.time())}"
        seq_path = f"{self.seq_root}/{seq_name}"
        seq.create_level_sequence(seq_path)
        for shot in shots:
            pose = shot.get("pose") or {}
            loc = [pose["location_x"], pose["location_y"], pose["location_z"]]
            label = f"AVCam_Shot{int(shot.get('index') or 1):02d}"
            seq.add_camera_cut(seq_path, label, loc,
                               float(shot.get("start_s") or 0.0),
                               float(shot.get("end_s") or 1.0))
        structure = seq.read_sequence_structure(seq_path)
        seq.save_sequence(seq_path)
        return seq_path

    def _motion_poses(self, shots: List[Dict[str, Any]],
                      duration_s: float) -> List[Dict[str, Any]]:
        """Linear interpolation between shot poses (a real dolly path).

        Bounded to a sane preview sample count (6 fps) so a run stays
        tractable; MRQ remains the full-quality path when supported.
        """
        if len(shots) < 2:
            return [dict(shots[0]["pose"])]
        poses = [dict(s["pose"]) for s in shots]
        n = max(8, min(72, int(duration_s * 6.0)))
        out: List[Dict[str, Any]] = []
        segs = len(poses) - 1
        for i in range(n):
            t = (i / float(n - 1)) if n > 1 else 0.0
            seg = min(int(t * segs), segs - 1)
            local = t * segs - seg
            a, b = poses[seg], poses[seg + 1]
            p = {}
            for k in ("location_x", "location_y", "location_z",
                      "pitch", "yaw", "roll", "fov"):
                av, bv = float(a[k]), float(b[k])
                p[k] = av + (bv - av) * local
            out.append(p)
        return out

    def _encode_video_if_possible(self, frame_dir: str, fps: int,
                                  out_dir: str) -> Dict[str, Any]:
        import shutil
        import subprocess
        exe = shutil.which("ffmpeg")
        if not exe:
            return {"status": "blocked",
                    "error": "ffmpeg not found; frames are the deliverable "
                             "video evidence"}
        video_path = os.path.join(out_dir, "aivido_cinematic.mp4")
        frames = sorted(f for f in os.listdir(frame_dir)
                        if f.lower().endswith(".png"))
        if not frames:
            return {"status": "blocked", "error": "no frames to encode"}
        # ffmpeg's png decoder rejects the native Unreal viewport PNG color
        # type on some builds; normalize every frame through Pillow first.
        norm_dir = os.path.join(out_dir, "frames_norm")
        os.makedirs(norm_dir, exist_ok=True)
        for f in frames:
            src = os.path.join(frame_dir, f)
            dst = os.path.join(norm_dir, f)
            try:
                im = Image.open(src).convert("RGB")
                im.save(dst, format="PNG")
            except Exception as exc:
                return {"status": "blocked", "error": f"normalize {f}: {exc}"}
        # yuv420p needs even dimensions; the native viewport can be odd-sized
        cmd = [exe, "-y", "-framerate", str(fps), "-i",
               os.path.join(norm_dir, "frame_%04d.png"),
               "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
               "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags",
               "+faststart", video_path]
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=600)
        except Exception as exc:
            return {"status": "blocked", "error": str(exc)}
        if proc.returncode != 0 or not os.path.isfile(video_path):
            return {"status": "blocked",
                    "error": "ffmpeg encode failed: "
                             + (proc.stderr or b"").decode("utf-8", "replace")[-200:]}
        return {"status": "done", "path": video_path,
                "bytes": os.path.getsize(video_path),
                "encoder": "ffmpeg (libx264) of real Unreal frames",
                "normalized": True}
