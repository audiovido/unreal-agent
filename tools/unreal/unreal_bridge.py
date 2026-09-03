import json
import socket
import os
import base64
import requests
import re

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 6766
PROJECT_TARGETS = {
    "avalive": ("127.0.0.1", 6766, r"C:/Users/Shadow/Desktop/AvaLive/AvaLive/AvaLive.uproject"),
    "audiovido": ("127.0.0.1", 6767, r"C:/Users/Shadow/Desktop/app/AudioVidoLivingCity/AudioVidoLivingCity.uproject"),
}


def verify_startup_map_result(result):
    """Validate persisted startup-map evidence independently of transport."""
    if not isinstance(result, dict):
        return False
    payload = result.get("result") if isinstance(result.get("result"), dict) else result
    path = str(payload.get("startup_map") or "")
    return bool(payload.get("config_verified") is True and path.startswith("/Game/") and "/Temp/Untitled_" not in path)


def verify_save_result(result):
    """Validate the structured save contract independently of transport."""
    if not isinstance(result, dict):
        return False
    payload = result.get("result") if isinstance(result.get("result"), dict) else result
    return bool(
        payload.get("package_exists") is True
        and payload.get("dirty_after") is False
        and payload.get("verified") is True
        and str(payload.get("map_after") or payload.get("active_map") or "").startswith("/Game/")
        and "/Temp/Untitled_" not in str(payload.get("map_after") or payload.get("active_map") or "")
    )


