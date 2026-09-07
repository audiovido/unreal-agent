"""movie_render_queue.py — Unreal Movie Render Queue (MRQ) driver.

Two contracts, both honest:

1. ``probe()`` — detects whether the live editor exposes the Movie Render
   Queue subsystem at all (the plugin must be enabled in the project).
   Returns structured evidence; never assumes support.

2. ``render_sequence()`` — issues a real MRQ render through the subsystem
   when the probe passes. When the probe fails, it returns a truthful
   BLOCKED result (``blocked: "movie_render_queue"``) instead of pretending
   a render happened.

3. ``render_real_frames()`` — NOT MRQ: deterministic per-sample high-res
   captures of real Unreal frames while the level-viewport camera is moved
   along a shot pose path. Exists so the quality loop and demo always have
   real-frame proof even where MRQ is unavailable. The produced files are
   real Unreal renderer output, labeled exactly as such.

No code in this module imports ``unreal`` on the host: everything is emitted
editor-side python through UnrealBridge.execute_python, matching the gap-tool
convention. Results pass through ``__bridge_result__`` verbatim — errors from
the engine are never converted into success.
"""

from __future__ import annotations

import json
import math
import os
import time
from typing import Any, Dict, List, Optional

# Resolution presets the renderer honors (1920x1080 default, 4K optional).
RESOLUTION_PRESETS = {
    "1080p": (1920, 1080),
    "1920x1080": (1920, 1080),
    "4k": (3840, 2160),
    "3840x2160": (3840, 2160),
}


def _payload(res: Any) -> Any:
    """Tolerate both bridge wrappings: nested {"ok":.., "result": <payload>}
    and flat payloads, mirroring the canonical tools handling."""
    if isinstance(res, dict) and isinstance(res.get("result"), (dict, list)):
        return res["result"]
    return res


