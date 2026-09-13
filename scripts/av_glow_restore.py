"""Bridge-side: restore CoreGlow to 2000 + final state verification."""
import unreal

report = {}


def find(label):
    for a in unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors():
        if a.get_actor_label() == label:
            return a
    return None


glow = find("AIVIDO_CoreGlow")
if glow:
    gc = glow.get_component_by_class(unreal.PointLightComponent)
    gc.set_editor_property("intensity", 2000.0)
    report["core_glow"] = gc.get_editor_property("intensity")

# final character facing table
report["characters"] = {}
for label in ("AIVIDO_Heidi", "AIVIDO_Worker01", "AIVIDO_Worker02", "AIVIDO_Worker03"):
    a = find(label)
    if a:
        r = a.get_actor_rotation()
        p = a.get_actor_location()
        report["characters"][label] = {"yaw": round(r.yaw, 1),
                                       "pos": [round(p.x), round(p.y)]}

# final camera
cam = find("AIVIDO_HeroCamera")
if cam:
    cc = cam.get_cine_camera_component()
    r = cam.get_actor_rotation()
    report["camera"] = {"yaw": round(r.yaw, 1), "pitch": round(r.pitch, 1),
                        "focal": cc.get_editor_property("current_focal_length")}

# final light positions
for label in ("AIVIDO_KeyWarm", "AIVIDO_FillCool", "AIVIDO_RimGold"):
    a = find(label)
    if a:
        p = a.get_actor_location()
        report.setdefault("lights", {})[label] = [round(p.x), round(p.y), round(p.z)]

# fog state
fog = find("AIVIDO_Fog")
if fog:
    fc = fog.get_component_by_class(unreal.ExponentialHeightFogComponent)
    report["fog_density"] = round(fc.get_editor_property("fog_density"), 4)

report["actor_count"] = len(unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors())
report["map"] = unreal.EditorLevelLibrary.get_editor_world().get_path_name()

__bridge_result__ = report
