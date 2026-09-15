"""Bridge-side: stage the dispatch moment for the AIVIDO showcase.

Mission flow made visually readable from the hero camera:
  - Heidi faces the camera (listening/acknowledge pose)         [done earlier]
  - Worker02 glances up from desk toward the dais (dispatched)
  - Worker03 turns to attention toward the room center
  - Worker01 keeps working at its desk (alive/idle contrast)
  - Core glow raised: the "result processing" read on the holo core
Everything recorded as before/after; nothing deleted.
"""
import unreal

report = {"staged": [], "glow": None, "save": None}


def find(label):
    for a in unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors():
        if a.get_actor_label() == label:
            return a
    return None


stages = {
    # worker02: between desk (yaw -135) and dais (yaw 31) -> looking up at the boss
    "AIVIDO_Worker02": 15.0,
    # worker03: full attention toward room center (computed 148.5 -> 148)
    "AIVIDO_Worker03": 148.0,
}
for label, yaw in stages.items():
    a = find(label)
    if not a:
        report["staged"].append({"label": label, "error": "missing"})
        continue
    old = a.get_actor_rotation()
    a.set_actor_rotation(unreal.Rotator(0.0, yaw, 0.0), False)
    # re-pin his hat to the new facing (hats were placed for old yaws)
    hat = find("AIVIDO_Acc_%s_HatBrim" % label.replace("AIVIDO_", ""))
    crown = find("AIVIDO_Acc_%s_HatCrown" % label.replace("AIVIDO_", ""))
    for acc in (hat, crown):
        if acc:
            acc.set_actor_rotation(unreal.Rotator(0.0, yaw, 0.0), False)
    report["staged"].append({
        "label": label, "yaw_before": round(old.yaw, 1), "yaw_after": yaw,
        "hat_repinned": bool(hat),
    })

# core glow: active-processing read (recorded, reversible)
glow = find("AIVIDO_CoreGlow")
if glow:
    gc = glow.get_component_by_class(unreal.PointLightComponent)
    before = gc.get_editor_property("intensity")
    gc.set_editor_property("intensity", 900.0)
    report["glow"] = {"before": before, "after": 900.0}

# Heidi duster: align to her adopted hero yaw 180
d = find("AIVIDO_Acc_Heidi_Duster")
if d:
    d.set_actor_rotation(unreal.Rotator(0.0, 180.0, 0.0), False)
    report["duster"] = "aligned to yaw 180"

# save
saved = unreal.EditorLevelLibrary.save_current_level()
dirty = unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)
report["save"] = {"level_saved": bool(saved), "packages_saved": bool(dirty)}

__bridge_result__ = report
