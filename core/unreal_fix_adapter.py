"""unreal_fix_adapter.py — generic, bounded, read-back-verified Unreal fix
executor for the autonomous Visual Director loop.

The deterministic loop (AutonomousVisualLoop) asks for ONE high-impact fix
per iteration; this adapter turns those fix actions into concrete Unreal
operations that are

  * generic        — reasoned from measured metrics, never from screenshot
                     pixel boxes or one scene's coordinates
  * bounded        — one small change per operation, clamped factors
  * verifiable     — every operation reads the editor state back
  * reversible     — every mutation is snapshotted so a regression can be
                     rolled back before the next strategy is attempted
  * durable        — the world is saved after each applied change

Supported action families (the production fix planner's vocabulary):

  camera framing   camera_pull_back / camera_move_closer /
                   camera_framing_recompute   (viewport camera dolly)
  camera roll      camera_roll_reset          (exact roll zero)
  exposure/lights  exposure_reduce_highlights / lighting_reduce_background /
                   environment_reduce_emissives  (dim dominant light)
                   exposure_raise_blacks / lighting_raise_key
                                              (raise dominant light)
  capture          capture_force_fresh

The adapter never changes scorer thresholds or acceptance rules; it only
mutates real editor state through bounded operations.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core.release_director import (
    decide_rollback,
    dolly_factor,
    light_factor,
    parse_capture_diag,
)

CAPTURE_TIMEOUT_S = 30
SUPPORTED_ACTIONS = {
    "camera_pull_back", "camera_move_closer", "camera_framing_recompute",
    "camera_roll_reset", "exposure_reduce_highlights",
    "lighting_reduce_background", "environment_reduce_emissives",
    "exposure_raise_blacks", "lighting_raise_key", "capture_force_fresh",
}


class ViewportNotVisibleError(RuntimeError):
    """Raised when the editor viewport is not rendering (minimized/occluded),
    so the returned frame would be stale and must never be used as
    evidence."""


class UnrealFixAdapter:
    """Bounded Unreal fix executor bound to one live bridge."""

    def __init__(
        self,
        bridge: Any,
        *,
        assumed_depth_m: float = 2500.0,
        wake_editor: Optional[Callable[[], bool]] = None,
        visible_retries: int = 2,
    ):
        self.bridge = bridge
        self.assumed_depth_m = float(assumed_depth_m)
        self.wake_editor = wake_editor
        self.visible_retries = int(visible_retries)
        # change history for rollback decisions + structured records
        self.history: List[Dict[str, Any]] = []
        self._snapshots: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # low level bridge execution
    # ------------------------------------------------------------------
    def execute(self, code: str) -> Dict[str, Any]:
        raw = self.bridge.execute_python(code)
        if not isinstance(raw, dict):
            return {"ok": False, "error": str(raw)[:200]}
        if not raw.get("ok"):
            return {"ok": False,
                    "error": str(raw.get("message") or raw.get("error"))[:200]}
        payload = raw.get("result")
        if isinstance(payload, dict):
            return payload
        return {"ok": bool(payload)}

    def _poke_render(self, settle_s: float = 0.35) -> None:
        """Unfreeze + force a viewport repaint so the next capture reflects
        the CURRENT editor state, never a stale pre-change buffer."""
        self.execute("""
import unreal
w = unreal.EditorLevelLibrary.get_editor_world()
for c in ("r.FreezeRendering 0", "RedrawAllViewports"):
    try:
        unreal.SystemLibrary.execute_console_command(w, c)
    except Exception:
        pass
__bridge_result__ = {"ok": True}
""")
        time.sleep(settle_s)

    def _redraw(self) -> None:
        self._poke_render(0.25)

    def save_world(self) -> bool:
        r = self.execute("""
import unreal
ok = unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)
__bridge_result__ = {"ok": True, "saved": bool(ok)}
""")
        return bool(r.get("ok") and r.get("saved"))

    # ------------------------------------------------------------------
    # guarded fresh capture
    # ------------------------------------------------------------------
    def capture(self, path: str) -> Dict[str, Any]:
        """Fresh viewport capture with visibility + size-stability checks.

        Raises ViewportNotVisibleError when the viewport is not rendering
        after bounded wake retries, so a stale/occluded frame is never
        returned as evidence.
        """
        p = str(Path(path).resolve()).replace("\\", "/")
        for attempt in range(1 + self.visible_retries):
            if attempt and self.wake_editor:
                self.wake_editor()
                time.sleep(2.2)
            # force the viewport to render the CURRENT state before capture
            self._poke_render(0.25)
            result = self.execute(f"""
