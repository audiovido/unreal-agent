"""scene_verification.py — REAL read-only scene verification for explicit
user requirements.

Registered tool `verify_scene` executes one deterministic, READ-ONLY editor
query per explicit requirement:

  map                        active level matches the expected map
  bridge                     live editor bridge is healthy
  count_prefix               exact actor count by label/name prefix
  movable_lights             exact count of movable light actors
  missing_skeletal_meshes    no character actor is missing a skeletal mesh
  missing_prop_references    no prop actor has a null mesh or null material slot

Every query measures the live editor through the existing bridge and returns
{ok, measured, expected, detail, ...}. Nothing in this module mutates world,
asset, project or editor state — it only reads the editor. Check failure is a
truthful ok=False with the measured value, never a fabricated pass.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

# Default target prefixes for the certified AividoHQ scene. Deterministic
# defaults; callers may override with an explicit target.
DEFAULT_HUMAN_PREFIX = "AVIDO_Human"
DEFAULT_PROP_PREFIX = "W3I_"

SUPPORTED_CHECKS = (
    "map", "bridge", "count_prefix", "movable_lights",
    "missing_skeletal_meshes", "missing_prop_references",
)

# ---------------------------------------------------------------------------
# Editor scripts (pure reads; never mutate). Values are injected with repr().
# ---------------------------------------------------------------------------

_MAP_SCRIPT = r"""
import unreal
world = unreal.EditorLevelLibrary.get_editor_world()
__bridge_result__ = {
    "ok": True,
    "measured": world.get_name() if world else None,
    "path": world.get_path_name() if world else None,
}
"""

_COUNT_PREFIX_SCRIPT = r"""
import unreal
prefix = __prefix__
actors = unreal.EditorLevelLibrary.get_all_level_actors()
matches = []
for a in actors:
    label = a.get_actor_label() or ""
    name = a.get_name() or ""
    if label.startswith(prefix) or name.startswith(prefix):
        matches.append(label or name)
__bridge_result__ = {
    "ok": True,
    "measured": len(matches),
    "actors": sorted(matches),
    "target": prefix,
}
"""

_MOVABLE_LIGHTS_SCRIPT = r"""
import unreal
actors = unreal.EditorLevelLibrary.get_all_level_actors()
movable = []
static = []
stationary = []
unclassified = []
for a in actors:
    label = a.get_actor_label() or a.get_name()
    light_comp = None
    for c in a.get_components_by_class(unreal.SceneComponent):
        cn = c.get_class().get_name()
        if cn.endswith("LightComponent") or cn in ("PointLightComponent",
                                                   "SpotLightComponent",
                                                   "RectLightComponent",
                                                   "DirectionalLightComponent",
                                                   "SkyLightComponent",
                                                   "LocalLightComponent"):
            light_comp = c
            break
    if light_comp is None:
        continue
    mob = None
    try:
        mob = light_comp.mobility
    except Exception:
        try:
            mob = light_comp.get_editor_property("mobility")
        except Exception:
            mob = None
    if mob == unreal.ComponentMobility.MOVABLE:
        movable.append(label)
    elif mob == unreal.ComponentMobility.STATIC:
        static.append(label)
    elif mob == unreal.ComponentMobility.STATIONARY:
        stationary.append(label)
    else:
        unclassified.append(label)
__bridge_result__ = {
    "ok": True,
    "measured": len(movable),
    "movable": sorted(movable),
    "static": sorted(static),
    "stationary": sorted(stationary),
    "unclassified": sorted(unclassified),
}
"""

_MISSING_SKELETAL_SCRIPT = r"""
import unreal
prefix = __prefix__
actors = unreal.EditorLevelLibrary.get_all_level_actors()
missing = []
checked = []
for a in actors:
    label = a.get_actor_label() or a.get_name()
    if not (label.startswith(prefix) or a.get_name().startswith(prefix)):
        continue
    checked.append(label)
    comps = a.get_components_by_class(unreal.SkeletalMeshComponent)
    if not comps:
        missing.append(label + " (no SkeletalMeshComponent)")
        continue
    for c in comps:
        sm = None
        try:
            sm = c.skeletal_mesh
        except Exception:
            try:
                sm = c.get_editor_property("skeletal_mesh")
            except Exception:
                sm = None
        if sm is None:
            missing.append(label + " (null skeletal mesh)")
            break
