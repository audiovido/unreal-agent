"""Probe AividoHQ: character actors, their base Z (floor anchors), and traces at intended prop XYs."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.unreal.unreal_bridge import UnrealBridge  # noqa: E402

BRIDGE = UnrealBridge(host="127.0.0.1", port=6766, timeout=180)

code = r"""
import unreal
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
les.load_level("/Game/Maps/AividoHQ")
world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()

actors = unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor)
chars = []
for a in actors:
    label = a.get_actor_label()
    cls = a.get_class().get_name()
    if a.get_component_by_class(unreal.SkeletalMeshComponent) is not None or "Character" in cls or "Director" in label or "Artist" in label:
        loc = a.get_actor_location()
        chars.append({"label": label, "cls": cls, "loc": [round(loc.x, 1), round(loc.y, 1), round(loc.z, 1)]})

all_static = [a.get_actor_label() for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.StaticMeshActor)][:60]


def trace_descend(x, y):
    z = 100000.0
    hits = []
    for _ in range(4):
        hit = unreal.SystemLibrary.line_trace_single(
            world, unreal.Vector(x, y, z), unreal.Vector(x, y, -2000),
            unreal.TraceTypeQuery.TRACE_TYPE_QUERY1, True, [], unreal.DrawDebugTrace.NONE)
        t = hit.to_tuple()
        if not t[0]:
            hits.append(None)
            break
        iz = t[4].z
        hits.append(round(iz, 1))
        z = iz - 20.0
    return hits


probes = {}
for name, (x, y) in {
    "hub_center": (0, 0), "station_W": (-900, 0), "station_N": (0, 900),
    "station_E": (900, 0), "station_S": (0, -900), "board": (0, 1800),
    "cabinet": (1800, 500), "rack": (1500, 1500), "plant_SW": (-1800, -1700),
    "lantern": (0, 2100), "term_W": (-700, 500), "term_E": (700, -500),
}.items():
    probes[name] = trace_descend(x, y)

__bridge_result__ = {"chars": chars, "static_labels": all_static, "probes": probes}
"""

out = BRIDGE.execute_python(code)
r = out.get("result") or {}
print("CHARACTERS:")
for c in r.get("chars", []):
    print(" ", c["label"], c["cls"], c["loc"])
print("PROBES (iterative descents):")
for k, v in r.get("probes", {}).items():
    print(" ", k, v)
print("STATIC SAMPLE:", r.get("static_labels", [])[:20])
if out.get("error"):
    print("error:", str(out["error"])[:500])