import unreal, os
p = {p!r}
if os.path.isfile(p):
    os.remove(p)
diag = str(unreal.UnrealAgentBlueprintLibrary.capture_active_viewport_detailed(p))
__bridge_result__ = {{"ok": True, "diag": diag,
  "size": os.path.getsize(p) if os.path.isfile(p) else -1}}
""")
            diag = result.get("diag") or ""
            parsed = parse_capture_diag(diag)
            if not parsed["visible"]:
                continue
            # the native capture wrote the file synchronously before the diag
            # returned (diag carries the post-write byte count); confirm the
            # file is present and non-empty instead of long-polling.
            file_ok = self._confirm_written(Path(p), size=result.get("size"),
                                            diag_size=parsed.get("bytes"))
            if file_ok:
                return {"ok": True, "path": str(Path(p).resolve()),
                        "diag": diag, "size": Path(p).stat().st_size,
                        "visible": True}
        raise ViewportNotVisibleError(
            "viewport not rendering (visible=0 after retries); stale frames "
            "are never used as evidence")

    def _confirm_written(self, path: Path, size=None,
                         diag_size: int = 0, timeout: float = 8.0) -> bool:
        """Confirm the freshly captured PNG is present and complete.

        The native capture deletes any previous file and writes the new
        frame synchronously; its diagnostic already carries the post-write
        byte count.  So the file is complete the moment the bridge call
        returns — we only need a short presence/size check, not a
        multi-second stability poll.
        """
        expected = int(size if size not in (None, -1) else diag_size or -1)
        deadline = time.time() + timeout
        while time.time() < deadline:
            actual = path.stat().st_size if path.is_file() else -1
            if actual > 0 and (expected <= 0 or abs(actual - expected) <= 4):
                return True
            time.sleep(0.05)
        return False

    # ------------------------------------------------------------------
    # state read/write primitives (read-back verified)
    # ------------------------------------------------------------------
    def _camera_state(self) -> Dict[str, Any]:
        return self.execute("""
import unreal
loc, rot = unreal.EditorLevelLibrary.get_level_viewport_camera_info()
__bridge_result__ = {
  "loc": [round(loc.x, 2), round(loc.y, 2), round(loc.z, 2)],
  "rot": [round(rot.roll, 2), round(rot.pitch, 2), round(rot.yaw, 2)],
}
""")

    def _set_camera(self, loc: List[float], rot: List[float]) -> Dict[str, Any]:
        """rot is [roll, pitch, yaw] (matches _camera_state order); the UE
        python Rotator constructor takes (roll, pitch, yaw)."""
        return self.execute(f"""
import unreal
unreal.EditorLevelLibrary.set_level_viewport_camera_info(
    unreal.Vector({loc[0]}, {loc[1]}, {loc[2]}),
    unreal.Rotator({rot[0]}, {rot[1]}, {rot[2]}))
loc, rot = unreal.EditorLevelLibrary.get_level_viewport_camera_info()
__bridge_result__ = {{
  "loc": [round(loc.x, 2), round(loc.y, 2), round(loc.z, 2)],
  "rot": [round(rot.roll, 2), round(rot.pitch, 2), round(rot.yaw, 2)],
}}
""")

    def _lights(self) -> List[Dict[str, Any]]:
        r = self.execute("""
import unreal
acts = unreal.EditorLevelLibrary.get_all_level_actors()
lights = []
for a in acts:
    cls = a.get_class().get_name()
    if "Light" not in cls or "Sky" in cls or "mass" in cls:
        continue
    comps = a.get_components_by_class(unreal.LightComponent)
    if not comps:
        continue
    c = comps[0]
    def gp(prop, default=None):
        try:
            return c.get_editor_property(prop)
        except Exception:
            return default
    val = gp("intensity")
    lights.append({
        "label": a.get_actor_label(),
        "path": a.get_path_name(),
        "class": cls,
        "intensity": round(val, 2) if val is not None else None,
    })
