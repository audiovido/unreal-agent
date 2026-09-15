"""Probe live LevelViewport camera vs HeroCamera, room bounds, lights, fog, exposure.
Read-only. No changes."""
import unreal

ews = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
actors = ews.get_all_level_actors()


def by_label(lbl):
    for a in actors:
        if a.get_actor_label() == lbl:
            return a
    return None


def pose(a):
    loc = a.get_actor_location()
    rot = a.get_actor_rotation()
    return {"loc": [round(loc.x, 1), round(loc.y, 1), round(loc.z, 1)],
            "rot": [round(rot.roll, 1), round(rot.pitch, 1), round(rot.yaw, 1)]}


vp_loc, vp_rot = ues.get_level_viewport_camera_info()

out = {
    "active_viewport": {"loc": [round(vp_loc.x, 1), round(vp_loc.y, 1), round(vp_loc.z, 1)],
                        "rot_rpY": [round(vp_rot.roll, 1), round(vp_rot.pitch, 1), round(vp_rot.yaw, 1)]},
    "hero_camera": pose(by_label("AIVIDO_HeroCamera")),
    "heidi": pose(by_label("AIVIDO_Heidi")),
    "world_map": unreal.EditorLevelLibrary.get_editor_world().get_path_name(),
}

# Lights
def light_state(lbl):
    a = by_label(lbl)
    if not a:
        return None
    comp = a.get_component_by_class(unreal.PointLightComponent)
    if not comp:
        return {"cls": a.get_class().get_name(), "note": "no pointlight comp"}
    col = comp.light_color
    return {"intensity": round(comp.intensity, 1),
            "color": [col.r, col.g, col.b],
            "attenuation": round(comp.attenuation_radius, 0),
            "enabled": comp.is_visible()}


out["lights"] = {lbl: light_state(lbl) for lbl in
                 ["AIVIDO_KeyWarm", "AIVIDO_FillCool", "AIVIDO_RimGold",
                  "AIVIDO_Practical_AV", "AIVIDO_CoreGlow"]}

sky = by_label("AIVIDO_SkyLight")
if sky:
    sc = sky.get_component_by_class(unreal.SkyLightComponent)
    out["skylight"] = {"intensity": round(sc.intensity, 2) if sc else None}

fog = by_label("AIVIDO_ExponentialFog") or by_label("AIVIDO_Fog")
if not fog:
    for a in actors:
        if a.get_component_by_class(unreal.ExponentialHeightFogComponent):
            fog = a
            break
if fog:
    fc = fog.get_component_by_class(unreal.ExponentialHeightFogComponent)
    out["fog"] = {"label": fog.get_actor_label(), "density": round(fc.fog_density, 4),
                  "inscatter": [round(c, 3) for c in (fc.fog_inscattering_luminance.r,
                                                      fc.fog_inscattering_luminance.g,
                                                      fc.fog_inscattering_luminance.b)] if fc else None}

# Front wall visibility (does it block the outside hero pose?)
front = by_label("AIVIDO_FrontWall")
out["front_wall"] = {"hidden_ed": front.is_hidden_ed() if front else None,
                     "cls": front.get_class().get_name() if front else None}

# Post-process exposure
pp = by_label("AIVIDO_PostProcess")
if pp:
    ppc = pp.get_component_by_class(unreal.PostProcessComponent)
    if ppc:
        s = ppc.settings
        out["postprocess"] = {
            "exposure_method": str(getattr(s, "auto_exposure_method", "?")),
            "exposure_bias": getattr(s, "auto_exposure_bias", None),
            "min_bright": getattr(s, "auto_exposure_min_brightness", None),
            "max_bright": getattr(s, "auto_exposure_max_brightness", None),
            "unbound": getattr(s, "bUnbound", None),
            "volume_enabled": ppc.is_visible(),
        }

__bridge_result__ = out
