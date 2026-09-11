import unreal, traceback
out = []
def V(v): return None if v is None else [round(v.x,1), round(v.y,1), round(v.z,1)]
def R(r):
    if r is None: return None
    return [round(r.roll,1), round(r.pitch,1), round(r.yaw,1)]
try:
    ews = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    for a in ews.get_all_level_actors():
        cname = a.get_class().get_name()
        item = {
            "label": a.get_actor_label(), "class": cname,
            "loc": V(a.get_actor_location()), "rot": R(a.get_actor_rotation()), "scale": V(a.get_actor_scale3d()),
        }
        if "Light" in cname:
            for p in ("intensity","source_radius","source_length","attenuation_radius","light_color","inner_cone_angle","outer_cone_angle","use_temperature","temperature"):
                try: item[p] = a.get_editor_property(p)
                except Exception: pass
        if cname=="CameraActor":
            try:
                item["fov"] = a.get_editor_property("camera_component").field_of_view
            except Exception: pass
        out.append(item)
except Exception:
    out = [{"error": traceback.format_exc()}]
__bridge_result__ = out
