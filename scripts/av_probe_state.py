
import unreal
ews = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
out=[]
for a in ews.get_all_level_actors():
    lab=a.get_actor_label()
    if lab.startswith("UA_L_") or lab=="UA_PROD_Camera" or lab=="UA_Avatar" or lab=="UA_PP_Master":
        d={"label":lab,"class":a.get_class().get_name()}
        r=a.get_actor_rotation(); l=a.get_actor_location()
        d["rot"]=[round(r.pitch,1),round(r.yaw,1)]; d["loc"]=[round(l.x,1),round(l.y,1),round(l.z,1)]
        out.append(d)
__bridge_result__=out
