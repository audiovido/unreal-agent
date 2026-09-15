"""Probe character meshes + material assignments for Aivido overnight pass."""
import json

ews = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
actors = ews.get_all_level_actors()
out = {"chars": [], "mats": []}

for a in actors:
    label = a.get_actor_label()
    if a.get_class().get_name() == "SkeletalMeshActor":
        smc = a.get_component_by_class(unreal.SkeletalMeshComponent)
        mesh = None
        mats = []
        if smc:
            m = smc.get_editor_property("skeletal_mesh_asset")
            mesh = m.get_path_name() if m else None
            try:
                mats = [mi.get_path_name() for mi in smc.get_material_slot_names()]  # names only
            except Exception:
                pass
        out["chars"].append({
            "label": label,
            "mesh": mesh,
            "slots": [str(s) for s in mats],
            "pos": [round(v, 0) for v in (a.get_actor_location().x, a.get_actor_location().y, a.get_actor_location().z)],
        })
    elif label in ("AIVIDO_Floor", "AIVIDO_RearWall", "AIVIDO_HoloRing", "AIVIDO_CoreOrb",
                   "AIVIDO_WorkerDesk_AV", "AIVIDO_WorkerScreen_AV", "AIVIDO_Prop_Rug",
                   "AIVIDO_Acc_Heidi_Duster", "AIVIDO_Acc_Heidi_HatBrim"):
        smc = a.get_component_by_class(unreal.StaticMeshComponent)
        mats = []
        if smc:
            for i in range(smc.get_num_materials()):
                m = smc.get_material(i)
                mats.append(m.get_path_name() if m else None)
        out["mats"].append({"label": label, "materials": mats})

# available anim assets for mannequin
ar = unreal.AssetRegistryHelpers.get_asset_registry()
anims = []
for a in ar.get_assets_by_path("/Game/Mannequins/Anims", recursive=True):
    cls = str(a.asset_class_path.asset_name)
    if cls in ("AnimSequence", "BlendSpace", "BlendSpace1D"):
        anims.append(str(a.asset_name))
out["anims"] = sorted(anims)

__bridge_result__ = out
