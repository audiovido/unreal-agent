"""ONE TARGETED POLISH PASS (mission step 7): make the dispatch story readable
and declare worker states the way the visual contract expects (label/task hints).

- Worker03: staged MID-WALK between his UA desk (490,-300) and the dais, facing
  his direction of travel (yaw ~153 toward the core). Accessories (hat, vest,
  bandana) shift by the same delta so he keeps his outfit.
- Worker01: stays at his desk working  -> label ..._Work
- Worker02: stays idle/glance-up       -> label ..._Idle
- Worker03 becomes the WALK state      -> label ..._Walk
Everything records before-transforms; nothing is deleted. Map is force-saved.
"""
import unreal

DELTA = unreal.Vector(-190.0, 150.0, 0.0)   # UA desk -> mid-room walk line
BEFORE = {}

ews = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
by_label = {a.get_actor_label(): a for a in ews.get_all_level_actors()}


def snap(a):
    loc, rot = a.get_actor_location(), a.get_actor_rotation()
    return {"loc": [round(loc.x, 1), round(loc.y, 1), round(loc.z, 1)],
            "rot_rpY": [round(rot.roll, 1), round(rot.pitch, 1), round(rot.yaw, 1)]}


w3 = by_label["AIVIDO_Worker03"]
BEFORE["AIVIDO_Worker03"] = snap(w3)
w3.set_actor_location(w3.get_actor_location() + DELTA, False, False)
w3.set_actor_rotation(unreal.Rotator(roll=0.0, pitch=0.0, yaw=153.0), False)

ACC = ["AIVIDO_Acc_Worker03_HatBrim", "AIVIDO_Acc_Worker03_HatCrown",
       "AIVIDO_Acc_Worker03_VestL", "AIVIDO_Acc_Worker03_VestR",
       "AIVIDO_Acc_Worker03_Bandana"]
for name in ACC:
    a = by_label.get(name)
    if a:
        BEFORE[name] = snap(a)
        a.set_actor_location(a.get_actor_location() + DELTA, False, False)

renames = {"AIVIDO_Worker01": "AIVIDO_Worker01_Work",
           "AIVIDO_Worker02": "AIVIDO_Worker02_Idle",
           "AIVIDO_Worker03": "AIVIDO_Worker03_Walk"}
applied = {}
for old, new in renames.items():
    a = by_label.get(old)
    if a:
        a.set_actor_label(new)
        applied[old] = new

save_ok = bool(les.save_current_level())

AFTER = {"AIVIDO_Worker03_Walk": snap(by_label["AIVIDO_Worker03_Walk"])}
__bridge_result__ = {"before": BEFORE, "after": AFTER,
                     "renamed": applied, "map_saved": save_ok,
                     "missing": [n for n in ACC if n not in by_label]}
