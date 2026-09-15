"""Bridge-side: persist idle anim state + final Heidi facing + save."""
import unreal

report = {"anim_data": [], "heidi_yaw": None, "save": None}
IDLE = unreal.load_asset("/Game/Mannequins/Anims/Unarmed/MM_Idle")


def find(label):
    for a in unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors():
        if a.get_actor_label() == label:
            return a
    return None


for label in ("AIVIDO_Heidi", "AIVIDO_Worker01", "AIVIDO_Worker02", "AIVIDO_Worker03"):
    a = find(label)
    entry = {"label": label}
    if a is None:
        entry["error"] = "missing"
        report["anim_data"].append(entry)
        continue
    comp = a.get_component_by_class(unreal.SkeletalMeshComponent)
    try:
        comp.set_editor_property("animation_mode", unreal.AnimationMode.ANIMATION_SINGLE_NODE)
        data = comp.get_editor_property("animation_data")
        data.set_editor_property("anim_to_play", IDLE)
        data.set_editor_property("saved_looping", True)
        data.set_editor_property("saved_playing", True)
        data.set_editor_property("saved_play_rate", 1.0)
        comp.set_editor_property("animation_data", data)
        entry["data"] = "set"
    except Exception as e:
        entry["data_err"] = str(e)[:120]
    # live play (instance) on top; keeps editor view animated right now
    try:
        comp.call_method("PlayAnimation", args=(IDLE, True))
        entry["live"] = "playing"
    except Exception as e:
        entry["live_err"] = str(e)[:80]
    report["anim_data"].append(entry)

# Heidi: re-assert hero facing (idle root reasserted 180; set 165 explicitly)
h = find("AIVIDO_Heidi")
if h:
    h.set_actor_rotation(unreal.Rotator(0.0, 165.0, 0.0), False)
    report["heidi_yaw"] = round(h.get_actor_rotation().yaw, 1)
    # duster pinned to her back for yaw 180 was written earlier; align to 165
    d = find("AIVIDO_Acc_Heidi_Duster")
    if d:
        d.set_actor_rotation(unreal.Rotator(0.0, 165.0, 0.0), False)

# save
saved = unreal.EditorLevelLibrary.save_current_level()
dirty = unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)
report["save"] = {"level_saved": bool(saved), "packages_saved": bool(dirty)}

# read-back: anim_data persisted?
h = find("AIVIDO_Heidi")
comp = h.get_component_by_class(unreal.SkeletalMeshComponent)
data = comp.get_editor_property("animation_data")
anim = data.get_editor_property("anim_to_play")
report["readback_heidi"] = {
    "anim": anim.get_path_name() if anim else None,
    "looping": data.get_editor_property("saved_looping"),
    "playing": data.get_editor_property("saved_playing"),
}

__bridge_result__ = report
