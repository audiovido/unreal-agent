import os
import time
import json

from tools.unreal.unreal_bridge import UnrealBridge

bridge = UnrealBridge(timeout=30)

out_dir = os.path.join(
    os.environ["LOCALAPPDATA"],
    "UnrealAgent",
    "captures",
)

out_file = os.path.join(
    out_dir,
    "scene_capture_test.png",
)

os.makedirs(out_dir, exist_ok=True)

try:
    os.remove(out_file)
except FileNotFoundError:
    pass

code = r"""
import os
import unreal

out_dir = os.path.join(
    os.environ["LOCALAPPDATA"],
    "UnrealAgent",
    "captures",
)

os.makedirs(out_dir, exist_ok=True)

editor = unreal.get_editor_subsystem(
    unreal.UnrealEditorSubsystem
)

world = editor.get_editor_world()
camera_info = editor.get_level_viewport_camera_info()

if world is None:
    __bridge_result__ = {
        "ok": False,
        "error": "No editor world"
    }

elif camera_info is None:
    __bridge_result__ = {
        "ok": False,
        "error": "No level viewport camera"
    }

else:
    camera_location, camera_rotation = camera_info

    actor_system = unreal.get_editor_subsystem(
        unreal.EditorActorSubsystem
    )

    capture_actor = actor_system.spawn_actor_from_class(
        unreal.SceneCapture2D,
        camera_location,
        camera_rotation,
        True
    )

    component = capture_actor.get_component_by_class(
        unreal.SceneCaptureComponent2D
    )

    if component is None:
        __bridge_result__ = {
            "ok": False,
            "error": "SceneCaptureComponent2D not found"
        }

    else:
        render_target = unreal.RenderingLibrary.create_render_target2d(
            world,
            1280,
            720,
            unreal.TextureRenderTargetFormat.RTF_RGBA8
        )

        component.set_editor_property(
            "texture_target",
            render_target
        )

        component.set_editor_property(
            "capture_every_frame",
            False
        )

        component.set_editor_property(
            "capture_on_movement",
            False
        )

        component.set_editor_property(
            "capture_source",
            unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR
        )

        # Match active editor viewport FOV when possible.
        fov = 90.0

        try:
            level_editor = unreal.get_editor_subsystem(
                unreal.LevelEditorSubsystem
            )

            key = level_editor.get_active_viewport_config_key()

            viewport_fov = level_editor.get_level_viewport_fov(
                key
            )

            if viewport_fov:
                fov = float(viewport_fov)

        except Exception:
            pass

        component.set_editor_property(
            "fov_angle",
            fov
        )

        component.capture_scene()

        unreal.RenderingLibrary.export_render_target(
            world,
            render_target,
            out_dir,
            "scene_capture_test.png"
        )

        try:
            actor_system.destroy_actor(capture_actor)
        except Exception:
            pass

        __bridge_result__ = {
            "ok": True,
            "path": os.path.join(
                out_dir,
                "scene_capture_test.png"
            ),
            "fov": fov
        }
"""

result = bridge.execute_python(code)

print(json.dumps(
    result,
    ensure_ascii=False,
    indent=2
))

deadline = time.time() + 20

while time.time() < deadline:

    if os.path.isfile(out_file):

        size = os.path.getsize(out_file)

        if size > 1000:
            print()
            print("SCENE_CAPTURE_OK")
            print(out_file)
            print("SIZE =", size)
            raise SystemExit(0)

    time.sleep(0.5)

print()
print("SCENE_CAPTURE_FAILED")
raise SystemExit(2)