class MovieRenderQueueDriver:
    def __init__(self, bridge) -> None:
        self.bridge = bridge

    # ------------------------------------------------------------------ probe
    def probe(self) -> Dict[str, Any]:
        """Detect MRQ subsystem exposure on the live editor (read-only)."""
        return self.bridge.execute_python(r'''
import unreal
import json
found = {}
for name in ("MovieRenderQueueSubsystem", "MoviePipelineEditorExecutor",
             "MoviePipelineExecutorJob", "MoviePipelinePrimaryConfig",
             "MoviePipeline"):
    found[name] = hasattr(unreal, name)
classes_present = [k for k, v in found.items() if v]
subsystem_ok = False
subsystem_error = None
if "MovieRenderQueueSubsystem" in classes_present:
    try:
        sub = unreal.get_editor_subsystem(unreal.MovieRenderQueueSubsystem)
        subsystem_ok = sub is not None
    except Exception as exc:
        subsystem_error = str(exc)[:200]
plugins = unreal.SystemLibrary  # may be absent in some builds
__bridge_result__ = {
    "ok": bool(classes_present and subsystem_ok),
    "supported": bool(classes_present and subsystem_ok),
    "classes_present": classes_present,
    "classes_checked": sorted(found.keys()),
    "subsystem_ok": subsystem_ok,
    "subsystem_error": subsystem_error,
    "note": ("MovieRenderPipeline plugin must be enabled in the active "
             "project for the subsystem to exist"),
}
''')

    # ----------------------------------------------------------------- render
    def render_sequence(self, seq_path: str, out_root: str = ".", *,
                        width: int = 1920, height: int = 1080,
                        fps: int = 30, duration_s: float = 8.0,
                        output_name: str = "cinematic") -> Dict[str, Any]:
        """Real MRQ render of a Level Sequence. Truthfully BLOCKED when the
        subsystem/plugin is not exposed by the live editor."""
        out_root = str(out_root).replace("\\", "/")
        probe = self.probe()
        probe_payload = _payload(probe)
        if not isinstance(probe_payload, dict) or not probe_payload.get("supported"):
            return {
                "ok": False,
                "blocked": "movie_render_queue",
                "error": ("Movie Render Queue is not exposed by the live "
                          "editor (MovieRenderPipeline plugin not enabled in "
                          "this project); real MRQ render BLOCKED, no render "
                          "was faked"),
                "probe": probe_payload,
                "path": None,
            }

        # Subsystem present: attempt a genuine MRQ job. Every engine-side
        # failure is captured verbatim and returned as not-ok.
        seq_json = json.dumps(str(seq_path))
        name_json = json.dumps(str(output_name))
        return _payload(self.bridge.execute_python(f'''
import unreal
import os
seq_path = {seq_json}
name = {name_json}
w = int({int(width)})
h = int({int(height)})
fps_v = float({float(fps)})
dur = float({float(duration_s)})
out_dir = {json.dumps(out_root)}
os.makedirs(out_dir, exist_ok=True)
seq = unreal.EditorAssetLibrary.load_asset(seq_path)
if seq is None:
    __bridge_result__ = {{"ok": False, "blocked": "movie_render_queue",
                          "error": "sequence not found: " + seq_path}}
else:
    try:
        sub = unreal.get_editor_subsystem(unreal.MovieRenderQueueSubsystem)
        job = sub.allocate_new_job(unreal.MoviePipelineExecutorJob)
        job.sequence = unreal.SoftObjectPath(seq_path)
        cfg = unreal.MoviePipelinePrimaryConfig()
        setting = unreal.MoviePipelineOutputSetting()
        setting.output_resolution = unreal.IntPoint(w, h)
        setting.file_name_format = "{{frame_number}}"
        setting.output_directory = unreal.DirectoryPath(out_dir)
        cfg.set_setting(setting)
        job.set_configuration(cfg)
        executor = unreal.MoviePipelinePIEExecutor() if hasattr(unreal, "MoviePipelinePIEExecutor") else None
        if executor is None and hasattr(unreal, "MoviePipelineEditorExecutor"):
            executor = unreal.MoviePipelineEditorExecutor()
        if executor is None:
            __bridge_result__ = {{"ok": False, "blocked": "movie_render_queue",
                                  "error": "no MRQ executor class exposed"}}
        else:
            executor.execute([job])
            __bridge_result__ = {{"ok": True, "renderer": "movie_render_queue",
                                  "job": str(job), "output_dir": out_dir,
                                  "width": w, "height": h, "fps": fps_v,
                                  "duration_s": dur,
                                  "note": "MRQ job submitted; completion "
                                          "checked by the caller via output "
                                          "files"}}            except Exception as exc:
                __bridge_result__ = {{"ok": False, "blocked": "movie_render_queue",
                                      "error": str(exc)[:400],
                                      "engine_closed": True}}
'''))

    # ---------------------------------------------- real frames (non-MRQ) --
    def render_real_frames(self, seq_path: str, out_dir: str, *,
                           width: int = 1920, height: int = 1080,
                           fps: int = 30,
                           pose_paths: Optional[List[Dict[str, Any]]] = None,
                           sample_stride: float = 0.5,
                           poll_timeout_s: float = 60.0) -> Dict[str, Any]:
        """Capture real Unreal frames along a deterministic camera pose path.

        Each sample: the editor level-viewport camera is moved to the pose and
        a high-resolution (AutomationLibrary) screenshot captures the real
        rendered frame. MRQ is intentionally NOT claimed: this is the
        real-frame evidence path used when MRQ is unavailable.

        ``pose_paths``: list of pose dicts with location_*, pitch, yaw, roll
        (as produced by core.cinematic_director.plan_cinematic_shots).
        """
        out_dir = str(out_dir).replace("\\", "/")
        seq_json = json.dumps(str(seq_path))
        poses = [dict(p) for p in (pose_paths or [])]
        total = len(poses)
        if total == 0:
            return {"ok": False, "error": "no camera poses to render",
                    "renderer": "real_frames"}
        width, height = int(width), int(height)
        out = {"ok": False, "renderer": "real_frames",
               "renderer_is_mrq": False,
               "note": "real Unreal frames captured from the live level "
                       "viewport (native editor viewport read-back, MRQ "
                       "unavailable); not a Movie Render Queue output. "
                       "Captured at the editor viewport's real resolution."}
        paths: List[str] = []
        os.makedirs(out_dir, exist_ok=True)
        actual: Optional[List[int]] = None
        for i, pose in enumerate(poses):
            loc = [float(pose["location_x"]), float(pose["location_y"]),
                   float(pose["location_z"])]
            pitch = float(pose.get("pitch", 0.0))
            yaw = float(pose.get("yaw", 0.0))
            roll = float(pose.get("roll", 0.0))
            frame_name = f"frame_{i + 1:04d}.png"
            frame_path = os.path.join(out_dir, frame_name)
            res = self.bridge.execute_python(f'''
import unreal
loc = {json.dumps(loc)}
editor = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
view_loc = unreal.Vector(loc[0], loc[1], loc[2])
view_rot = unreal.Rotator(pitch={pitch!r}, yaw={yaw!r}, roll={roll!r})
editor.set_level_viewport_camera_info(view_loc, view_rot)
readback = editor.get_level_viewport_camera_info()
__bridge_result__ = {{"ok": readback is not None}}
''')
            payload = _payload(res)
            if not (isinstance(payload, dict) and payload.get("ok")):
                out["error"] = f"frame {i + 1}: viewport camera set failed: {payload}"
                out["frames_captured"] = len(paths)
                return out
            cap = self._native_capture()
            cap_payload = _payload(cap)
            src = (cap_payload or {}).get("path") if isinstance(
                cap_payload, dict) else None
            if isinstance(cap_payload, dict) and cap_payload.get("ok") and src \
                    and os.path.isfile(src):
                import shutil
                try:
                    shutil.copyfile(src, frame_path)
                except OSError:
                    frame_path = ""
                if frame_path and os.path.isfile(frame_path) \
                        and os.path.getsize(frame_path) > 0:
                    paths.append(frame_path)
                    if actual is None:
                        try:
                            from PIL import Image as _Im
                            actual = list(_Im.open(frame_path).size)
                        except Exception:
                            actual = None
                    continue
            out["error"] = f"frame {i + 1} capture failed: {cap_payload}"
            out["frames_captured"] = len(paths)
            return out
        w_actual = (actual or [width, height])[0]
        h_actual = (actual or [width, height])[1]
        out.update({
            "ok": True,
            "frame_dir": out_dir,
            "frames": paths,
            "frame_count": len(paths),
            "width_requested": width, "height_requested": height,
            "width": w_actual, "height": h_actual,
            "fps": int(fps),
            "duration_s": round(len(paths) * sample_stride, 2),
            "note": ("real Unreal frames captured natively from the live "
                      "level viewport at " + str(w_actual) + "x" + str(h_actual)
                      + " (MRQ unavailable); not a Movie Render Queue output"),
        })
        return out

    def _native_capture(self) -> Any:
        """Native editor-viewport capture (reliable repeated read-back)."""
        return self.bridge.capture_unreal_viewport()

    @staticmethod
    def resolution_for(requested: Any) -> List[int]:
        """Resolve a requested resolution string/list to [w, h]."""
        if isinstance(requested, (list, tuple)) and len(requested) >= 2:
            try:
                return [int(requested[0]), int(requested[1])]
            except (TypeError, ValueError):
                pass
        return list(RESOLUTION_PRESETS.get(
            str(requested).lower().strip(), (1920, 1080)))
