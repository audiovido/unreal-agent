"""Explicitly invalidate + redraw all level viewports (standard editor commands,
not capture research). Reports which redraw entry points exist on this build."""
import unreal

have = {}
for fn in ("editor_redraw_all_viewports", "editor_invalidate_all_viewports"):
    have[fn] = hasattr(unreal.EditorLevelLibrary, fn)

if have["editor_invalidate_all_viewports"]:
    unreal.EditorLevelLibrary.editor_invalidate_all_viewports()
if have["editor_redraw_all_viewports"]:
    unreal.EditorLevelLibrary.editor_redraw_all_viewports()

ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
loc, rot = ues.get_level_viewport_camera_info()
__bridge_result__ = {"have": have,
                     "viewport": {"loc": [round(loc.x, 1), round(loc.y, 1), round(loc.z, 1)],
                                  "rot_rpY": [round(rot.roll, 1), round(rot.pitch, 1), round(rot.yaw, 1)]}}
