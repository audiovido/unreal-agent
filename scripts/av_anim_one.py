"""Bridge-side: deep-inspect one ERR-bucket anim asset."""
import unreal

out = {}
p = "/Game/Mannequins/Anims/Unarmed/Walk/MF_Unarmed_Walk_Fwd"
a = unreal.load_asset(p)
out["loaded"] = a is not None
if a:
    out["class"] = a.get_class().get_name()
    for prop in ("skeleton", "skeleton_guid", "rate_scale", "sequence_length"):
        try:
            v = a.get_editor_property(prop)
            out[prop] = v.get_path_name() if hasattr(v, "get_path_name") else v
        except Exception as e:
            out[prop + "_err"] = str(e)[:80]
    # Fallback: probe path via walk_asset for skeleton type object
    try:
        out["props_sample"] = [p2 for p2 in dir(a) if "skel" in p2.lower()][:8]
    except Exception:
        pass

# also: what skeleton objects exist in the project at all?
ar = unreal.AssetRegistryHelpers.get_asset_registry()
skels = []
for row in ar.get_assets_by_class(unreal.TopLevelAssetPath("/Script/Engine", "Skeleton"), True):
    skels.append(str(row.package_name))
out["skeleton_assets"] = skels

# and SkeletalMesh -> Skeleton binding of our mannequin mesh
mesh = unreal.load_asset("/Game/Mannequins/Meshes/SKM_Manny_Simple")
try:
    sk = mesh.get_editor_property("skeleton")
    out["manny_skeleton"] = sk.get_path_name() if sk else None
    out["manny_skel_class"] = sk.get_class().get_name() if sk else None
except Exception as e:
    out["manny_skel_err"] = str(e)[:100]

__bridge_result__ = out
