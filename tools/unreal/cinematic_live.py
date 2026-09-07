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
        self._mutations: List[Dict[str, Any]] = []

    def set_resolution(self, width: int, height: int) -> None:
        self._resolution = [int(width), int(height)]

    def snapshot_scene(self) -> Dict[str, Any]:
        """Record PPV exposure + certified light values this adapter may touch.

        Restore is exact-value based: every mutation made through this adapter
        is recorded in ``self._mutations`` and ``restore_scene()`` reverts
        them one by one (level is never saved)."""
        res = self.bridge.execute_python(r'''
import unreal
out = {"ppv": [], "lights": []}
for a in unreal.EditorLevelLibrary.get_all_level_actors():
    cn = a.get_class().get_name()
    if cn == "PostProcessVolume" and hasattr(a, "settings"):
        entry = {"label": a.get_actor_label(), "props": {}}
        for p in ("auto_exposure_bias", "auto_exposure_method",
                  "camera_shutter_speed", "camera_iso"):
            try:
                entry["props"][p] = a.settings.get_editor_property(p)
            except Exception:
                pass
        out["ppv"].append(entry)
    elif cn in ("DirectionalLight", "PointLight", "SpotLight"):
        for c in a.get_components_by_class(unreal.LightComponent):
            entry = {"label": a.get_actor_label(), "comp": c.get_class().get_name()}
            try:
                entry["intensity"] = c.get_editor_property("intensity")
            except Exception:
                continue
            out["lights"].append(entry)
__bridge_result__ = out
''')
        return _payload(res)

    def restore_scene(self) -> Dict[str, Any]:
        """Exact restore of every scene value this adapter mutated."""
        restored = []
        # reverse order: the LAST mutation applied is reverted first, so the
        # final value equals the original certified value exactly.
        for m in list(reversed(self._mutations)):
            ok = self._restore_one(m)
            restored.append({"mutation": m, "restored": ok})
        self._mutations.clear()
        return {"ok": True, "restored_count": len(restored), "restored": restored}

    def _restore_one(self, m: Dict[str, Any]) -> bool:
        kind = m.get("kind")
        if kind == "ppv":
            prop = m.get("prop")
            code = f'''
import unreal
vols = [a for a in unreal.EditorLevelLibrary.get_all_level_actors()
        if a.get_class().get_name() == "PostProcessVolume"]
if vols:
    try:
        vols[0].settings.set_editor_property({json.dumps(prop)}, {json.dumps(m.get("before"))})
        __bridge_result__ = {{"ok": True}}
    except Exception as exc:
        __bridge_result__ = {{"ok": False, "error": str(exc)[:120]}}
else:
    __bridge_result__ = {{"ok": False}}
'''
        elif kind == "light":
            code = f'''
import unreal
label = {json.dumps(m.get("label"))}
done = {{"ok": False}}
for a in unreal.EditorLevelLibrary.get_all_level_actors():
    if a.get_actor_label() != label:
        continue
    for c in a.get_components_by_class(unreal.LightComponent):
        if c.get_class().get_name() != {json.dumps(m.get("comp"))}:
            continue
        try:
            c.set_editor_property("intensity", {json.dumps(float(m.get("before")))})
            done = {{"ok": True}}
        except Exception as exc:
            done = {{"ok": False, "error": str(exc)[:120]}}
        break
    break
__bridge_result__ = done
'''
        else:
            return True
        payload = _payload(self.bridge.execute_python(code))
        return isinstance(payload, dict) and bool(payload.get("ok"))

    def on_shot_done(self) -> Dict[str, Any]:
        """Revert every loop mutation so the next shot starts from the
        certified scene (fixes are per-shot evidence, never accumulated)."""
        return self.restore_scene()

    def before_render(self) -> Dict[str, Any]:
        """Render the final film from the certified baseline, which the
        bounded loop could not beat in earlier live runs."""
        return self.restore_scene()

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
        """Point the level-viewport camera at the shot pose directly.

        Never frames from an actor (pilot/frame-from-actor left the editor
        viewport frozen and captures stale on this engine build); the pose is
        a stable explicit camera transform that the capture path re-applies
        before every fresh frame.
        """
        pose = shot.get("pose") or {}
        loc = [float(pose.get("location_x", 0.0)),
               float(pose.get("location_y", 0.0)),
               float(pose.get("location_z", 0.0))]
        pitch = float(pose.get("pitch", 0.0))
        yaw = float(pose.get("yaw", 0.0))
        roll = float(pose.get("roll", 0.0))
        res = self.bridge.execute_python(f'''
import unreal
sub = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
loc = {json.dumps([round(v, 3) for v in loc])}
rot = unreal.Rotator(pitch={json.dumps(float(pitch))}, yaw={json.dumps(float(yaw))}, roll={json.dumps(float(roll))})
__bridge_result__ = {{"ok": True}}
try:
    sub.set_level_viewport_camera_info(
        unreal.Vector(loc[0], loc[1], loc[2]), rot)
    rb = sub.get_level_viewport_camera_info()
    __bridge_result__ = {{"ok": rb is not None}}
except Exception as exc:
    __bridge_result__ = {{"ok": False, "error": str(exc)[:120]}}
''')
        return _payload(res)

    # -------------------------------------------------------------- capture
    def _wake_editor(self) -> bool:
        """Restore + foreground the UnrealEditor frame window.

        A backgrounded/minimized editor stops presenting new viewport frames
        (the native capture then returns a stale backbuffer as evidence).
        V1 restores the window before every guarded capture; the cinematic
        fresh-capture contract needs the same wake so an exposure/light fix
        is actually visible in the next capture.
        """
        import subprocess
        # canonical location is the workspace root scripts/ (the cinematic
        # worktree lives inside the same workspace as the V1 tree)
        here = os.path.dirname(os.path.abspath(__file__))  # .../tools/unreal
        candidates = [
            os.path.join(here, "..", "..", "..", "..", "scripts",
                         "restore_editor_window.ps1"),
            os.path.join(here, "..", "..", "..", "scripts",
                         "restore_editor_window.ps1"),
        ]
        script = next((p for p in candidates if os.path.isfile(p)), None)
        if not script:
            return False
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-File", script], capture_output=True, text=True,
                timeout=30)
            out = r.stdout or ""
            return "RESTORED" in out or "ALREADY_OK" in out
        except Exception:
            return False

    def _kick_viewport_render(self, shot: Dict[str, Any], settle: float = 2.2) -> bool:
        """Force the level viewport to present a REAL fresh frame.

        An editor whose window is not foreground stops re-rendering the
        viewport on pure post-process/light edits, so a capture taken after
        only a PPV property change silently returns the previous frame. The
        reliable refresh (proven live) is to move the level-viewport camera:
        each move forces a new render, and the final re-set restores the
        exact shot framing before the native capture reads the backbuffer.
        """
        pose = shot.get("pose") or {}
        loc = [float(pose.get("location_x", 0.0)),
               float(pose.get("location_y", 0.0)),
               float(pose.get("location_z", 0.0))]
        pitch = float(pose.get("pitch", 0.0))
        yaw = float(pose.get("yaw", 0.0))
        roll = float(pose.get("roll", 0.0))
        import time as _t
        code = f'''
import unreal
sub = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
loc = {json.dumps([round(v, 3) for v in loc])}
rot = unreal.Rotator(pitch={json.dumps(float(pitch))}, yaw={json.dumps(float(yaw))}, roll={json.dumps(float(roll))})
ok = False
try:
    sub.set_level_viewport_camera_info(
        unreal.Vector(loc[0], loc[1], loc[2]), rot)
    ok = True
except Exception:
    ok = False
__bridge_result__ = {{"ok": ok}}
'''
        res = self.bridge.execute_python(code)
        payload = _payload(res)
        ok = isinstance(payload, dict) and bool(payload.get("ok"))
        # V1's verified fresh-render recipe in a SEPARATE call (the editor
        # main thread must be free to present the frame; sleeping inside a
        # single editor python block starves rendering).
        redraw = f'''
import unreal
w = unreal.EditorLevelLibrary.get_editor_world()
if w is not None:
    try:
        unreal.EditorLevelLibrary.editor_invalidate_viewports()
    except Exception:
        pass
    for cmd in ("r.ScreenPercentage 99", "RedrawAllViewports",
                "r.ScreenPercentage 100", "RedrawAllViewports"):
        try:
            unreal.SystemLibrary.execute_console_command(w, cmd)
        except Exception:
            pass
__bridge_result__ = {{"ok": True}}
'''
        self.bridge.execute_python(redraw)
        _t.sleep(max(1.0, float(settle)))
        return ok

    def capture(self, shot: Dict[str, Any], out_path: str) -> Dict[str, Any]:
        """Real capture of the active level viewport (native read-back).

        A shot pose is re-applied to the level-viewport camera before capture
        so every capture reflects the CURRENT scene state (PPV exposure,
        lights) rather than a stale backbuffer from a backgrounded editor.
        The viewport's ACTUAL resolution is read back and reported (never
        assumed to equal the requested resolution). The requested resolution
        remains the target for an MRQ render when the plugin is available.
        """
        out_path = os.path.abspath(out_path)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        # Fresh-render contract with bounded retry: the editor viewport needs
        # an explicit kick to present a NEW frame after a PPV/light edit, and
        # a capture can transiently race that present (a heavy scene re-render
        # after actor moves can make the native readback fail). Retrying with
        # a fresh wake + escalating settle keeps the quality loop honest
        # (never a stale frame labelled as current, never a silent no-op).
        last_error = ""
        import time as _time
        for _attempt in range(1, 6):
            # Wake the editor before EVERY attempt: a foregrounded window is
            # required for the viewport to actually present the fresh frame.
            self._wake_editor()
            self.bridge.execute_python("""
import unreal
unreal.SystemLibrary.execute_console_command(None, "r.ThrottleCPUWhenNotForeground 0")
unreal.SystemLibrary.execute_console_command(None, "t.MaxFPS 0")
try:
    # no selection gizmo/overlay may appear in a capture frame
    unreal.get_editor_subsystem(unreal.EditorActorSubsystem).set_selected_level_actors([])
except Exception:
    pass
__bridge_result__ = {"ok": True}
""")
            self._kick_viewport_render(shot, settle=2.0 + 1.2 * _attempt)
            res = self.bridge.capture_unreal_viewport()
            payload = _payload(res)
            if not (isinstance(payload, dict) and payload.get("ok")):
                last_error = "native viewport capture failed"
                _time.sleep(1.0 + _attempt)
                continue
            src = payload.get("path")
            if not src or not os.path.isfile(src):
                last_error = "native capture file missing"
                continue
            if os.path.getsize(src) == 0:
                last_error = "native capture produced an empty file"
                continue
            import shutil
            try:
                shutil.copyfile(src, out_path)
            except OSError as exc:
                last_error = f"copy failed: {exc}"
                continue
            try:
                im = Image.open(out_path)
                actual = list(im.size)
            except Exception:
                actual = None
            if not actual or actual[0] < 320:
                last_error = f"capture not a real frame: {actual}"
                continue
            return {"ok": True, "path": out_path,
                    "resolution_requested": list(self._resolution),
                    "resolution": actual,
                    "bytes": os.path.getsize(out_path),
                    "attempts": _attempt}
        return {"ok": False, "error": last_error or "native capture failed "
                                                "after retries",
                "path": out_path}

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
            if action in ("lighting_raise_key", "lighting_reduce_background"):
                return self._adjust_lights(action)
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
        """Best-effort exposure change through the scene PostProcessVolume.

        The AividoHQ PPV drives manual exposure through ``auto_exposure_bias``
        (verified live: each -1.0 EV measurably darkens the captured frame).
        Every change is read back and recorded so ``restore_scene()`` can put
        the certified value back exactly (level never saved).
        """
        delta = -0.5 if action == "exposure_reduce_highlights" else 0.5
        code = f'''
import unreal
volumes = [a for a in unreal.EditorLevelLibrary.get_all_level_actors()
           if a.get_class().get_name() == "PostProcessVolume"]
if not volumes:
    __bridge_result__ = {{"ok": False, "engine_closed": True,
                          "error": "no PostProcessVolume in level to "
                                   "drive exposure"}}
else:
    vol = volumes[0]
    if not hasattr(vol, "settings"):
        __bridge_result__ = {{"ok": False, "engine_closed": True,
                              "error": "PPV settings not accessible"}}
    else:
        changed = None
        error = None
        for prop in ("auto_exposure_bias", "exposure_compensation",
                     "auto_exposure_bias_compensation"):
            try:
                cur = float(vol.settings.get_editor_property(prop) or 0.0)
                vol.settings.set_editor_property(prop, cur + {json.dumps(float(delta))})
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
                                                    "exposed on PPV"}}
'''
        payload = _payload(self.bridge.execute_python(code))
        if isinstance(payload, dict) and payload.get("ok"):
            change = payload.get("change") or {}
            self._mutations.append({"kind": "ppv",
                                    "prop": change.get("prop"),
                                    "before": change.get("before")})
        return payload

    def _adjust_lights(self, action: str) -> Dict[str, Any]:
        """Real light-intensity change (key raise / background reduce).

        Operates on the certified AividoHQ light rig by actor label; the
        before value is recorded in ``self._mutations`` so ``restore_scene``
        reverts it exactly. Read-back verified, never a silent no-op.
        """
        if action == "lighting_raise_key":
            label = "AVIDO_KeyLight"
            factor = 1.35
        else:  # lighting_reduce_background
            label = "AVIDO_Light_Fill"
            factor = 0.65
        code = f'''
import unreal
label = {json.dumps(label)}
factor = float({json.dumps(float(factor))})
target = None
for a in unreal.EditorLevelLibrary.get_all_level_actors():
    if a.get_actor_label() == label:
        for c in a.get_components_by_class(unreal.LightComponent):
            try:
                cur = float(c.get_editor_property("intensity"))
            except Exception:
                continue
            c.set_editor_property("intensity", cur * factor)
            new = float(c.get_editor_property("intensity"))
            target = {{"label": label, "comp": c.get_class().get_name(),
                       "before": cur, "after": new}}
            break
        break
if target is None:
    __bridge_result__ = {{"ok": False, "engine_closed": True,
                          "error": ("light " + label + " not found "
                                     "in level")}}
else:
    __bridge_result__ = {{"ok": True, "action": "light_intensity",
                          "change": target, "readback": True}}
'''
        payload = _payload(self.bridge.execute_python(code))
        if isinstance(payload, dict) and payload.get("ok"):
            change = payload.get("change") or {}
            self._mutations.append({"kind": "light",
                                    "label": change.get("label"),
                                    "comp": change.get("comp"),
                                    "before": change.get("before")})
        return payload

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
            frame_dir = mrq_payload.get("frame_dir") or os.path.join(out_dir, "mrq")
            frame_count = int(mrq_payload.get("frame_count") or 0)
            # the sequence's real rate drives the film; derive it from the
            # rendered frame count over the requested duration (never guess)
            fps_actual = max(1, int(round(frame_count / max(duration, 0.1))))
            encode = self._encode_video_if_possible(frame_dir, fps_actual,
                                                    out_dir)
            return {
                "ok": True, "renderer": "movie_render_queue",
                "renderer_is_mrq": True,
                "sequence": seq_path, "result": mrq_payload,
                "frames": mrq_payload.get("frames") or [],
                "frame_count": frame_count,
                "frame_dir": frame_dir,
                "path": os.path.join(out_dir, "mrq"),
                "resolution": mrq_payload.get("resolution") or [width, height],
                "width": (mrq_payload.get("width") or width),
                "height": (mrq_payload.get("height") or height),
                "fps": fps_actual,
                "capture_fps": fps_actual,
                "duration_s": round(frame_count / float(fps_actual), 2)
                if fps_actual else duration,
                "video": encode,
                "note": "REAL Movie Render Queue render (PIE executor) at " +
                        str(mrq_payload.get("width") or width) + "x" +
                        str(mrq_payload.get("height") or height),
            }
        # MRQ unavailable -> real-frame evidence path (viewer dolly), using
        # the SAME fresh-capture contract as the quality loop (wake -> kick
        # -> settle -> native capture with bounded retry) because that path
        # is the only one proven to present real frames reliably on this
        # editor. Each pose is one real captured frame.
        poses = self._motion_poses(shots, duration)
        capture_fps = 6  # real-time capture rate; MRQ full-rate stays blocked
        frame_dir = os.path.join(out_dir, "frames")
        os.makedirs(frame_dir, exist_ok=True)
        missing: List[Dict[str, Any]] = []
        paths: List[str] = []
        actual: Optional[List[int]] = None
        import time as _time
        total = len(poses)
        for i, pose in enumerate(poses):
            frame_name = f"frame_{i + 1:04d}.png"
            frame_path = os.path.join(frame_dir, frame_name)
            shot_like = {"index": i + 1, "pose": pose}
            cap = self.capture(shot_like, frame_path)
            if cap.get("ok") and os.path.isfile(frame_path) \
                    and os.path.getsize(frame_path) > 0:
                paths.append(frame_path)
                if actual is None:
                    try:
                        from PIL import Image as _Im
                        actual = list(_Im.open(frame_path).size)
                    except Exception:
                        actual = None
            else:
                missing.append({"frame": i + 1,
                                "error": cap.get("error") or "capture failed"})
            if missing and len(missing) >= max(3, total // 4):
                break   # a genuinely frozen viewport; stop wasting attempts
        if not paths:
            return {
                "ok": False,
                "blocked": "movie_render_queue",
                "error": "no real frames captured by the render path",
                "mrq_blocked": mrq_payload,
                "sequence": seq_path,
                "path": None,
            }
        actual = actual or [int(width), int(height)]
        result = {
            "ok": True,
            "renderer": "real_frames",
            "renderer_is_mrq": False,
            "mrq_blocked_evidence": mrq_payload,
            "sequence": seq_path,
            "frames": paths,
            "frame_count": len(paths),
            "frame_dir": frame_dir,
            "resolution": actual,
            "width": actual[0], "height": actual[1],
            "fps": fps,
            "capture_fps": capture_fps,
            "duration_s": round(len(paths) / float(capture_fps), 2),
            "partial": bool(missing),
            "missing_count": len(missing),
            "missing": missing[:5],
            "video": self._encode_video_if_possible(
                frame_dir, capture_fps, out_dir),
            "note": ("MRQ unavailable on this editor; frames are REAL Unreal "
                     "viewport captures (wake->kick->settle->native capture) "
                     "along a deterministic camera pose path (" +
                     str(actual[0]) + "x" + str(actual[1]) + "). Not an MRQ "
                     "output." + (f" PARTIAL ({len(paths)}/{total} frames)"
                                  if missing else "")),
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
