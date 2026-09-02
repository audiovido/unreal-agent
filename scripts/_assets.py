import unreal, traceback
out = {"skel_meshes": [], "asses": [], "avatar": {}}
try:
    reg = unreal.AssetRegistryHelpers.get_asset_registry()
    # avatar mesh
    ews = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    for a in ews.get_all_level_actors():
        if a.get_actor_label().startswith("UA_Avatar"):
            try:
                smc = [c for c in a.get_components_by_class(unreal.SkeletalMeshComponent)]
                out["avatar"]["components"] = len(smc)
                if smc:
                    sm = smc[0].get_editor_property("skeletal_mesh_asset")
                    out["avatar"]["mesh"] = None if sm is None else str(sm.get_path_name())
                    anim = smc[0].get_editor_property("anim_class")
                    out["avatar"]["anim_class"] = None if anim is None else str(anim.get_path_name())
            except Exception:
                out["avatar"]["err"] = traceback.format_exc()
    # assets containing SkeletalMesh or MetaHuman-ish, all skeletal meshes in project
    paths = reg.get_assets_by_class("SkeletalMesh")
    out["skel_meshes"] = sorted(set(p.package_name + "." + p.asset_name for p in paths))[:100]
except Exception:
    out["error"] = traceback.format_exc()
__bridge_result__ = out
