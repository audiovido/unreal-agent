"""Probe line trace return shape."""
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
hit = unreal.SystemLibrary.line_trace_single(world, unreal.Vector(0, 0, 5000), unreal.Vector(0, 0, -1000), unreal.TraceTypeQuery.TRACE_TYPE_QUERY1, True, [], unreal.DrawDebugTrace.NONE)
t = hit.to_tuple()
desc = []
for item in t:
    if isinstance(item, unreal.HitResult):
        d = item.to_tuple()
        loc = d[1].location if (d[1] is not None and len(d) > 1) else None
        desc.append({"hit": str(d[0]), "loc_z": round(loc.z, 2) if loc else None})
    else:
        desc.append(item)
__bridge_result__ = {"n": len(t), "t": desc, "level": world.get_path_name()}
"""

out = BRIDGE.execute_python(code)
print(json.dumps(out.get("result"), indent=1))
if out.get("error"):
    print("error:", str(out["error"])[:500])
