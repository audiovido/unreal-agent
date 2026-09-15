"""Bridge-side: inventory anim sequences + skeleton bindings."""
import unreal

ar = unreal.AssetRegistryHelpers.get_asset_registry()
rows = {}
for a in ar.get_assets_by_path("/Game/Mannequins", recursive=True):
    cls = str(a.asset_class_path.asset_name)
    if cls != "AnimSequence":
        continue
    try:
        obj = a.get_asset()
        skel = obj.get_editor_property("skeleton")
        skel_name = skel.get_path_name() if skel else None
        # sample play length for idle heuristics
        try:
            rate = obj.get_editor_property("rate_scale")
        except Exception:
            rate = None
        rows.setdefault(skel_name or "NONE", []).append(str(a.asset_name))
    except Exception:
        rows.setdefault("ERR", []).append(str(a.asset_name))

out = {k: sorted(v) for k, v in rows.items()}
out["_counts"] = {k: len(v) for k, v in out.items() if not k.startswith("_")}
__bridge_result__ = out