__bridge_result__ = {
    "ok": True,
    "measured": len(missing),
    "missing": missing,
    "checked": sorted(checked),
    "target": prefix,
}
"""

_MISSING_PROP_SCRIPT = r"""
import unreal
prefix = __prefix__
actors = unreal.EditorLevelLibrary.get_all_level_actors()
missing = []
checked = []
for a in actors:
    label = a.get_actor_label() or a.get_name()
    if not (label.startswith(prefix) or a.get_name().startswith(prefix)):
        continue
    checked.append(label)
    comps = a.get_components_by_class(unreal.StaticMeshComponent)
    if not comps:
        missing.append(label + " (no StaticMeshComponent)")
        continue
    for c in comps:
        sm = None
        try:
            sm = c.static_mesh
        except Exception:
            try:
                sm = c.get_editor_property("static_mesh")
            except Exception:
                sm = None
        if sm is None:
            missing.append(label + " (null static mesh)")
            break
        bad = False
        for i in range(c.get_num_materials()):
            mat = None
            try:
                mat = c.get_material(i)
            except Exception:
                mat = None
            if mat is None:
                missing.append(label + f" (null material slot {i})")
                bad = True
                break
        if bad:
            break
__bridge_result__ = {
    "ok": True,
    "measured": len(missing),
    "missing": missing,
    "checked": sorted(checked),
    "target": prefix,
}
"""


class SceneVerification:
    """Binds one registered read-only tool to the live editor bridge."""

    def __init__(self, bridge):
        self.bridge = bridge

    # -- dispatch ---------------------------------------------------------
    def verify(self, check: Optional[str] = None,
               expected: Any = None, target: Optional[str] = None,
               **kwargs) -> Dict[str, Any]:
        """Run one deterministic read-only editor query.

        Returns a flat payload: {ok, check, measured, expected, detail, ...}.
        ok=False is truthful (measured != expected, bridge error, or
        unsupported check) — never a fabricated pass.
        """
        check = str(check or "")
        # The planner emits kind "count" for an exact-count check; the tool's
        # canonical check name is count_prefix. Accept both.
        if check == "count":
            check = "count_prefix"
        try:
            if check == "bridge":
                return self._check_bridge()
            if check == "map":
                return self._check_map(expected)
            if check == "count_prefix":
                return self._check_count_prefix(expected, target)
            if check == "movable_lights":
                return self._check_movable_lights(expected)
            if check == "missing_skeletal_meshes":
                return self._check_missing_skeletal(
                    expected, target or DEFAULT_HUMAN_PREFIX)
            if check == "missing_prop_references":
                return self._check_missing_prop(
                    expected, target or DEFAULT_PROP_PREFIX)
            if check == "proof":
                return {
                    "ok": False, "check": check,
                    "error": ("proof is planned as an EVIDENCE capture step "
                              "(capture_unreal_viewport), not a verify_scene "
                              "query"),
                }
            return {"ok": False, "check": check,
                    "error": f"unsupported verification check: {check}"}
        except Exception as exc:  # pragma: no cover - defensive truthfulness
            return {"ok": False, "check": check,
                    "error": f"{type(exc).__name__}: {exc}"}

    # -- internals ---------------------------------------------------------
    def _unpack(self, raw: Any) -> Dict[str, Any]:
        """Unwrap the bridge envelope: {ok, result: {...}} -> inner dict."""
        if not isinstance(raw, dict):
            return {"ok": False, "error": f"bridge returned {type(raw).__name__}"}
        inner = raw.get("result")
        if isinstance(inner, dict):
            return inner
        return dict(raw)

    def _script(self, template: str, **bindings: Any) -> str:
        out = template
        for key, value in bindings.items():
            out = out.replace(f"__{key}__", repr(value))
        return out

    def _check_bridge(self) -> Dict[str, Any]:
        raw = self.bridge.ping()
        info = self._unpack(raw)
        ok = bool(info.get("ok")) or (
            raw.get("ok") is True and not info.get("error"))
        return {
            "ok": ok, "check": "bridge",
            "measured": "healthy" if ok else "unhealthy",
            "expected": "healthy",
            "detail": str(info.get("error") or info.get("message")
                          or "bridge ping ok")[:400],
        }

    def _check_map(self, expected: Any) -> Dict[str, Any]:
        raw = self.bridge.execute_python(_MAP_SCRIPT)
        info = self._unpack(raw)
        if not info.get("ok"):
            return {"ok": False, "check": "map",
                    "error": str(info.get("error") or raw)[:400]}
        name = str(info.get("measured") or "")
        path = str(info.get("path") or "")
        want = str(expected or "").strip().lower().lstrip("/")
        measured = name or path
        ok = bool(want) and (
            want in path.lower() or name.lower() == want
            or path.lower().endswith("." + want)
        )
        return {
            "ok": ok, "check": "map", "measured": measured,
            "expected": str(expected or ""), "path": path,
            "detail": (f"active world {path!r} matches expected "
                       f"{expected!r}" if ok else
                       f"active world {path!r} does not match {expected!r}"),
        }

    def _check_count_prefix(self, expected: Any,
                            target: Optional[str]) -> Dict[str, Any]:
        target = str(target or "").strip()
        if not target:
            return {"ok": False, "check": "count_prefix",
                    "error": "count_prefix check requires an actor target prefix"}
        raw = self.bridge.execute_python(
            self._script(_COUNT_PREFIX_SCRIPT, prefix=target))
        info = self._unpack(raw)
        if not info.get("ok"):
            return {"ok": False, "check": "count_prefix",
                    "error": str(info.get("error") or raw)[:400]}
        measured = int(info.get("measured") or 0)
        want = int(expected) if isinstance(expected, int) else (
            int(expected) if str(expected).lstrip("-").isdigit() else None)
        if want is None:
            return {"ok": False, "check": "count_prefix",
                    "error": "count_prefix check requires an integer expected count",
                    "measured": measured, "target": target}
        return {
            "ok": measured == want, "check": "count_prefix",
            "measured": measured, "expected": want, "target": target,
            "actors": info.get("actors") or [],
            "detail": (f"{measured} actors match prefix {target!r} "
                       f"(expected {want})"),
        }

    def _check_movable_lights(self, expected: Any) -> Dict[str, Any]:
        raw = self.bridge.execute_python(_MOVABLE_LIGHTS_SCRIPT)
        info = self._unpack(raw)
        if not info.get("ok"):
            return {"ok": False, "check": "movable_lights",
                    "error": str(info.get("error") or raw)[:400]}
        measured = int(info.get("measured") or 0)
        want = int(expected) if isinstance(expected, int) else (
            int(expected) if str(expected).lstrip("-").isdigit() else None)
        if want is None:
            return {"ok": False, "check": "movable_lights",
                    "error": "movable_lights check requires an integer expected count",
                    "measured": measured}
        return {
            "ok": measured == want, "check": "movable_lights",
            "measured": measured, "expected": want,
            "movable": info.get("movable") or [],
            "static": info.get("static") or [],
            "stationary": info.get("stationary") or [],
            "detail": (f"{measured} movable light actors (expected {want}); "
                       f"static={len(info.get('static') or [])}, "
                       f"stationary={len(info.get('stationary') or [])}, "
                       f"unclassified={len(info.get('unclassified') or [])}"),
        }

    def _check_missing_skeletal(self, expected: Any,
                                target: str) -> Dict[str, Any]:
        raw = self.bridge.execute_python(
            self._script(_MISSING_SKELETAL_SCRIPT, prefix=target))
        info = self._unpack(raw)
        if not info.get("ok"):
            return {"ok": False, "check": "missing_skeletal_meshes",
                    "error": str(info.get("error") or raw)[:400]}
        measured = int(info.get("measured") or 0)
        want = int(expected) if isinstance(expected, int) else (
            int(expected) if str(expected).lstrip("-").isdigit() else 0)
        return {
            "ok": measured == want, "check": "missing_skeletal_meshes",
            "measured": measured, "expected": want, "target": target,
            "missing": info.get("missing") or [],
            "checked": info.get("checked") or [],
            "detail": (f"{measured} character actor(s) missing a skeletal "
                       f"mesh among {len(info.get('checked') or [])} checked "
                       f"(expected {want})"),
        }

    def _check_missing_prop(self, expected: Any,
                            target: str) -> Dict[str, Any]:
        raw = self.bridge.execute_python(
            self._script(_MISSING_PROP_SCRIPT, prefix=target))
        info = self._unpack(raw)
        if not info.get("ok"):
            return {"ok": False, "check": "missing_prop_references",
                    "error": str(info.get("error") or raw)[:400]}
        measured = int(info.get("measured") or 0)
        want = int(expected) if isinstance(expected, int) else (
            int(expected) if str(expected).lstrip("-").isdigit() else 0)
        return {
            "ok": measured == want, "check": "missing_prop_references",
            "measured": measured, "expected": want, "target": target,
            "missing": info.get("missing") or [],
            "checked": info.get("checked") or [],
            "detail": (f"{measured} prop actor(s) with null mesh/material "
                       f"among {len(info.get('checked') or [])} checked "
                       f"(expected {want})"),
        }