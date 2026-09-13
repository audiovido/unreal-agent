"""Bridge-side: repair rotations with explicit keywords (positional order trap).

This build's unreal.Rotator positional order is (roll, pitch, yaw). All staged
rotations are re-applied with explicit keyword args, then audited axis-by-axis.
"""
import unreal

report = {"before": {}, "after": {}, "save": None}


def find(label):
    for a in unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors():
        if a.get_actor_label() == label:
            return a
    return None


def rot_of(a):
    r = a.get_actor_rotation()
    return {"roll": round(r.roll, 1), "pitch": round(r.pitch, 1), "yaw": round(r.yaw, 1)}


TARGETS = {
    "AIVIDO_Heidi": 180.0,    # facing hero camera (listening/acknowledge)
    "AIVIDO_Worker01": 45.0,  # at desk, working
    "AIVIDO_Worker02": 15.0,  # glance up toward Heidi/dais
    "AIVIDO_Worker03": 148.0, # attention toward room center
}
ACCESSORY_YAW = {
    "AIVIDO_Acc_Heidi_Duster": 180.0,
    "AIVIDO_Acc_Worker02_HatBrim": 15.0,
    "AIVIDO_Acc_Worker02_HatCrown": 15.0,
    "AIVIDO_Acc_Worker03_HatBrim": 148.0,
    "AIVIDO_Acc_Worker03_HatCrown": 148.0,
    "AIVIDO_Acc_Heidi_HatBrim": 180.0,
    "AIVIDO_Acc_Heidi_HatCrown": 180.0,
}

all_targets = dict(TARGETS)
all_targets.update(ACCESSORY_YAW)
for label in all_targets:
    a = find(label)
    if a:
        report["before"][label] = rot_of(a)

# repair: characters
for label, yaw in TARGETS.items():
    a = find(label)
    if a:
        a.set_actor_rotation(unreal.Rotator(roll=0.0, pitch=0.0, yaw=yaw), False)

# repair: accessories
for label, yaw in ACCESSORY_YAW.items():
    a = find(label)
    if a:
        a.set_actor_rotation(unreal.Rotator(roll=0.0, pitch=0.0, yaw=yaw), False)

# repair: hero camera yaw 34 pitch -8 roll 0
cam = find("AIVIDO_HeroCamera")
if cam:
    cam.set_actor_rotation(unreal.Rotator(roll=0.0, pitch=-8.0, yaw=34.0), False)

# audit after
for label in all_targets:
    a = find(label)
    if a:
        report["after"][label] = rot_of(a)
if cam:
    report["after"]["AIVIDO_HeroCamera"] = rot_of(cam)

saved = unreal.EditorLevelLibrary.save_current_level()
dirty = unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)
report["save"] = {"level_saved": bool(saved), "packages_saved": bool(dirty)}

__bridge_result__ = report
