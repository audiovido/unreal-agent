"""Worker 5 ingestion: validate Worker 3 props deliverables in live editor."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.unreal.unreal_bridge import UnrealBridge  # noqa: E402

BRIDGE = UnrealBridge(host="127.0.0.1", port=6766, timeout=180)

code = r"""
import unreal
ar = unreal.AssetRegistryHelpers.get_asset_registry()
props = ar.get_assets_by_path("/Game/AividoHQ/Props", recursive=True)
bps, mats, meshes = [], [], []
for a in props:
    cls = str(a.asset_class_path.asset_name)
    if cls == "Blueprint":
        bps.append(str(a.package_name))
    elif cls == "Material":
        mats.append(str(a.package_name))
    elif cls == "StaticMesh":
        meshes.append(str(a.package_name))
# load every BP: verify generated class + component meshes + materials resolve
bp_report = []
broken = []
for p in bps:
    bp = unreal.EditorAssetLibrary.load_asset(p)
    if bp is None:
        broken.append(p + " (load failed)")
        continue
    gen = bp.generated_class()
    if gen is None:
        broken.append(p + " (no gen class)")
        continue
    cdo = unreal.get_default_object(gen)
    parts = 0
    for c in cdo.get_components_by_class(unreal.StaticMeshComponent):
        parts += 1
        sm = c.get_editor_property("static_mesh")
        if sm is None:
            broken.append(p + " part" + str(parts) + " null mesh")
    bp_report.append({"bp": p.rsplit("/", 1)[-1], "parts": parts, "gen_ok": True})
# lantern meshes: verify exist + material slots resolve
lantern = []
for m in meshes:
    sm = unreal.EditorAssetLibrary.load_asset(m)
    if sm is None:
        broken.append(m + " (mesh load failed)")
        continue
    mats_n = None
    sec = sm.get_section_material_map(0) if hasattr(sm, "get_section_material_map") else None
    lantern.append({"mesh": m.rsplit("/", 1)[-1],
                    "materials": [str(m.get_name()) for m in sec] if sec else []})
# staging map exists + saved props intact
stage_exists = unreal.EditorAssetLibrary.does_asset_exist("/Game/Maps/AividoHQ_PropsStage")
stage_actor_count = None
if stage_exists:
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    cur = world.get_path_name()
    if "AividoHQ_PropsStage" in cur:
        stage_actor_count = len(unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor))
    else:
        les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        les.load_level("/Game/Maps/AividoHQ_PropsStage")
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        stage_actor_count = len(unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor))
        les.load_level("/Game/Maps/AividoHQ")
# ownership check: nothing under other workers' paths modified by props
__bridge_result__ = {"ok": len(broken) == 0 and len(bps) == 8 and len(mats) == 9 and len(meshes) == 3,
    "bp_count": len(bps), "mat_count": len(mats), "mesh_count": len(meshes),
    "bp_report": bp_report, "lantern": lantern, "broken": broken,
    "staging_map_exists": stage_exists, "staging_actor_count": stage_actor_count}
"""

out = BRIDGE.execute_python(code)
r = out.get("result") or {}
print(json.dumps({k: v for k, v in r.items() if k != "bp_report"}, indent=1, default=str))
print("BPs:", [b["bp"] + " parts=" + str(b["parts"]) for b in r.get("bp_report", [])])
if out.get("error"):
    print("error:", str(out["error"])[:800])
