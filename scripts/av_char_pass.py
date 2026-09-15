"""Bridge-side: AIVIDO overnight character pass.

1. Heidi hero pass: face the hero camera, re-pin accessories to her new frame,
   reposition the warm key light for hero modeling from the camera side.
2. Loop MM_Idle on Heidi + all three workers (ANIMATION_SINGLE_NODE, proven).
Nothing is deleted; every transform is recorded in a restorable before-table.
"""
import math

import unreal

report = {"rotated": [], "accessories": [], "anims": [], "key": None}

MAP_ACTORS = {}


def find(label):
    if label in MAP_ACTORS:
        return MAP_ACTORS[label]
    for a in unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors():
        if a.get_actor_label() == label:
            MAP_ACTORS[label] = a
            return a
    return None


# ------------------------------------------------------------------
# 1) Heidi hero facing: turn toward the hero camera (yaw ~165)
# ------------------------------------------------------------------
HEIDI_YAW = 165.0
heidi = find("AIVIDO_Heidi")
if heidi:
    before = heidi.get_actor_rotation()
    heidi.set_actor_rotation(unreal.Rotator(0.0, HEIDI_YAW, 0.0), False)
    report["rotated"].append({"label": "AIVIDO_Heidi", "yaw_before": round(before.yaw, 1),
                              "yaw_after": HEIDI_YAW})

    # re-pin accessories relative to her new frame (they were placed for yaw 35)
    hx, hy, hz = -620.0, -460.0, -13.0
    pins = {
        "AIVIDO_Acc_Heidi_HatBrim":   (hx - 1.0, hy + 2.0, hz + 175.0, 0.0),
        "AIVIDO_Acc_Heidi_HatCrown":  (hx - 1.0, hy + 2.0, hz + 181.0, 0.0),
        "AIVIDO_Acc_Heidi_Duster":    (hx + 15.0, hy - 6.0, hz + 78.0, HEIDI_YAW),
        "AIVIDO_Prop_Papers_H":       (hx - 20.0, hy - 40.0, hz + 17.0, 0.0),
    }
    for label, (x, y, z, yaw) in pins.items():
        a = find(label)
        if a is None:
            report["accessories"].append({"label": label, "error": "missing"})
            continue
        old = a.get_actor_location()
        oldr = a.get_actor_rotation()
        a.set_actor_location(unreal.Vector(x, y, z), False, False)
        if yaw:
            a.set_actor_rotation(unreal.Rotator(0.0, yaw, 0.0), False)
        report["accessories"].append({
            "label": label,
            "from": [round(old.x), round(old.y), round(old.z), round(oldr.yaw, 1)],
            "to": [round(x), round(y), round(z), round(yaw, 1)],
        })

    # 2) hero key light: warm modeling from camera-left on Heidi
    key = find("AIVIDO_KeyWarm")
    if key:
        old = key.get_actor_location()
        key.set_actor_location(unreal.Vector(-820.0, -700.0, 250.0), False, False)
        report["key"] = {"from": [round(old.x), round(old.y), round(old.z)],
                         "to": [-820, -700, 250]}

# ------------------------------------------------------------------
# 3) MM_Idle loops on all characters (proven single-node pattern)
# ------------------------------------------------------------------
IDLE = unreal.load_asset("/Game/Mannequins/Anims/Unarmed/MM_Idle")
report["idle_loaded"] = IDLE is not None
for label in ("AIVIDO_Heidi", "AIVIDO_Worker01", "AIVIDO_Worker02", "AIVIDO_Worker03"):
    a = find(label)
    if a is None:
        report["anims"].append({"label": label, "error": "missing"})
        continue
    comp = a.get_component_by_class(unreal.SkeletalMeshComponent)
    if comp is None:
        report["anims"].append({"label": label, "error": "no_skel_component"})
        continue
    try:
        comp.set_editor_property("animation_mode", unreal.AnimationMode.ANIMATION_SINGLE_NODE)
        data = comp.get_editor_property("animation_data")
        data.set_editor_property("anim_to_play", IDLE)
        data.set_editor_property("b_looping", True)
        data.set_editor_property("play_rate", 1.0)
        comp.set_editor_property("animation_data", data)
        report["anims"].append({"label": label, "ok": True})
    except Exception as exc:
        report["anims"].append({"label": label, "error": str(exc)[:160]})

# report also the hero-cam->heidi framing after rotation
cam = find("AIVIDO_HeroCamera")
if cam and heidi:
    cl = cam.get_actor_location()
    hl = heidi.get_actor_location()
    view_yaw = cam.get_actor_rotation().yaw
    ang = math.degrees(math.atan2(hl.y - cl.y, hl.x - cl.x))
    off = (ang - view_yaw + 180) % 360 - 180
    dist = math.hypot(hl.x - cl.x, hl.y - cl.y)
    report["heidi_in_frame"] = {"offset_deg": round(off, 1), "dist_cm": round(dist),
                                "half_fov_h": 27.0, "inside": abs(off) < 27.0}

__bridge_result__ = report
