"""Read wall hidden state + exposure, and produce capture A (current viewport state).
Read-only except the capture file. Records restore data."""
import json
import os

import unreal

saved_dir = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_saved_dir())
out_dir = os.path.join(saved_dir, "UnrealAgent")
os.makedirs(out_dir, exist_ok=True)
cap_a = os.path.join(out_dir, "liveness_A.png")
if os.path.isfile(cap_a):
    os.remove(cap_a)

ews = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
actors = ews.get_all_level_actors()


def by_label(lbl):
    for a in actors:
        if a.get_actor_label() == lbl:
            return a
    return None


wall = by_label("AIVIDO_FrontWall")
try:
    wall_hidden = wall.is_temporarily_hidden_in_editor()
except Exception as e:
    wall_hidden = f"err:{e}"

# front wall bounds (to confirm it spans the camera line of sight)
org, ext = wall.get_actor_bounds(False)

pp = by_label("AIVIDO_PostProcess")
pp_info = None
if pp:
    ppc = pp.get_component_by_class(unreal.PostProcessComponent)
    if ppc:
        s = ppc.settings
        pp_info = {
            "unbound": getattr(s, "unbound", None),
            "exposure_bias": getattr(s, "auto_exposure_bias", None),
            "metering_manual": getattr(s, "metering_manual_clamp_percent", None),
        }

diag = str(unreal.UnrealAgentBlueprintLibrary.capture_active_viewport_detailed(cap_a))
size = os.path.getsize(cap_a) if os.path.isfile(cap_a) else 0

vp_loc, vp_rot = ues.get_level_viewport_camera_info()
__bridge_result__ = {
    "capture_A": {"path": cap_a, "size": size, "diag": diag},
    "wall_hidden_in_editor": wall_hidden,
    "wall_bounds": {"origin": [round(org.x), round(org.y), round(org.z)],
                    "extent": [round(ext.x), round(ext.y), round(ext.z)]},
    "postprocess": pp_info,
    "viewport": {"loc": [round(vp_loc.x, 1), round(vp_loc.y, 1), round(vp_loc.z, 1)],
                 "rot_rpY": [round(vp_rot.roll, 1), round(vp_rot.pitch, 1), round(vp_rot.yaw, 1)]},
}
