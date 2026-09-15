"""AIVIDO overnight preflight probe: enumerate the live showcase scene."""
import json

ews = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
actors = ews.get_all_level_actors()
out = []
for a in actors:
    loc = a.get_actor_location()
    entry = {
        "label": a.get_actor_label(),
        "cls": a.get_class().get_name(),
        "pos": [round(loc.x, 0), round(loc.y, 0), round(loc.z, 0)],
    }
    plc = a.get_component_by_class(unreal.PointLightComponent)
    if plc:
        try:
            entry["intensity"] = round(plc.get_editor_property("intensity"), 1)
            entry["radius"] = plc.get_editor_property("attenuation_radius")
            col = plc.get_editor_property("light_color")
            entry["color"] = [col.r, col.g, col.b]
        except Exception:
            pass
    dlc = a.get_component_by_class(unreal.DirectionalLightComponent)
    if dlc:
        entry["dir_intensity"] = dlc.get_editor_property("intensity")
    out.append(entry)

map_name = unreal.EditorLevelLibrary.get_editor_world().get_path_name()
__bridge_result__ = {"count": len(out), "map": map_name, "actors": out}
