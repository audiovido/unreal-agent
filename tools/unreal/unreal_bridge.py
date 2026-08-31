import json
import socket
import os
import base64
import requests
import re

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 6766


class UnrealBridge:
    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT, timeout=30):
        self.host = host
        self.port = port
        self.timeout = timeout

    def ping(self):
        return self._send({"type": "ping"})

    def execute_python(self, code: str):
        return self._send({
            "type": "python",
            "code": code
        })

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
        return self.execute_python(r"""
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

diagnostic = (
    unreal.UnrealAgentBlueprintLibrary
    .capture_active_viewport_detailed(path)
)

diagnostic = str(diagnostic)
ok = diagnostic.startswith("OK|")

size = 0

try:
    if os.path.isfile(path):
        size = os.path.getsize(path)
except Exception:
    size = 0

__bridge_result__ = {
    "ok": bool(ok),
    "path": path,
    "size": size,
    "diagnostic": diagnostic
}
""")

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
checks = {
    "project_identity": active_project == {project_name!r},
    "project_path": project_path.lower().endswith("/" + {project_name!r}.lower() + ".uproject"),
    "level_loaded": world is not None,
    "actor_exists": actor is not None,
    "visible_mesh_actor": actor is not None and actor.get_class().get_name() == "StaticMeshActor" and mesh is not None,
    "clean_after_save": not dirty,
}
__bridge_result__ = {
    "ok": all(checks.values()),
    "project_name": active_project,
    "project_path": project_path,
    "level_path": world.get_path_name() if world else None,
    "actor_name": actor.get_actor_label() if actor else None,
    "actor_class": actor.get_class().get_name() if actor else None,
    "actor_transform": {
        "location": [actor.get_actor_location().x, actor.get_actor_location().y, actor.get_actor_location().z],
        "rotation": [actor.get_actor_rotation().pitch, actor.get_actor_rotation().yaw, actor.get_actor_rotation().roll],
        "scale": [actor.get_actor_scale3d().x, actor.get_actor_scale3d().y, actor.get_actor_scale3d().z],
    } if actor else None,
    "mesh_path": mesh.get_path_name() if mesh else None,
    "is_dirty": dirty,
    "checks": checks,
}
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
    if actor is not None:
        actor.set_actor_scale3d(unreal.Vector({scale[0]}, {scale[1]}, {scale[2]}))
        if {actor_name!r}:
            actor.set_actor_label({actor_name!r})
        if {mesh_asset!r} and hasattr(actor, "static_mesh_component"):
            mesh = unreal.load_asset({mesh_asset!r})
            if mesh is not None:
                actor.static_mesh_component.set_static_mesh(mesh)

    __bridge_result__ = {{
        "ok": actor is not None,
        "name": actor.get_name() if actor else None,
        "label": actor.get_actor_label() if actor else None,
        "class": actor.get_class().get_name() if actor else None
    }}
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

    def save_level(self):
        return self.execute_python(r'''
saved = unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)

__bridge_result__ = {
    "ok": bool(saved),
    "saved": bool(saved)
}
''')
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











