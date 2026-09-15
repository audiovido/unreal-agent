"""Bridge-side: probe anim play data properties available in this UE build."""
import unreal

heidi = None
for a in unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors():
    if a.get_actor_label() == "AIVIDO_Heidi":
        heidi = a
        break

out = {}
comp = heidi.get_component_by_class(unreal.SkeletalMeshComponent)
data = comp.get_editor_property("animation_data")
out["single_node_props"] = [p for p in dir(unreal.SingleAnimationPlayData) if not p.startswith("_")]
try:
    out["anim_mode"] = str(comp.get_editor_property("animation_mode"))
except Exception as e:
    out["anim_mode_err"] = str(e)[:100]
try:
    comp.set_editor_property("animation_mode", unreal.AnimationMode.ANIMATION_SINGLE_NODE)
    out["mode_set"] = True
except Exception as e:
    out["mode_set_err"] = str(e)[:100]
try:
    data.set_editor_property("anim_to_play",
                             unreal.load_asset("/Game/Mannequins/Anims/Unarmed/MM_Idle"))
    comp.set_editor_property("animation_data", data)
    out["anim_to_play_set"] = True
except Exception as e:
    out["anim_to_play_err"] = str(e)[:160]

# try looping property candidates
for cand in ("looping", "b_looping", "loop", "bLooping"):
    try:
        data.set_editor_property(cand, True)
        comp.set_editor_property("animation_data", data)
        out["looping_prop"] = cand
        break
    except Exception as e:
        out["loop_try_" + cand] = str(e)[:80]

__bridge_result__ = out
