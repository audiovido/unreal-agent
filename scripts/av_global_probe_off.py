"""Restore skylight to its original intensity and capture the after-restore frame."""
import os
import unreal

saved_dir = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_saved_dir())
out_dir = os.path.join(saved_dir, "UnrealAgent")
p = os.path.join(out_dir, "live2_D.png")
if os.path.isfile(p):
    os.remove(p)

ews = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
sky = None
for a in ews.get_all_level_actors():
    if a.get_actor_label() == "AIVIDO_SkyLight":
        sky = a
        break
sc = sky.get_component_by_class(unreal.SkyLightComponent)
sc.set_editor_property("intensity", 0.55)
d = str(unreal.UnrealAgentBlueprintLibrary.capture_active_viewport_detailed(p))
__bridge_result__ = {"restored": float(sc.get_editor_property("intensity")),
                     "path": p, "size": os.path.getsize(p) if os.path.isfile(p) else 0,
                     "diag": d}
