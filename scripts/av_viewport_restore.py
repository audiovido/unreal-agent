"""Restore the level viewport to its as-found pose (the recorded BEFORE state).
This reverts the transient editor-UI change used in the liveness proof. The map
asset is not touched (viewport pose is not stored in the umap)."""
import unreal

ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
ues.set_level_viewport_camera_info(
    unreal.Vector(-950.0, -420.0, 235.0),
    unreal.Rotator(roll=-8.0, pitch=0.0, yaw=27.0),  # explicit kwargs (rpY order)
)
loc, rot = ues.get_level_viewport_camera_info()
__bridge_result__ = {
    "restored": {"loc": [round(loc.x, 1), round(loc.y, 1), round(loc.z, 1)],
                 "rot_rpY": [round(rot.roll, 1), round(rot.pitch, 1), round(rot.yaw, 1)]},
}
