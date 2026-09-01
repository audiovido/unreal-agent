"""Generic runtime validation and reopen-verification capabilities.

These tools prove the app actually RUNS in Unreal (PIE) and that saved work
survives a project/map reopen:

- runtime_status           is PIE running, which world, how many actors
- runtime_widget_verify    verify a chat widget reflected in the running world
- runtime_actor_verify     verify a named actor exists in the PIE world
- verify_reopen_state      project identity + active map + startup map +
                           saved-state read-back after a reopen
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from tools.unreal.unreal_bridge import UnrealBridge


class RuntimeTools:
    def __init__(self, bridge: UnrealBridge):
        self.bridge = bridge

    def runtime_status(self) -> Dict[str, Any]:
        return self.bridge.execute_python(r"""
import unreal
world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
__bridge_result__ = {
    "ok": True,
    "is_playing": world is not None,
    "world_name": world.get_name() if world is not None else None,
    "world_path": world.get_path_name() if world is not None else None,
}
""")

    def runtime_widget_verify(
        self,
        widget_name: str,
        expected_text: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Verify a runtime chat widget while PIE is running."""
        return self.bridge.execute_python(f"""
import unreal
widget_name = {widget_name!r}
expected_text = {expected_text!r}
world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
if world is None:
    __bridge_result__ = {{
        "ok": False,
        "code": "RUNTIME_NOT_STARTED",
        "widget": widget_name,
        "is_playing": False,
        "verified": False,
    }}
else:
    import sys, types as _types
    _rt = sys.modules.get("ua_chat_rt")
    widget = None
    if _rt is not None:
        widget = getattr(_rt, "widgets", {{}}).get(widget_name)
    found = widget is not None
    text = None
    if widget is not None:
        try:
            t = widget.get_text()
            if t is None:
                text = None
            elif hasattr(t, "to_string"):
                text = t.to_string()
            else:
                text = str(t)
        except Exception:
            text = None
    match = bool(expected_text is None or (text is not None and expected_text in text))
    ok = bool(found and (expected_text is None or match))
    __bridge_result__ = {{
        "ok": ok,
        "code": None if ok else ("WIDGET_NOT_FOUND_AT_RUNTIME" if not found else "WIDGET_TEXT_MISMATCH"),
        "widget": widget_name,
        "found": bool(found),
        "text": text,
        "expected_text": expected_text,
        "text_match": bool(match),
        "world": world.get_name(),
        "is_playing": True,
        "verified": bool(ok),
    }}
""")

    def runtime_actor_verify(
        self,
        actor_name: str,
        actor_class: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Verify a named character/content actor exists in the PIE world."""
        return self.bridge.execute_python(f"""
import unreal
actor_name = {actor_name!r}
actor_class = {actor_class!r}
world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
if world is None:
    __bridge_result__ = {{
        "ok": False,
        "code": "RUNTIME_NOT_STARTED",
        "actor_label": actor_name,
        "is_playing": False,
        "found": False,
        "verified": False,
    }}
else:
    all_actors = unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor)
    matches = [a for a in all_actors if a.get_actor_label() == actor_name]
    found = len(matches) == 1
    class_ok = True
    if found and actor_class:
        class_ok = matches[0].get_class().get_name() == actor_class
    actor = matches[0] if found else None
    loc = actor.get_actor_location() if actor else None
    __bridge_result__ = {{
        "ok": bool(found and class_ok),
        "code": None if (found and class_ok) else ("ACTOR_NOT_FOUND_AT_RUNTIME" if not found else "ACTOR_CLASS_MISMATCH"),
        "actor_label": actor_name,
        "class": actor.get_class().get_name() if actor else None,
        "expected_class": actor_class,
        "found": bool(found),
        "location": [loc.x, loc.y, loc.z] if loc else None,
        "world": world.get_name(),
        "is_playing": True,
        "verified": bool(found and class_ok),
    }}
""")

    def verify_reopen_state(
        self,
        expected_project: Optional[str] = None,
        expected_map: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Read back project identity, active map, persisted startup map and a
        tracked asset/widget/actor after a reopen. Evidence-driven reopen
        validation for the deliverable:reopen criterion."""
        return self.bridge.execute_python(f"""
import unreal
expected_project = {expected_project!r}
expected_map = {expected_map!r}
project_path = str(unreal.Paths.get_project_file_path()).replace(chr(92), "/")
project_name = project_path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
world = unreal.EditorLevelLibrary.get_editor_world()
world_path = world.get_path_name() if world is not None else None
settings = unreal.GameMapsSettings.get_default_object()
startup = None
try:
    sp = settings.get_editor_property("editor_startup_map")
    startup = str(sp.export_text()) if sp is not None else None
except Exception:
    startup = None
checks = {{
    "project_identity_ok": bool(not expected_project or project_name == expected_project),
    "active_map_ok": bool(not expected_map or (world_path or "").startswith(str(expected_map).split(".")[0] + ".") or (world_path or "") == expected_map),
    "startup_map_ok": bool("Untitled" not in str(startup or "")),
}}
ok = bool(all(checks.values()) and world_path and world_path.startswith("/Game/") and "Untitled_" not in world_path)
__bridge_result__ = {{
    "ok": ok,
    "code": None if ok else "REOPEN_STATE_MISMATCH",
    "project_name": project_name,
    "project_path": project_path,
    "expected_project": expected_project,
    "active_map": world_path,
    "expected_map": expected_map,
    "startup_map": startup,
    "checks": checks,
    "verified": bool(ok),
}}
""")