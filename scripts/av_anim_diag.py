"""Bridge-side: diagnose anim binding (skeleton compat) + persistent set route."""
import unreal

report = {}
IDLE_PATH = "/Game/Mannequins/Anims/Unarmed/MM_Idle"
IDLE = unreal.load_asset(IDLE_PATH)

try:
    report["idle_skeleton"] = IDLE.get_editor_property("skeleton").get_path_name()
except Exception as e:
    report["idle_skel_err"] = str(e)[:100]

heidi = None
for a in unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors():
    if a.get_actor_label() == "AIVIDO_Heidi":
        heidi = a
        break
comp = heidi.get_component_by_class(unreal.SkeletalMeshComponent)
report["mesh"] = comp.get_editor_property("skeletal_mesh_asset").get_path_name()
try:
    report["mesh_skeleton"] = comp.get_editor_property("skeletal_mesh_asset").get_editor_property("skeleton").get_path_name()
except Exception as e:
    report["mesh_skel_err"] = str(e)[:100]

# route: set_animation then verify immediately (no PlayAnimation afterwards)
try:
    comp.call_method("SetAnimation", args=(IDLE,))
    data = comp.get_editor_property("animation_data")
    report["after_set_animation"] = (data.get_editor_property("anim_to_play").get_path_name()
                                     if data.get_editor_property("anim_to_play") else None)
except Exception as e:
    report["set_animation_err"] = str(e)[:140]

# route: write struct WITHOUT any subsequent play call
try:
    comp.set_editor_property("animation_mode", unreal.AnimationMode.ANIMATION_SINGLE_NODE)
    data = comp.get_editor_property("animation_data")
    data.set_editor_property("anim_to_play", IDLE)
    data.set_editor_property("saved_looping", True)
    data.set_editor_property("saved_playing", True)
    data.set_editor_property("saved_play_rate", 1.0)
    comp.set_editor_property("animation_data", data)
    data2 = comp.get_editor_property("animation_data")
    report["after_struct_write"] = (data2.get_editor_property("anim_to_play").get_path_name()
                                    if data2.get_editor_property("anim_to_play") else None)
except Exception as e:
    report["struct_write_err"] = str(e)[:140]

__bridge_result__ = report