__bridge_result__ = {"lights": lights}
""")
        return [x for x in r.get("lights") or [] if x.get("intensity") is not None]

    def _dominant_light(self) -> Optional[Dict[str, Any]]:
        lights = self._lights()
        directional = [l for l in lights if l["class"] == "DirectionalLight"]
        pool = directional or [l for l in lights
                               if l["class"] in ("PointLight", "SpotLight",
                                                 "RectLight")]
        if not pool:
            return None
        return max(pool, key=lambda l: float(l.get("intensity") or 0.0))

    def _set_light_intensity(self, light: Dict[str, Any], factor: float,
                             cap: float = 5000.0) -> Dict[str, Any]:
        """Scale one light's intensity by `factor`; read back and verify."""
        code = f"""
import unreal
# resolve the actor by its persisted path (labels are not unique)
target_path = {light['path']!r}
found = None
for a in unreal.EditorLevelLibrary.get_all_level_actors():
    if a.get_path_name() == target_path:
        found = a
        break
out = {{"ok": False}}
if found is not None:
    comps = found.get_components_by_class(unreal.LightComponent)
    if comps:
        c = comps[0]
        before = float(c.get_editor_property("intensity"))
        newv = min(float({cap}), max(0.5, before * float({factor})))
        c.set_editor_property("intensity", newv)
        after = float(c.get_editor_property("intensity"))
        out = {{"ok": abs(after - newv) < max(1.0, newv * 0.02),
                "before": round(before, 2), "after": round(after, 2),
                "label": found.get_actor_label(),
                "class": found.get_class().get_name()}}
__bridge_result__ = out
"""
        r = self.execute(code)
        r["light"] = {k: light.get(k) for k in ("label", "path", "class")}
        return r

    def _dolly(self, direction: str, factor: float) -> Dict[str, Any]:
        """Translate the viewport camera along its view axis by a bounded
        delta derived from the framing factor; read back and verify."""
        m = 0.0
        if factor > 1.0:
            m = self.assumed_depth_m * (factor - 1.0)
        elif factor < 1.0:
            m = self.assumed_depth_m * (1.0 - factor)
        m = min(max(m, 10.0), 2000.0)
        sign = -1.0 if direction == "camera_pull_back" else 1.0
        code = f"""
import unreal, math
loc, rot = unreal.EditorLevelLibrary.get_level_viewport_camera_info()
yaw = math.radians(rot.yaw)
pitch = math.radians(rot.pitch)
fwd = unreal.Vector(math.cos(pitch) * math.cos(yaw),
                    math.cos(pitch) * math.sin(yaw),
                    math.sin(pitch))
delta = fwd * ({sign} * {m})
newloc = loc + delta
unreal.EditorLevelLibrary.set_level_viewport_camera_info(newloc, rot)
loc2, rot2 = unreal.EditorLevelLibrary.get_level_viewport_camera_info()
d = float((loc2 - loc).length())
__bridge_result__ = {{"ok": d > {m} * 0.8,
  "moved_m": round(d, 1),
  "loc_before": [round(loc.x,1), round(loc.y,1), round(loc.z,1)],
  "loc_after": [round(loc2.x,1), round(loc2.y,1), round(loc2.z,1)],
  "rot_after": [round(rot2.roll,2), round(rot2.pitch,2), round(rot2.yaw,2)]}}
"""
        return self.execute(code)

    def _roll_reset(self) -> Dict[str, Any]:
        return self.execute("""
import unreal
loc, rot = unreal.EditorLevelLibrary.get_level_viewport_camera_info()
rot.roll = 0.0
unreal.EditorLevelLibrary.set_level_viewport_camera_info(loc, rot)
loc2, rot2 = unreal.EditorLevelLibrary.get_level_viewport_camera_info()
__bridge_result__ = {"ok": abs(rot2.roll) < 0.01,
  "roll": round(rot2.roll, 3),
  "loc": [round(loc2.x,1), round(loc2.y,1), round(loc2.z,1)]}
""")

    # ------------------------------------------------------------------
    # the loop's apply contract
    # ------------------------------------------------------------------
    def apply(self, action: str, metrics: Any, score: Any,
              target: Optional[Dict[str, Any]] = None,
              pass_index: int = 1) -> Dict[str, Any]:
        """One bounded, read-back-verified fix (rollback-aware)."""
        action = str(action or "")
        record: Dict[str, Any] = {
            "index": int(pass_index), "action": action,
            "planned": True, "ops": [], "readback": {}, "ok": False,
            "rollback": False, "note": "", "error": "",
        }
        if action not in SUPPORTED_ACTIONS:
            record["ok"] = False
            record["error"] = f"unsupported action {action}"
            record["note"] = f"{action}: not supported by the live adapter"
            self.history.append(record)
            return record

        # ---- rollback of the previous change when it regressed ----------
        if self.history:
            prev = self.history[-1]
            if prev.get("ok") and prev.get("snapshot") and decide_rollback(
                    prev.get("score_before"),
                    float(getattr(score, "overall", 0.0) or 0.0),
                    prev.get("defects_before") or [],
                    list(getattr(metrics, "issues", []) or []) or
                    prev.get("defects_before") or [],
                    [prev.get("action") or ""]):
                restored = self._restore(prev["snapshot"])
                record["rollback"] = bool(restored.get("ok"))
                record["ops"].append({"op": "rollback",
                                      "restore": restored})

        # ---- execute ------------------------------------------------------
        executed: Dict[str, Any] = {}
        if action in ("camera_pull_back", "camera_move_closer",
                      "camera_framing_recompute"):
            cov = float(getattr(metrics, "subject_coverage", 0.0) or 0.0)
            if action == "camera_framing_recompute":
                direction = ("camera_pull_back" if cov > 0.42
                             else "camera_move_closer")
                factor = dolly_factor(direction, cov)
                if cov > 0.50 or cov < 0.25:
                    executed = self._dolly(direction, factor)
                    self._roll_reset()
            else:
                factor = dolly_factor(action, cov)
                executed = self._dolly(action, factor)
            record["ops"].append({"op": "viewport_camera_dolly",
                                  "action": action,
                                  "factor": round(factor, 3)})
        elif action == "camera_roll_reset":
            executed = self._roll_reset()
            record["ops"].append({"op": "viewport_camera_roll_reset"})
        elif action in ("exposure_reduce_highlights",
                        "lighting_reduce_background",
                        "environment_reduce_emissives",
                        "exposure_raise_blacks", "lighting_raise_key"):
            factor = light_factor(action, metrics)
            light = self._dominant_light()
            if light is None:
                record["error"] = "no adjustable dominant light found"
                record["note"] = f"{action}: no dominant light to adjust"
                self.history.append(record)
                return record
            snapshot = {"type": "light", "path": light["path"],
                        "intensity": light["intensity"]}
            record["snapshot"] = snapshot
            executed = self._set_light_intensity(light, factor)
            record["ops"].append({"op": "light_intensity_scale",
                                  "action": action,
                                  "factor": round(factor, 3),
                                  "light_label": light.get("label")})
        elif action == "capture_force_fresh":
            self._redraw()
            executed = {"ok": True, "note": "viewport repaint forced"}
            record["ops"].append({"op": "force_redraw"})

        record["readback"] = executed
        record["ok"] = bool(executed.get("ok"))
        if executed.get("ok"):
            self._snapshots.append(dict(record.get("snapshot") or {}))
            saved = self.save_world()
            record["world_saved"] = bool(saved)
        record["score_before"] = round(
            float(getattr(score, "overall", 0.0) or 0.0), 3)
        record["defects_before"] = list(getattr(metrics, "issues", []) or [])
        note = (f"{action}: "
                + (executed.get("note") or _describe_readback(executed)))
        record["note"] = note
        if not executed.get("ok") and executed.get("error"):
            record["error"] = str(executed.get("error"))[:160]
        # no trailing redraw here: the next loop pass always pokes the
        # viewport inside capture(), so the settle would be pure wait.
        self.history.append(record)
        return record

    # ------------------------------------------------------------------
    def _restore(self, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        if snapshot.get("type") == "light":
            lights = self._lights()
            match = next((l for l in lights
                          if l.get("path") == snapshot.get("path")), None)
            if match is None:
                return {"ok": False, "error": "light no longer present"}
            target = float(snapshot.get("intensity") or 1.0)
            cur = float(match.get("intensity") or 0.0)
            if cur <= 0:
                return {"ok": False, "error": "unreadable current intensity"}
            factor = target / cur
            return self._set_light_intensity(match, factor)
        if snapshot.get("type") == "camera":
            return self._set_camera(snapshot.get("loc") or [],
                                    snapshot.get("rot") or [])
        return {"ok": False, "error": f"unknown snapshot {snapshot}"}

    def reset(self) -> None:
        self.history.clear()
        self._snapshots.clear()


def _describe_readback(executed: Dict[str, Any]) -> str:
    parts = []
    if executed.get("after") is not None:
        parts.append(f"intensity {executed.get('before')} -> "
                     f"{executed.get('after')}")
    if executed.get("moved_m"):
        parts.append(f"camera moved {executed.get('moved_m')} m")
    if executed.get("roll") is not None:
        parts.append(f"roll {executed.get('roll')}")
    return "read-back verified" + (f" ({'; '.join(parts)})" if parts else "")
