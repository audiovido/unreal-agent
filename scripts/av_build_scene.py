import unreal, traceback, math
out = {"actors": [], "errors": []}
ews = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
EPS = unreal.EditorLevelLibrary
CUBE = "/Engine/BasicShapes/Cube.Cube"
CYL  = "/Engine/BasicShapes/Cylinder.Cylinder"

def mk_actor(cls, label, loc, rot=(0,0,0), scale=(1,1,1)):
    a = ews.spawn_actor_from_class(cls, unreal.Vector(*loc), unreal.Rotator(*rot))
    a.set_actor_scale3d(unreal.Vector(*scale)); a.set_actor_label(label); return a

def setmat(actor, mesh, material):
    comp = actor.static_mesh_component
    m = unreal.load_asset(mesh)
    if m: comp.set_static_mesh(m)
    mm = unreal.load_asset(material)
    if mm: comp.set_material(0, mm)

def box(label, loc, scale, material, rot=(0,0,0)):
    a = mk_actor(unreal.StaticMeshActor, label, loc, rot=rot, scale=scale)
    setmat(a, CUBE, material); out["actors"].append([label,"box"])

def cyl(label, loc, scale, material, rot=(0,0,0)):
    a = mk_actor(unreal.StaticMeshActor, label, loc, rot=rot, scale=scale)
    setmat(a, CYL, material); out["actors"].append([label,"cyl"])

def look(at, target):
    try:
        return unreal.KismetMathLibrary.find_look_at_rotation(unreal.Vector(*at), unreal.Vector(*target))
    except Exception:
        dx,dy,dz = target[0]-at[0], target[1]-at[1], target[2]-at[2]
        ln = math.sqrt(dx*dx+dy*dy+dz*dz); ln=max(ln,0.0001)
        yaw = math.degrees(math.atan2(dy, dx))
        pitch = -math.degrees(math.asin(max(-1.0,min(1.0,dz/ln))))
        return unreal.Rotator(pitch, yaw, 0.0)

def setv(obj, value, candidates):
    for cand in candidates:
        try:
            obj.set_editor_property(cand, value); return cand
        except Exception:
            continue
    return None

def light(cls, label, loc, lcomp=None, props=None):
    a = mk_actor(cls, label, loc)
    comp = None
    if lcomp:
        try: comp = a.get_editor_property(lcomp)
        except Exception: comp = None
    (props or {}).setdefault("errors", [])  # placeholder
    return a, comp

# Just apply props tolerant across actor+component
def apply(a, comp, props, label):
    targets = [comp] if comp is not None else []
    objs = [a] + targets
    applied = {}
    for key, (value, cands) in props.items():
        okname = None
        for obj in objs:
            okname = setv(obj, value, cands)
            if okname is not None: break
        if okname is None:
            out["errors"].append(label+":"+key+"|none-ok")
        else:
            applied[key] = okname
    return applied

try:
    for a in EPS.get_all_level_actors():
        lab = a.get_actor_label()
        if lab.startswith("UA_E_") or lab.startswith("UA_L_") or lab.startswith("UA_Env"):
            ews.destroy_actor(a)
except Exception as e:
    out["errors"].append("preclean:"+str(e)[:80])

