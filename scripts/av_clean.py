import unreal, json
def V(v): return [round(v.x,1), round(v.y,1), round(v.z,1)]
ews = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
lvl = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
# ensure not in PIE
try:
    lvl.editor_request_end_play()
except Exception:
    pass
import time; time.sleep(1)
deleted = []
kept = []
for a in ews.get_all_level_actors():
    lab = a.get_actor_label()
    if lab.startswith("Agent_Test_Cube") or lab.startswith("GOAL_TEST") or lab.startswith("UA_Env_") or lab.startswith("UA_L_"):
        try:
            ews.destroy_actor(a); deleted.append(lab)
        except Exception as e:
            kept.append(lab + ":" + str(e)[:40])
    else:
        kept.append(lab)
world = unreal.EditorLevelLibrary.get_editor_world()
ame = unreal.EditorLoadingAndSavingUtils.save_map(world, "/Game/Maps/AvaLive_Main")
__bridge_result__ = {"deleted": sorted(deleted), "kept": sorted(kept), "saved": bool(ame)}
