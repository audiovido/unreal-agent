"""Diagnose prop actor bounds: list components + meshes + comp bounds per W3P actor."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.unreal.unreal_bridge import UnrealBridge  # noqa: E402

BRIDGE = UnrealBridge(host="127.0.0.1", port=6766, timeout=120)

code = r"""
import unreal
world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
report = []
for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor):
    label = a.get_actor_label()
    if not label.startswith("W3P_") or "Lantern" in label:
        continue
    comps = []
    for c in a.get_components_by_class(unreal.StaticMeshComponent):
        sm = c.get_editor_property("static_mesh")
        if sm is None:
            comps.append({"comp": c.get_name(), "mesh": None, "world_z_min": None, "world_z_max": None})
            continue
        b = sm.get_bounds()
        wt = c.get_world_transform()
        zmin, zmax = 1e9, -1e9
        for sx in (-1, 1):
            for sy in (-1, 1):
                for sz in (-1, 1):
                    corner = unreal.Vector(b.origin.x + sx * b.box_extent.x,
                                           b.origin.y + sy * b.box_extent.y,
                                           b.origin.z + sz * b.box_extent.z)
                    wz = wt.transform_location(corner).z
                    zmin = min(zmin, wz)
                    zmax = max(zmax, wz)
        comps.append({"comp": c.get_name(), "mesh": str(sm.get_name()),
                      "world_z_min": round(zmin, 2), "world_z_max": round(zmax, 2)})
    origin, extent = a.get_actor_bounds(False)
    report.append({"label": label, "actor_z_min": round(origin.z - extent.z, 2), "comps": comps})
    break
__bridge_result__ = report[0] if report else {"error": "no W3P actor"}
"""

out = BRIDGE.execute_python(code)
print("ok:", out.get("ok"))
print(json.dumps(out.get("result"), indent=1, default=str))
if out.get("error"):
    print("error:", out["error"][:800])
