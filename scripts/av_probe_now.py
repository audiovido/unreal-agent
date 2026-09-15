import unreal
ews=unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
out={"count":0,"labels":[],"summary":{},"level":None,"errors":[]}
world=unreal.EditorLevelLibrary.get_editor_world()
out["level"]=str(world.get_path_name()) if world else None
try:
    labs=[a.get_actor_label() for a in ews.get_all_level_actors()]
    out["count"]=len(labs)
    out["labels"]=sorted(labs)[:]
    out["summary"]["env"]=sum(1 for l in labs if l.startswith("UA_E_"))
    out["summary"]["light"]=sum(1 for l in labs if l.startswith("UA_L_"))
    out["summary"]["has_avatar"]="UA_Avatar" in labs
    out["summary"]["has_cam"]="UA_PROD_Camera" in labs
except Exception as e:
    out["errors"].append(str(e)[:200])
# check a material loads
for mp in ("/Game/Studio/Materials/M_Floor_GlossDark.M_Floor_GlossDark","/Game/Studio/Materials/M_Glow_Warm.M_Glow_Warm"):
    try:
        m=unreal.load_asset(mp); out[mp]=None if m is None else m.get_class().get_name()
    except Exception as e:
        out[mp]="ERR:"+str(e)[:60]
__bridge_result__=out
