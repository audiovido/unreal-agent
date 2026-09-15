"""Move the live level viewport to the interior hero pose (transient editor state).
Separate call so the editor can redraw before the next capture."""
import unreal

ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
ues.set_level_viewport_camera_info(
    unreal.Vector(-820.0, -350.0, 270.0),
    unreal.Rotator(roll=0.0, pitch=-10.0, yaw=0.0),
)
loc, rot = ues.get_level_viewport_camera_info()
__bridge_result__ = {"viewport": {"loc": [round(loc.x, 1), round(loc.y, 1), round(loc.z, 1)],
                                  "rot_rpY": [round(rot.roll, 1), round(rot.pitch, 1), round(rot.yaw, 1)]}}
