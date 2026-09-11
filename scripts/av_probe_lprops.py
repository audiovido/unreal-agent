import unreal, traceback
out = {}
def props_of(obj):
    try: return list(obj.get_property_names())
    except Exception as e: return ["ERR:"+str(e)[:100]]
# util to get a fresh actor's component
def comp_of(cls, lcomp):
    ews = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    a = ews.spawn_actor_from_class(cls, unreal.Vector(999,999,999), unreal.Rotator(0,0,0))
    c = a.get_editor_property(lcomp) if hasattr(a, lcomp) else None
    name = c.get_class().get_name() if c else None
    ps = props_of(c) if c else []
    ews.destroy_actor(a)
    return (name, ps)
for cls, lcomp in [(unreal.SkyLight,"sky_light_component"),(unreal.RectLight,"rect_light_component"),(unreal.SpotLight,"spot_light_component"),(unreal.PointLight,"point_light_component"),(unreal.CameraActor,"camera_component")]:
    try:
        nm, ps = comp_of(cls, lcomp)
        # filter for relevant keywords
        kw = [p for p in ps if any(k in p.lower() for k in ("intens","color","temper","width","height","radius","cone","source","atlas","capture_source","auto","exposure","bias","bloom","vignette"))]
        out[cls.__name__] = {"comp_name": nm, "relevant": kw[:40]}
    except Exception as e:
        out[cls.__name__] = {"ERR": str(e)[:120]}
out["AEM"] = [a for a in dir(unreal.AutoExposureMethod) if not a.startswith("_")]
out["ExpMethod"] = [a for a in dir(unreal) if "Exposure" in a]
__bridge_result__ = out
