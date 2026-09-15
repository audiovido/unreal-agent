"""Bridge-side: focal widen + save + persistence verification."""
import unreal

report = {"save": None, "anim_state": {}, "cam": None}


def find(label):
    for a in unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors():
        if a.get_actor_label() == label:
            return a
    return None


# 1) widen hero focal 35 -> 30mm (Worker01 at frame edge moves comfortably inside)
cam = find("AIVIDO_HeroCamera")
if cam:
    try:
        cc = cam.get_cine_camera_component()
        old = cc.get_editor_property("current_focal_length")
        cc.set_editor_property("current_focal_length", 30.0)
        report["cam"] = {"focal": [old, 30.0]}
    except Exception as e:
        report["cam_err"] = str(e)[:120]

# 2) save the level + dirty packages
saved = unreal.EditorLevelLibrary.save_current_level()
dirty = unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)
report["save"] = {"level_saved": bool(saved), "packages_saved": bool(dirty)}

# 3) verify animation state per character
for label in ("AIVIDO_Heidi", "AIVIDO_Worker01", "AIVIDO_Worker02", "AIVIDO_Worker03"):
    a = find(label)
    if not a:
        report["anim_state"][label] = "missing"
        continue
    comp = a.get_component_by_class(unreal.SkeletalMeshComponent)
    try:
        anim = comp.get_editor_property("animation_data").get_editor_property("anim_to_play")
        mode = str(comp.get_editor_property("animation_mode"))
        playing = None
        try:
            playing = bool(comp.get_editor_property("playing"))
        except Exception:
            pass
        report["anim_state"][label] = {
            "mode": mode,
            "anim": anim.get_path_name() if anim else None,
            "playing": playing,
        }
    except Exception as e:
        report["anim_state"][label] = {"error": str(e)[:100]}

# 4) verify key light + heidi transform round-trip
key = find("AIVIDO_KeyWarm")
if key:
    p = key.get_actor_location()
    report["key_pos"] = [round(p.x), round(p.y), round(p.z)]
h = find("AIVIDO_Heidi")
if h:
    p = h.get_actor_location()
    r = h.get_actor_rotation()
    report["heidi"] = {"pos": [round(p.x), round(p.y), round(p.z)], "yaw": round(r.yaw, 1)}

__bridge_result__ = report