class UnrealBridge:
    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT, timeout=30, target=None):
        if target is not None:
            if target not in PROJECT_TARGETS:
                raise ValueError(f"Unknown Unreal project target: {target}")
            host, port, self.expected_project = PROJECT_TARGETS[target]
            self.target = target
        else:
            self.expected_project = None
            self.target = None
        self.host = host
        self.port = port
        self.timeout = timeout

    def ping(self):
        return self._send({"type": "ping"})

    def execute_python(self, code: str, *, expected_project=None):
        expected = expected_project or self.expected_project
        return self._send({"type": "python", "code": code, "expected_project": expected})

    def get_identity(self):
        return self._send({"type": "identity"})

    def start_pie(self):
        return self.execute_python(r"""
level_subsystem = unreal.get_editor_subsystem(
    unreal.LevelEditorSubsystem
)
editor_subsystem = unreal.get_editor_subsystem(
    unreal.UnrealEditorSubsystem
)

game_world = editor_subsystem.get_game_world()

if game_world is not None:
    __bridge_result__ = {
        "ok": True,
        "requested": False,
        "already_running": True,
        "world_name": game_world.get_name(),
        "world_path": game_world.get_path_name()
    }
else:
    level_subsystem.editor_request_begin_play()

    __bridge_result__ = {
        "ok": True,
        "requested": True,
        "already_running": False,
        "message": "PIE begin-play requested"
    }
""")

    def stop_pie(self):
        return self.execute_python(r"""
level_subsystem = unreal.get_editor_subsystem(
    unreal.LevelEditorSubsystem
)
editor_subsystem = unreal.get_editor_subsystem(
    unreal.UnrealEditorSubsystem
)

game_world = editor_subsystem.get_game_world()

if game_world is None:
    __bridge_result__ = {
        "ok": True,
        "requested": False,
        "already_stopped": True
    }
else:
    world_name = game_world.get_name()
    level_subsystem.editor_request_end_play()

    __bridge_result__ = {
        "ok": True,
        "requested": True,
        "already_stopped": False,
        "previous_world_name": world_name,
        "message": "PIE end-play requested"
    }
""")

    def get_pie_status(self):
        return self.execute_python(r"""
editor_subsystem = unreal.get_editor_subsystem(
    unreal.UnrealEditorSubsystem
)

game_world = editor_subsystem.get_game_world()

__bridge_result__ = {
    "ok": True,
    "is_playing": game_world is not None,
    "world_name": game_world.get_name() if game_world else None,
    "world_path": game_world.get_path_name() if game_world else None
}
""")

    def capture_pie_viewport(self):
        return self.execute_python(r"""
import os

editor_subsystem = unreal.get_editor_subsystem(
    unreal.UnrealEditorSubsystem
)

game_world = editor_subsystem.get_game_world()

if game_world is None:
    __bridge_result__ = {
        "ok": False,
        "error": "PIE is not running"
    }
else:
    saved_dir = unreal.Paths.convert_relative_path_to_full(
        unreal.Paths.project_saved_dir()
    )

    out_dir = os.path.join(saved_dir, "UnrealAgent")
    os.makedirs(out_dir, exist_ok=True)

    path = os.path.join(
        out_dir,
        "pie_viewport_latest.png"
    )

    diagnostic = (
        unreal.UnrealAgentBlueprintLibrary
        .capture_active_viewport_detailed(path)
    )

    diagnostic = str(diagnostic)

    exists = os.path.isfile(path)
    size = os.path.getsize(path) if exists else 0

    ok = (
        diagnostic.startswith("OK|")
        and "source=GameViewport" in diagnostic
        and exists
        and size > 0
    )

    __bridge_result__ = {
        "ok": bool(ok),
        "path": path.replace("\\", "/"),
        "size": size,
        "world_name": game_world.get_name(),
        "diagnostic": diagnostic,
        "source_is_game_viewport": (
            "source=GameViewport" in diagnostic
        ),
        "error": None if ok else (
            "Native capture did not verify GameViewport output"
        )
    }
""")

    def capture_unreal_viewport(self):
        result = self.execute_python(r"""
import os

saved_dir = unreal.Paths.convert_relative_path_to_full(
    unreal.Paths.project_saved_dir()
)

out_dir = os.path.join(
    saved_dir,
    "UnrealAgent"
)

os.makedirs(out_dir, exist_ok=True)

path = os.path.join(
    out_dir,
    "viewport_latest.png"
)

try:
    if os.path.isfile(path):
        os.remove(path)
except Exception:
    pass

if hasattr(unreal, "UnrealAgentBlueprintLibrary"):
    diagnostic = str(
        unreal.UnrealAgentBlueprintLibrary
        .capture_active_viewport_detailed(path)
    )
    capture_source = "NativeEditorViewport"
    capture_requested = False
    ok = diagnostic.startswith("OK|")
else:
    # A newly created project may not yet have the optional native bridge
    # module loaded. UE 5.8's built-in editor automation still captures the
    # real active editor viewport and completes asynchronously.
    task = unreal.AutomationLibrary.take_high_res_screenshot(
        1280,
        720,
        path,
        None,
        False,
        False,
        force_game_view=False,
    )
    diagnostic = "OK|source=EditorAutomation|task=" + str(task)
    capture_source = "EditorAutomation"
    capture_requested = True
    ok = False

size = os.path.getsize(path) if os.path.isfile(path) else 0
__bridge_result__ = {
    "ok": bool(ok),
    "path": path.replace(chr(92), "/"),
    "size": size,
    "diagnostic": diagnostic,
    "capture_source": capture_source,
    "capture_requested": capture_requested,
}
""")

        if not isinstance(result, dict):
            return result

        info = result.get("result")
        if not isinstance(info, dict) or not info.get("capture_requested"):
            return result

        path = info.get("path")
        if not path:
            return result

        deadline = __import__("time").time() + 45
        while __import__("time").time() < deadline:
            if os.path.isfile(path):
                info["ok"] = os.path.getsize(path) > 0
                info["size"] = os.path.getsize(path)
                info["capture_requested"] = False
                return result
            __import__("time").sleep(1)

        return result

    def visual_review_unreal(self):
        capture = self.capture_unreal_viewport()

        if not isinstance(capture, dict) or not capture.get("ok"):
            return {
                "ok": False,
                "error": "Native viewport capture bridge call failed.",
                "capture": capture
            }

        info = capture.get("result") or {}

        if not info.get("ok"):
            return {
                "ok": False,
                "error": "Native viewport capture failed inside Unreal.",
                "capture": capture
            }

        path = info.get("path")

        if not path or not os.path.isfile(path):
            return {
                "ok": False,
                "error": "Native viewport screenshot file was not found.",
                "path": path,
                "capture": capture
            }

        with open(path, "rb") as f:
            image_b64 = base64.b64encode(
                f.read()
            ).decode("ascii")

        model = os.getenv(
            "UNREAL_AGENT_VISION_MODEL",
            "qwen3-vl:8b-instruct"
        )

        prompt = """
You are the visual QA director for an autonomous Unreal Engine 5.8 production agent.

Review ONLY what is visible in this Unreal viewport screenshot.

Evaluate:
- composition and hierarchy
- lighting and readability
- scale and proportion
- materials and visible defects
- environment/level presentation
- UI/UX quality when interface elements are visible
- clipping, overlap, broken layout, unfinished presentation

Return JSON only:
{
  "pass": false,
  "score": 0,
  "capture_quality": "good",
  "summary": "short summary",
  "critical_issues": ["..."],
  "issues": [
    {
      "priority": "high",
      "problem": "...",
      "fix": "..."
    }
  ],
  "next_action": "..."
}

Rules:
- pass=true only when there is no critical visible problem.
- score 8 or higher means production-ready enough for this iteration.
- If the image is unusable, use capture_quality="bad".
- Every issue must have an actionable Unreal fix.
- Never invent hidden project state.
"""

        body = {
            "model": model,
            "stream": False,
            "options": {
                "temperature": 0
            },
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                    "images": [image_b64]
                }
            ]
        }

        try:
            response = requests.post(
                os.getenv(
                    "UNREAL_AGENT_OLLAMA_URL",
                    "http://127.0.0.1:11434/api/chat"
                ),
                json=body,
                timeout=600
            )

            response.raise_for_status()

            content = (
                response.json()
                .get("message", {})
                .get("content", "")
            )

            content = str(content).strip()

            try:
                review = json.loads(content)
            except Exception:
                cleaned = content

                if cleaned.startswith("```"):
                    cleaned = re.sub(
                        r"^```(?:json)?\s*",
                        "",
                        cleaned,
                        count=1,
                        flags=re.IGNORECASE,
                    )
                    cleaned = re.sub(
                        r"\s*```$",
                        "",
                        cleaned,
                        count=1,
                    )

                start = cleaned.find("{")
                end = cleaned.rfind("}")

                if start >= 0 and end > start:
                    cleaned = cleaned[start:end + 1]

                review = json.loads(cleaned)

            return {
                "ok": True,
                "model": model,
                "screenshot": path,
                "pass": bool(review.get("pass", False)),
                "score": review.get("score"),
                "capture_quality": review.get(
                    "capture_quality",
                    "unknown"
                ),
                "summary": review.get("summary", ""),
                "critical_issues": review.get(
                    "critical_issues",
                    []
                ),
                "issues": review.get("issues", []),
                "next_action": review.get(
                    "next_action",
                    ""
                )
            }

        except Exception as exc:
            return {
                "ok": False,
                "model": model,
                "screenshot": path,
                "error": (
                    type(exc).__name__
                    + ": "
                    + str(exc)
                )
            }

    def get_selected_actors(self):
        return self.execute_python(r'''
actors = unreal.EditorLevelLibrary.get_selected_level_actors()

__bridge_result__ = [
    {
        "name": actor.get_name(),
        "label": actor.get_actor_label(),
        "class": actor.get_class().get_name()
    }
    for actor in actors
]
''')

    def list_level_actors(self):
        return self.execute_python(r'''
actors = unreal.EditorLevelLibrary.get_all_level_actors()

__bridge_result__ = [
    {
        "name": actor.get_name(),
        "label": actor.get_actor_label(),
        "class": actor.get_class().get_name()
    }
    for actor in actors
]
''')


    def is_level_dirty(self):
        return self.execute_python(r'''
world = unreal.EditorLevelLibrary.get_editor_world()

if world is None:
    __bridge_result__ = {
        "ok": False,
        "error": "No editor world is currently open"
    }
else:
    package = world.get_outermost()

    __bridge_result__ = {
        "ok": True,
        "world_name": world.get_name(),
        "world_path": world.get_path_name(),
        "is_dirty": package in unreal.EditorLoadingAndSavingUtils.get_dirty_map_packages()
    }
''')
    def get_current_level(self):
        return self.execute_python(r'''
world = unreal.EditorLevelLibrary.get_editor_world()

__bridge_result__ = {
    "ok": world is not None,
    "world_name": world.get_name() if world else None,
    "world_path": world.get_path_name() if world else None
}
''')

    def set_startup_map(self, map_path: str):
        """Persist GameMapsSettings startup/editor map and verify it."""
        return self.execute_python(f'''\
import unreal
from pathlib import Path
map_path = {map_path!r}
if not map_path.startswith("/Game/"):
    __bridge_result__ = {{"ok": False, "error": "Startup map must be under /Game/"}}
else:
    project_dir = Path(unreal.SystemLibrary.get_project_directory())
    config_path = project_dir / "Config" / "DefaultEngine.ini"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    text = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    section = "[/Script/EngineSettings.GameMapsSettings]"
    lines = text.splitlines()
    if section not in lines:
        lines.extend(["", section])
    start = lines.index(section)
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("["):
            end = i
            break
    block = [line for line in lines[start + 1:end] if not (line.startswith("GameDefaultMap=") or line.startswith("EditorStartupMap="))]
    block.extend(["GameDefaultMap=" + map_path, "EditorStartupMap=" + map_path])
    lines[start + 1:end] = block
    config_path.write_text("\\n".join(lines) + "\\n", encoding="utf-8")
    # Reload the supported project settings object so the current editor uses
    # the same values persisted for the next editor process.
    settings = unreal.GameMapsSettings.get_default_object()
    soft_map = unreal.SoftObjectPath(map_path)
    settings.set_editor_property("editor_startup_map", soft_map)
    settings.set_editor_property("game_default_map", soft_map)
    __bridge_result__ = {{
        "ok": True,
        "startup_map": map_path,
        "config_path": str(config_path).replace(chr(92), "/"),
        "config_verified": ("EditorStartupMap=" + map_path in config_path.read_text(encoding="utf-8")),
    }}
''')

    def get_project_identity(self):
        return self.execute_python(r'''
project_path = str(unreal.Paths.get_project_file_path()).replace(chr(92), "/")
project_name = project_path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
__bridge_result__ = {
    "ok": bool(project_path),
    "project_path": project_path,
    "project_name": project_name,
    "engine": unreal.SystemLibrary.get_engine_version(),
}
''')

    def open_map(self, level_path=None):
        """Reopen a real /Game map through the correct UE 5.8 API
        (LevelEditorSubsystem.load_level) and verify identity + startup map.

        With no level_path, reopens the project's persisted EditorStartupMap so
        a "reopen" task proves the saved map + startup config survive a reload.
        """
        previous_timeout = self.timeout
        self.timeout = max(self.timeout, 120)
        try:
            return self.execute_python(f'''\
import unreal
level_path = {level_path!r}
subsystem = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
if not level_path or not level_path.startswith("/Game/"):
    settings = unreal.GameMapsSettings.get_default_object()
    sp = settings.get_editor_property("editor_startup_map")
    # SoftObjectPath struct: export_text() is the only python-safe conversion.
    level_path = str(sp.export_text()) if sp is not None else None
loaded = False
if level_path:
    loaded = bool(subsystem.load_level(level_path))
world = unreal.EditorLevelLibrary.get_editor_world()
world_path = world.get_path_name() if world else ""
# Compare against the package form (strip any object suffix such as
# "/Game/Maps/X.X:PersistentLevel" or "/Game/Maps/X.X").
level_cmp = level_path.split(".", 1)[0] if level_path and "." in level_path else level_path
identity_ok = bool(loaded and level_cmp and world_path.startswith(level_cmp + "."))
__bridge_result__ = {{
    "ok": identity_ok,
    "level_path": level_path,
    "loaded": bool(loaded),
    "world_path": world_path,
    "identity_ok": identity_ok,
}}
''')
        finally:
            self.timeout = previous_timeout

    def create_default_level(self, level_path: str):
        previous_timeout = self.timeout
        self.timeout = max(self.timeout, 180)
        try:
            return self.execute_python(f'''
level_path = {level_path!r}
subsystem = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
created = bool(subsystem.new_level(level_path))
saved = False
if created:
    saved = bool(subsystem.save_current_level())
__bridge_result__ = {{
    "ok": bool(created and saved),
    "level_path": level_path,
    "created": created,
    "saved": saved,
}}
''')
        finally:
            self.timeout = previous_timeout

    def validate_project_creation(self, project_name: str, actor_name: str):
        return self.execute_python(f'''
project_path = str(unreal.Paths.get_project_file_path()).replace(chr(92), "/")
active_project = project_path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
world = unreal.EditorLevelLibrary.get_editor_world()
actors = unreal.EditorLevelLibrary.get_all_level_actors() if world else []
matches = [a for a in actors if a.get_actor_label() == {actor_name!r}]
actor = matches[0] if len(matches) == 1 else None
mesh = None
if actor is not None and hasattr(actor, "static_mesh_component"):
    mesh = actor.static_mesh_component.get_editor_property("static_mesh")
package = world.get_outermost() if world else None
dirty = bool(package and package in unreal.EditorLoadingAndSavingUtils.get_dirty_map_packages())
checks = {{
    "project_identity": active_project == {project_name!r},
    "project_path": project_path.lower().endswith("/" + {project_name!r}.lower() + ".uproject"),
    "level_loaded": world is not None,
    "actor_exists": actor is not None,
    "visible_mesh_actor": actor is not None and actor.get_class().get_name() == "StaticMeshActor" and mesh is not None,
    "clean_after_save": not dirty,
}}
__bridge_result__ = {{
    "ok": all(checks.values()),
    "project_name": active_project,
    "project_path": project_path,
    "level_path": world.get_path_name() if world else None,
    "actor_name": actor.get_actor_label() if actor else None,
    "actor_class": actor.get_class().get_name() if actor else None,
    "actor_transform": {{
        "location": [actor.get_actor_location().x, actor.get_actor_location().y, actor.get_actor_location().z],
        "rotation": [actor.get_actor_rotation().pitch, actor.get_actor_rotation().yaw, actor.get_actor_rotation().roll],
        "scale": [actor.get_actor_scale3d().x, actor.get_actor_scale3d().y, actor.get_actor_scale3d().z],
    }} if actor else None,
    "mesh_path": mesh.get_path_name() if mesh else None,
    "is_dirty": dirty,
    "checks": checks,
}}
''')

    def list_assets(self, path="/Game", recursive=True):
        return self.execute_python(f"""
assets = unreal.EditorAssetLibrary.list_assets(
    "{path}",
    recursive={str(recursive)},
    include_folder=False
)

assets = [str(x) for x in assets]

__bridge_result__ = {{
    "ok": True,
    "path": "{path}",
    "count": len(assets),
    "assets": assets
}}
""")
    def get_asset_info(self, asset_path: str):
        return self.execute_python(f'''
asset = unreal.load_asset("{asset_path}")

if asset is None:
    __bridge_result__ = {{
        "ok": False,
        "error": "Asset not found: {asset_path}"
    }}
else:
    __bridge_result__ = {{
        "ok": True,
        "path": asset.get_path_name(),
        "name": asset.get_name(),
        "class": asset.get_class().get_name()
    }}
''')
    def get_actor(self, actor_name: str):
        return self.execute_python(f"""
actors = unreal.EditorLevelLibrary.get_all_level_actors()

name_matches = [a for a in actors if a.get_name() == "{actor_name}"]

if len(name_matches) == 1:
    target = name_matches[0]
elif len(name_matches) > 1:
    target = None
    __bridge_result__ = {{
        "ok": False,
        "error": "Multiple actors matched internal name: {actor_name}"
    }}
else:
    label_matches = [a for a in actors if a.get_actor_label() == "{actor_name}"]

    if len(label_matches) == 0:
        target = None
        __bridge_result__ = {{
            "ok": False,
            "error": "Actor not found: {actor_name}"
        }}
    elif len(label_matches) > 1:
        target = None
        __bridge_result__ = {{
            "ok": False,
            "error": "Ambiguous actor label: {actor_name}",
            "matches": [a.get_name() for a in label_matches]
        }}
    else:
        target = label_matches[0]

if target is not None:
    loc = target.get_actor_location()
    rot = target.get_actor_rotation()
    scale = target.get_actor_scale3d()

    __bridge_result__ = {{
        "ok": True,
        "name": target.get_name(),
        "label": target.get_actor_label(),
        "class": target.get_class().get_name(),
        "location": [loc.x, loc.y, loc.z],
        "rotation": [rot.pitch, rot.yaw, rot.roll],
        "scale": [scale.x, scale.y, scale.z]
    }}
""")
    def spawn_actor(self, class_name: str = None, location=None, rotation=None, actor_type: str = None, scale=None, actor_name: str = None, mesh_asset: str = None):
        class_name = class_name or actor_type or "Actor"
        location = location or [0, 0, 0]
        rotation = rotation or [0, 0, 0]
        scale = scale or [1, 1, 1]

        return self.execute_python(f'''
actor_class = getattr(unreal, "{class_name}", None)

if actor_class is None:
    __bridge_result__ = {{
        "ok": False,
        "error": "Unknown Unreal class: {class_name}"
    }}
else:
    subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)

    actor = subsystem.spawn_actor_from_class(
        actor_class,
        unreal.Vector({location[0]}, {location[1]}, {location[2]}),
        unreal.Rotator(pitch={rotation[0]}, yaw={rotation[1]}, roll={rotation[2]})
    )
    mesh_loaded = None
    if actor is not None:
        actor.set_actor_scale3d(unreal.Vector({scale[0]}, {scale[1]}, {scale[2]}))
        if {actor_name!r}:
            actor.set_actor_label({actor_name!r})
        if {mesh_asset!r} and hasattr(actor, "static_mesh_component"):
            mesh = unreal.load_asset({mesh_asset!r})
            mesh_loaded = mesh is not None
            if mesh is not None:
                actor.static_mesh_component.set_static_mesh(mesh)

    __bridge_result__ = {{
        "ok": actor is not None,
        "name": actor.get_name() if actor else None,
        "label": actor.get_actor_label() if actor else None,
        "class": actor.get_class().get_name() if actor else None,
        "mesh_loaded": mesh_loaded,
        "requested_mesh": {mesh_asset!r} or None,
    }}
    if mesh_loaded is False:
        __bridge_result__["warning"] = (
            "Requested mesh asset not found: " + {mesh_asset!r}
        )
''')

    def move_actor(self, actor_name: str, location):
        return self.execute_python(f"""
actors = unreal.EditorLevelLibrary.get_all_level_actors()

name_matches = [a for a in actors if a.get_name() == "{actor_name}"]

if len(name_matches) == 1:
    target = name_matches[0]
elif len(name_matches) > 1:
    target = None
    __bridge_result__ = {{
        "ok": False,
        "error": "Multiple actors matched internal name: {actor_name}"
    }}
else:
    label_matches = [a for a in actors if a.get_actor_label() == "{actor_name}"]

    if len(label_matches) == 0:
        target = None
        __bridge_result__ = {{
            "ok": False,
            "error": "Actor not found: {actor_name}"
        }}
    elif len(label_matches) > 1:
        target = None
        __bridge_result__ = {{
            "ok": False,
            "error": "Ambiguous actor label: {actor_name}",
            "matches": [a.get_name() for a in label_matches]
        }}
    else:
        target = label_matches[0]

if target is not None:
    target.set_actor_location(
        unreal.Vector({location[0]}, {location[1]}, {location[2]}),
        False,
        False
    )

    loc = target.get_actor_location()

    __bridge_result__ = {{
        "ok": True,
        "name": target.get_name(),
        "label": target.get_actor_label(),
        "location": [loc.x, loc.y, loc.z]
    }}
""")
    def rotate_actor(self, actor_name: str, rotation):
        return self.execute_python(f"""
actors = unreal.EditorLevelLibrary.get_all_level_actors()

name_matches = [a for a in actors if a.get_name() == "{actor_name}"]

if len(name_matches) == 1:
    target = name_matches[0]
elif len(name_matches) > 1:
    target = None
    __bridge_result__ = {{
        "ok": False,
        "error": "Multiple actors matched internal name: {actor_name}"
    }}
else:
    label_matches = [a for a in actors if a.get_actor_label() == "{actor_name}"]

    if len(label_matches) == 0:
        target = None
        __bridge_result__ = {{
            "ok": False,
            "error": "Actor not found: {actor_name}"
        }}
    elif len(label_matches) > 1:
        target = None
        __bridge_result__ = {{
            "ok": False,
            "error": "Ambiguous actor label: {actor_name}",
            "matches": [a.get_name() for a in label_matches]
        }}
    else:
        target = label_matches[0]

if target is not None:
    target.set_actor_rotation(
        unreal.Rotator(
            pitch={rotation[0]},
            yaw={rotation[1]},
            roll={rotation[2]}
        ),
        False
    )

    r = target.get_actor_rotation()

    __bridge_result__ = {{
        "ok": True,
        "name": target.get_name(),
        "label": target.get_actor_label(),
        "rotation": [r.pitch, r.yaw, r.roll]
    }}
""")

    def frame_viewport_from_actor(self, actor_name: str, distance: float = 0.0):
        """Aim the active editor viewport from one unambiguous camera actor.

        This intentionally does not guess at arbitrary scene actors: callers
        must supply a mission-owned camera label.  It gives visual acceptance
        evidence a deterministic relationship to the camera it is repairing.
        """
        return self.execute_python(f"""
actors = unreal.EditorLevelLibrary.get_all_level_actors()
matches = [a for a in actors if a.get_name() == {actor_name!r}
           or a.get_actor_label() == {actor_name!r}]
if len(matches) != 1:
    __bridge_result__ = {{
        "ok": False,
        "error": "Camera actor not found or ambiguous: {actor_name}",
        "matches": [a.get_name() for a in matches],
    }}
else:
    camera = matches[0]
    loc = camera.get_actor_location()
    rot = camera.get_actor_rotation()
    # Pulling back along the camera forward vector is bounded and is used
    # only for a framing repair.  It never moves the camera actor itself.
    offset = camera.get_actor_forward_vector() * float({float(distance)!r})
    view_loc = loc - offset
    editor = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    editor.set_level_viewport_camera_info(view_loc, rot)
    readback = editor.get_level_viewport_camera_info()
    __bridge_result__ = {{
        "ok": readback is not None,
        "camera": camera.get_actor_label(),
        "location": [view_loc.x, view_loc.y, view_loc.z],
        "rotation": [rot.pitch, rot.yaw, rot.roll],
        "distance": float({float(distance)!r}),
    }}
""")
    def scale_actor(self, actor_name: str, scale):
        return self.execute_python(f"""
actors = unreal.EditorLevelLibrary.get_all_level_actors()

name_matches = [a for a in actors if a.get_name() == "{actor_name}"]

if len(name_matches) == 1:
    target = name_matches[0]
elif len(name_matches) > 1:
    target = None
    __bridge_result__ = {{
        "ok": False,
        "error": "Multiple actors matched internal name: {actor_name}"
    }}
else:
    label_matches = [a for a in actors if a.get_actor_label() == "{actor_name}"]

    if len(label_matches) == 0:
        target = None
        __bridge_result__ = {{
            "ok": False,
            "error": "Actor not found: {actor_name}"
        }}
    elif len(label_matches) > 1:
        target = None
        __bridge_result__ = {{
            "ok": False,
            "error": "Ambiguous actor label: {actor_name}",
            "matches": [a.get_name() for a in label_matches]
        }}
    else:
        target = label_matches[0]

if target is not None:
    target.set_actor_scale3d(
        unreal.Vector({scale[0]}, {scale[1]}, {scale[2]})
    )

    s = target.get_actor_scale3d()

    __bridge_result__ = {{
        "ok": True,
        "name": target.get_name(),
        "label": target.get_actor_label(),
        "scale": [s.x, s.y, s.z]
    }}
""")
    def delete_actor(self, actor_name: str):
        return self.execute_python(f"""
subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
actors = unreal.EditorLevelLibrary.get_all_level_actors()

name_matches = [a for a in actors if a.get_name() == "{actor_name}"]

if len(name_matches) == 1:
    target = name_matches[0]
elif len(name_matches) > 1:
    target = None
    __bridge_result__ = {{
        "ok": False,
        "error": "Multiple actors matched internal name: {actor_name}"
    }}
else:
    label_matches = [a for a in actors if a.get_actor_label() == "{actor_name}"]

    if len(label_matches) == 0:
        target = None
        __bridge_result__ = {{
            "ok": False,
            "error": "Actor not found: {actor_name}"
        }}
    elif len(label_matches) > 1:
        target = None
        __bridge_result__ = {{
            "ok": False,
            "error": "Ambiguous actor label: {actor_name}",
            "matches": [a.get_name() for a in label_matches]
        }}
    else:
        target = label_matches[0]

if target is not None:
    name = target.get_name()
    label = target.get_actor_label()
    deleted = subsystem.destroy_actor(target)

    __bridge_result__ = {{
        "ok": bool(deleted),
        "name": name,
        "label": label
    }}
""")

    def delete_asset(self, asset_path: str):
        return self.execute_python(f'''
if not unreal.EditorAssetLibrary.does_asset_exist("{asset_path}"):
    __bridge_result__ = {{
        "ok": False,
        "error": "Asset not found: {asset_path}"
    }}
else:
    deleted = unreal.EditorAssetLibrary.delete_asset("{asset_path}")

    __bridge_result__ = {{
        "ok": bool(deleted),
        "asset_path": "{asset_path}",
        "deleted": bool(deleted)
    }}
''')

    def save_level(self, requested_map=None):
        """Persist the active level and verify a real /Game map is clean.

        Temporary /Temp/Untitled worlds are saved-as a real project map before
        verification. Success is impossible unless the package exists, the
        active world points at that map, and the map is no longer dirty.
        """
        result = self.execute_python(f'''\
import unreal
requested_map = {requested_map!r}
world = unreal.EditorLevelLibrary.get_editor_world()
if world is None:
    __bridge_result__ = {{"ok": False, "code": "NO_ACTIVE_LEVEL", "requested_map": requested_map}}
else:
    package = world.get_outermost()
    before_path = world.get_path_name()
    dirty_before = package in unreal.EditorLoadingAndSavingUtils.get_dirty_map_packages()
    was_temp = before_path.startswith("/Temp/") or "/Untitled_" in before_path or not before_path.startswith("/Game/")
    saved_map = before_path
    save_error = None
    if was_temp:
        # Default Save-As target derives from the LIVE project, never from a
        # hardcoded product project (an AvaLive-specific default would pollute
        # every other project the agent works in).
        if not requested_map or not requested_map.startswith("/Game/"):
            project_path = str(unreal.Paths.get_project_file_path()).replace(chr(92), "/")
            project_name = project_path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
            requested_map = "/Game/Maps/" + project_name
            if not requested_map.startswith("/Game/Maps/"):
                requested_map = "/Game/Maps/" + requested_map.rsplit("/", 1)[-1]
        saved_map = requested_map
        subsystem = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        try:
            saved = bool(unreal.EditorLoadingAndSavingUtils.save_map(world, requested_map))
        except Exception as exc:
            saved = False
            save_error = str(exc)
    else:
        saved = bool(unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True))
    # Re-read the active world after the save-as operation. Map package
    # bookkeeping is reflected by the world/package objects directly.
    world_after = unreal.EditorLevelLibrary.get_editor_world()
    after_path = world_after.get_path_name() if world_after else ""
    after_package = world_after.get_outermost() if world_after else None
    dirty_after = bool(after_package and after_package in unreal.EditorLoadingAndSavingUtils.get_dirty_map_packages())
    package_exists = bool(saved_map.startswith("/Game/") and unreal.EditorAssetLibrary.does_asset_exist(saved_map))
    active_identity_correct = bool(after_path.startswith(saved_map + ".") or after_path == saved_map or (saved_map.rsplit("/", 1)[-1] in after_path and after_path.startswith("/Game/")))
    verified = bool(saved and package_exists and active_identity_correct and not dirty_after)
    __bridge_result__ = {{
        "ok": verified,
        "map_before": before_path,
        "map_after": after_path,
        "requested_asset_path": requested_map,
        "requested_map": requested_map,
        "saved_map": saved_map,
        "was_temp_level": was_temp,
        "package_exists": package_exists,
        "dirty_before": dirty_before,
        "dirty_after": dirty_after,
        "active_map": after_path,
        "active_map_identity_correct": active_identity_correct,
        "verified": verified,
        "save_error": save_error,
    }}
''')
        if isinstance(result, dict) and isinstance(result.get("result"), dict):
            payload = result["result"]
            if payload.get("verified"):
                active_map = payload.get("map_after", requested_map)
                startup_asset = str(active_map).rsplit(".", 1)[0] if "." in str(active_map) else str(active_map)
                startup = self.set_startup_map(startup_asset)
                startup_payload = startup.get("result") if isinstance(startup, dict) else None
                payload["startup_map"] = startup_asset
                payload["startup_map_persisted"] = bool(isinstance(startup_payload, dict) and startup_payload.get("config_verified"))
                payload["verified"] = bool(payload.get("verified") and payload["startup_map_persisted"])
                payload["ok"] = payload["verified"]
                if not payload["verified"]:
                    payload["save_error"] = "Startup map configuration was not verified"
        return result
    def _send(self, payload):
        data = (json.dumps(payload) + "\n").encode("utf-8")

        try:
            with socket.create_connection(
                (self.host, self.port),
                timeout=self.timeout
            ) as sock:

                sock.settimeout(self.timeout)
                sock.sendall(data)

                received = b""

                while b"\n" not in received:
                    chunk = sock.recv(65536)

                    if not chunk:
                        break

                    received += chunk

                if not received:
                    return {
                        "ok": False,
                        "error": "Empty bridge response"
                    }

                return json.loads(
                    received.decode("utf-8").strip()
                )

        except Exception as exc:
            return {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}"
            }


if __name__ == "__main__":
    bridge = UnrealBridge()

    print("=== Unreal Bridge Test ===")
    print(bridge.ping())











