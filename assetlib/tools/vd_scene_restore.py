"""Visual-Director scene restore + framing (bridge 6766, ASSET_Showcase2).

Re-materializes the graduated modern street scene from the accepted recipe
(building 9x MB_* at ~x=2400 scale 2.5; black SUV; walking fox; lanterns) on
the current map, then frames the editor viewport for a high-res screenshot.
Reversible: pre-change map backed up by the caller. All placements use the
proven spawn/ground primitives (ue_showcase_build.py + tool-gap batches).
"""
import json
import os
import sys
from typing import Any, Dict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools", "unreal"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from unreal_bridge import UnrealBridge  # noqa: E402

BUILDING_FOLDER = "/Game/Showcase/Buildings"
SUV_FOLDER = "/Game/NLR/BlackSUV"
FOX_MESH = "/Game/Showcase/Animations/Fox/SkeletalMeshes/Fox.Fox"
FOX_WALK = "/Game/Showcase/Animations/Fox/SkeletalMeshes/FoxWalk.FoxWalk"
LANTERN_FOLDER = "/Game/Showcase/Props/Lantern/StaticMeshes"
CINE = "VD"


def main() -> int:
    b = UnrealBridge("127.0.0.1", 6766)
    code = f"""
import unreal, math, os, json
sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
ell = unreal.EditorLevelLibrary
world = unreal.EditorLevelLibrary.get_editor_world()

# sweep VD/MB/ACC leftovers from previous runs
for a in list(sub.get_all_level_actors()):
    lab = a.get_actor_label()
    if lab.startswith("{CINE}") or lab.startswith("MB_") or lab.startswith("VD_"):
        sub.destroy_actor(a)

def static(path, label, at, scale=1.0):
    a = sub.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(*at), unreal.Rotator(0,0,0))
    if a is None: return None
    a.static_mesh_component.set_static_mesh(unreal.load_asset(path))
    a.set_actor_label(label)
    a.set_actor_scale3d(unreal.Vector(scale, scale, scale))
    return a

def ground(a, x, y):
    o, e = a.get_actor_bounds(False, False)
    bot = o.z - e.z
    a.set_actor_location(unreal.Vector(x, y, -bot), False, False)

def place_folder(folder, label, at, scale, only_mb=False):
    paths = sorted(unreal.EditorAssetLibrary.list_assets(folder, recursive=True, include_folder=False))
    spawned = []
    for p in paths:
        asset = unreal.load_asset(p)
        if asset is None or asset.get_class().get_name() != "StaticMesh":
            continue
        nm = p.rsplit("/",1)[-1].split(".")[0]
        if only_mb and not nm.lower().startswith("mb_"):
            continue
        a = static(p, f"{{label}}_{{len(spawned)}}", at, scale)
        if a is not None: spawned.append(a)
    if not spawned: return spawned
    bottoms = []
    for a in spawned:
        o, e = a.get_actor_bounds(False, False)
        bottoms.append(o.z - e.z)
    lift = -min(bottoms)
    for a in spawned:
        loc = a.get_actor_location()
        a.set_actor_location(unreal.Vector(loc.x, loc.y, loc.z + lift), False, False)
    return spawned

report = {{"placed": []}}

# 1. ground plane
plane = sub.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(0,0,0), unreal.Rotator(0,0,0))
plane.static_mesh_component.set_static_mesh(unreal.load_asset("/Engine/BasicShapes/BasicShapePlane"))
plane.set_actor_label("VD_Ground")
plane.set_actor_scale3d(unreal.Vector(200, 200, 1))
report["placed"].append({{"group": "ground", "actors": 1}})

# 2. modern building: the 9 composed mb_* pieces, scale 2.5 (accepted recipe)
mb = place_folder("{BUILDING_FOLDER}", "MB", (2400, 0, 0), 2.5, only_mb=True)
report["placed"].append({{"group": "modern_building", "actors": len(mb)}})

# 3. black SUV (Blender-tinted import, all parts)
suv = place_folder("{SUV_FOLDER}", "SUV", (1500, -100, 0), 1.0)
report["placed"].append({{"group": "black_suv", "actors": len(suv)}})

# 4. lantern street props on the sidewalk
lan1 = place_folder("{LANTERN_FOLDER}", "VD_Lantern", (2050, -160, 0), 1.0)
report["placed"].append({{"group": "lantern", "actors": len(lan1)}})

# 5. walking fox on the street (FoxWalk, single-node anim)
fox = sub.spawn_actor_from_class(unreal.SkeletalMeshActor, unreal.Vector(900, 120, 0), unreal.Rotator(0, 180, 0))
fox.skeletal_mesh_component.set_skeletal_mesh_asset(unreal.load_asset("{FOX_MESH}"))
fox.set_actor_label("VD_Fox")
ground(fox, 900, 120)
fox.skeletal_mesh_component.set_animation(unreal.load_asset("{FOX_WALK}"))
try:
    fox.skeletal_mesh_component.set_editor_property("animation_mode", unreal.AnimationMode.ANIMATION_SINGLE_NODE)
except Exception as exc:
    report["fox_mode_err"] = str(exc)[:120]
report["placed"].append({{"group": "fox", "actors": 1, "anim": "FoxWalk"}})

# lights present from acceptance (VD_Sun/VD_SkyLight aliases not needed; reuse ACC_)
report["lights"] = [a.get_actor_label() for a in sub.get_all_level_actors()
                    if a.get_actor_label() in ("ACC_Sun", "ACC_SkyLight")]

# cleanup stale ACC category actors far off the stage (kept away from framing)
for a in list(sub.get_all_level_actors()):
    if a.get_actor_label().startswith("ACC_") and a.get_actor_label() not in ("ACC_Sun", "ACC_SkyLight", "ACC_Ground"):
        sub.destroy_actor(a)

# save
saved = unreal.EditorAssetLibrary.save_asset("/Game/ShowcaseMap")
ell.save_current_level()
report["saved"] = saved

# frame the whole street: building..fox span
targets = [a for a in sub.get_all_level_actors() if a.get_actor_label().startswith(("MB_", "SUV_", "VD_Fox", "VD_Lantern"))]
mins = [1e12]*3; maxs = [-1e12]*3
for t in targets:
    o, e = t.get_actor_bounds(False, False)
    for i,(oa,ea) in enumerate(zip((o.x,o.y,o.z),(e.x,e.y,e.z))):
        mins[i]=min(mins[i],oa-ea); maxs[i]=max(maxs[i],oa+ea)
center = unreal.Vector((mins[0]+maxs[0])/2, (mins[1]+maxs[1])/2, (mins[2]+maxs[2])/2)
radius = max(maxs[0]-mins[0], maxs[1]-mins[1], maxs[2]-mins[2])/2
dist = max(radius*1.7, 200.0)
loc = unreal.Vector(center.x, center.y - dist, center.z + radius*0.62)
pitch = -math.degrees(math.atan2(radius*0.62, dist))
ell.set_level_viewport_camera_info(loc, unreal.Rotator(pitch=pitch, yaw=0, roll=0))
report["frame"] = {{"center": [round(v,1) for v in (center.x, center.y, center.z)],
                     "radius": round(radius,1), "cam": [round(v,1) for v in (loc.x, loc.y, loc.z)]}}

__bridge_result__ = report
"""
    r = b.execute_python(code)
    body = r.get("result")
    print(json.dumps(body, indent=1)[:2400])
    return 0 if (body or {}).get("saved") else 1


if __name__ == "__main__":
    sys.exit(main())
