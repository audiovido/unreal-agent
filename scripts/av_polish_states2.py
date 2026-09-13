"""Idempotent completion of the worker-state polish pass.
Absolute target transforms (safe to re-run): Worker03_Walk staged mid-room on the
UA-desk -> dais line, accessories at desk+delta, state labels applied, then save.
"""
import unreal

# absolute staging targets = original desk pose + walk delta (-190, +150)
TARGETS = {
    "AIVIDO_Worker03_Walk":        {"loc": [300.0, -150.0, -13.0], "yaw": 153.0},
    "AIVIDO_Acc_Worker03_HatBrim":  {"loc": [302.0, -151.0, 162.0]},
    "AIVIDO_Acc_Worker03_HatCrown": {"loc": [302.0, -151.0, 168.0]},
    "AIVIDO_Acc_Worker03_VestL":    {"loc": [306.0, -161.0, 102.0]},
    "AIVIDO_Acc_Worker03_VestR":    {"loc": [317.0, -150.0, 102.0]},
    "AIVIDO_Acc_Worker03_Bandana":  {"loc": [303.0, -156.0, 135.0]},
}
OLD_TO_NEW = {"AIVIDO_Worker01": "AIVIDO_Worker01_Work",
              "AIVIDO_Worker02": "AIVIDO_Worker02_Idle",
              "AIVIDO_Worker03": "AIVIDO_Worker03_Walk"}

ews = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
by_label = {a.get_actor_label(): a for a in ews.get_all_level_actors()}

# 1) ensure renames (idempotent)
for old, new in OLD_TO_NEW.items():
    a = by_label.get(old)
    if a:
        a.set_actor_label(new)
        by_label[new] = a

# 2) absolute transforms (idempotent even if the failed run half-applied)
moved = {}
for name, t in TARGETS.items():
    a = by_label.get(name)
    if not a:
        continue
    loc = a.get_actor_location()
    a.set_actor_location(unreal.Vector(t["loc"][0], t["loc"][1], t["loc"][2]), False, False)
    if "yaw" in t:
        a.set_actor_rotation(unreal.Rotator(roll=0.0, pitch=0.0, yaw=t["yaw"]), False)
    loc2 = a.get_actor_location()
    moved[name] = [round(loc2.x, 1), round(loc2.y, 1), round(loc2.z, 1)]

# 3) save
save_ok = bool(les.save_current_level())

# 4) verify via FRESH full enumeration (bypasses any stale dict)
labels = [a.get_actor_label() for a in ews.get_all_level_actors()]
__bridge_result__ = {"moved": moved, "map_saved": save_ok,
                     "state_labels_present": [l for l in labels if l.endswith(("_Work", "_Idle", "_Walk"))],
                     "missing": [n for n in TARGETS if n not in by_label]}