try:
    # ENVIRONMENT
    box("UA_E_Floor", (0,-30,-2), (70,70,0.06), "/Game/Studio/Materials/M_Floor_GlossDark.M_Floor_GlossDark")
    box("UA_E_BackWall", (0,-360,190), (24,0.4,4.6), "/Game/Studio/Materials/M_Wall_Dark.M_Wall_Dark")
    box("UA_E_WingL", (-1050,-180,190), (10,0.4,4.6), "/Game/Studio/Materials/M_Wall_Dark.M_Wall_Dark", rot=(0,-35,0))
    box("UA_E_WingR", (1050,-180,190), (10,0.4,4.6), "/Game/Studio/Materials/M_Wall_Dark.M_Wall_Dark", rot=(0,35,0))
    box("UA_E_Ceiling", (0,-80,430), (30,18,0.3), "/Game/Studio/Materials/M_Wall_Dark.M_Wall_Dark")
    box("UA_E_CeilStrip", (0,-70,425), (10,5,0.05), "/Game/Studio/Materials/M_Glow_Warm.M_Glow_Warm")
    box("UA_E_StripL", (-160,-360,190), (0.14,0.1,2.6), "/Game/Studio/Materials/M_Glow_Cyan.M_Glow_Cyan")
    box("UA_E_StripR", (160,-360,190), (0.14,0.1,2.6), "/Game/Studio/Materials/M_Glow_Cyan.M_Glow_Cyan")
    box("UA_E_BaseLine", (0,-359,6), (20,0.06,0.12), "/Game/Studio/Materials/M_Trim_Metal.M_Trim_Metal")
    box("UA_E_ColumnL", (-240,40,220), (1.2,0.9,4.4), "/Game/Studio/Materials/M_Trim_Metal.M_Trim_Metal")
    box("UA_E_ColumnR", (380,40,220), (1.2,0.9,4.4), "/Game/Studio/Materials/M_Trim_Metal.M_Trim_Metal")
    box("UA_E_CeilingR", (-420,-80,430), (4,18,0.3), "/Game/Studio/Materials/M_Wall_Dark.M_Wall_Dark")
    box("UA_E_CeilingL", (420,-80,430), (4,18,0.3), "/Game/Studio/Materials/M_Wall_Dark.M_Wall_Dark")
    cyl("UA_E_Stage", (0,60,-9), (1.7,1.7,0.1), "/Game/Studio/Materials/M_Stage_Dark.M_Stage_Dark")
    cyl("UA_E_StageRing", (0,60,-5), (1.95,1.95,0.05), "/Game/Studio/Materials/M_Glow_Soft.M_Glow_Soft")

    # LIGHTING
    sky, skyc = light(unreal.SkyLight, "UA_L_Sky", (0,0,300), "sky_light_component")
    apply(sky, skyc, {
        "intensity": (0.5, ["intensity","sky_intensity","indirect_lighting_intensity"]),
        "sky_color": (unreal.LinearColor(0.12,0.14,0.2), ["sky_color","light_color"]),
    }, "UA_L_Sky")

    key, keyc = light(unreal.RectLight, "UA_L_Key", (170,270,430), "rect_light_component")
    key.set_actor_rotation(look((170,270,430),(0,60,120)), False)
    apply(key, keyc, {
        "intensity": (30000.0, ["intensity","intensity_units_value","atlas_light_intensity"]),
        "light_color": (unreal.LinearColor(1.0,0.85,0.6), ["light_color","color","diffuse_color"]),
        "width": (320.0, ["source_width","rect_width","width"]),
        "height": (220.0, ["source_height","rect_height","height"]),
        "radius": (15.0, ["source_radius","radius"]),
    }, "UA_L_Key")

    fill, fillc = light(unreal.SpotLight, "UA_L_Fill", (-300,290,200), "spot_light_component")
    fill.set_actor_rotation(look((-300,290,200),(0,60,110)), False)
    apply(fill, fillc, {
        "intensity": (15000.0, ["intensity"]),
        "light_color": (unreal.LinearColor(0.9,0.95,1.0), ["light_color"]),
        "inner": (40.0, ["inner_cone_angle"]), "outer": (70.0, ["outer_cone_angle"]),
    }, "UA_L_Fill")

    rim, rimc = light(unreal.SpotLight, "UA_L_Rim", (0,-200,400), "spot_light_component")
    rim.set_actor_rotation(look((0,-200,400),(0,60,150)), False)
    apply(rim, rimc, {
        "intensity": (22000.0, ["intensity"]),
        "light_color": (unreal.LinearColor(0.55,0.75,1.0), ["light_color"]),
        "inner": (25.0, ["inner_cone_angle"]), "outer": (55.0, ["outer_cone_angle"]),
    }, "UA_L_Rim")

    cove, covec = light(unreal.PointLight, "UA_L_Cove", (0,-60,360), "point_light_component")
    apply(cove, covec, {"intensity": (5000.0, ["intensity"]), "light_color": (unreal.LinearColor(1.0,0.92,0.78), ["light_color"])}, "UA_L_Cove")
    sL, sLc = light(unreal.PointLight, "UA_L_StripL", (-160,-330,190), "point_light_component")
    apply(sL, sLc, {"intensity": (2500.0, ["intensity"]), "light_color": (unreal.LinearColor(0.4,0.8,1.0), ["light_color"])}, "UA_L_StripL")
    sR, sRc = light(unreal.PointLight, "UA_L_StripR", (160,-330,190), "point_light_component")
    apply(sR, sRc, {"intensity": (2500.0, ["intensity"]), "light_color": (unreal.LinearColor(0.4,0.8,1.0), ["light_color"])}, "UA_L_StripR")

    for _,_,lab in [("a","b","UA_L_Sky")]:
        pass

    # POST PROCESS
    pp = mk_actor(unreal.PostProcessVolume, "UA_PP_Master", (0,0,0))
    pp.set_editor_property("unbound", True); pp.set_editor_property("priority", 100.0)
    s = pp.get_editor_property("settings")
    setters = {
        "bloom_intensity": 0.6, "bloom_threshold": 1.0, "bloom_1_size": 1.5,
        "auto_exposure_method": unreal.AutoExposureMethod.AEM_HISTOGRAM,
        "auto_exposure_bias": 1.6, "auto_exposure_min_brightness": 0.2, "auto_exposure_max_brightness": 6.0,
        "auto_exposure_speed_up": 1.0, "auto_exposure_speed_down": 1.0,
        "vignette_intensity": 0.24, "film_grain_intensity": 0.0, "motion_blur_amount": 0.0,
    }
    for k,v in setters.items():
        try: s.set_editor_property(k, v)
        except Exception as e: out["errors"].append("pp:"+k+"|"+str(e)[:50])
    out["actors"].append(["UA_PP_Master","PostProcessVolume"])

    # CAMERA
    cam = None
    for a in EPS.get_all_level_actors():
        if a.get_actor_label() == "UA_PROD_Camera": cam = a; break
    if cam is None: cam = mk_actor(unreal.CameraActor, "UA_PROD_Camera", (200,300,165))
    cam.set_actor_location(unreal.Vector(200,300,165), False, False)
    cam.set_actor_rotation(l
