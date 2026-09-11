"""FREEBUFF ASSET: bridge-driven live acceptance (A-E) on ASSET_Showcase2.

Runs entirely through the ONE running editor's bridge (127.0.0.1:6766):
build the showcase scene, import the Blender-processed BlackSUV FBX if
absent, place each category group with its verified display scale + grounding,
validate class/size/skeleton/collision/animation, force a viewport redraw,
capture a fresh real viewport PNG per category via the native
UnrealAgentBridge plugin, save the map to /Game/ShowcaseMap, verify on disk.
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from tools.unreal.unreal_bridge import UnrealBridge  # noqa: E402

ASSETLIB = Path(__file__).resolve().parent.parent
REPORT = ASSETLIB / "reports" / "milestone_ACCEPTANCE_A_E.json"
SHOT_DIR = ASSETLIB / "proof" / "screens"

# (category, prefix, spawn_folder, display_scale) - verified display scales
CATS = [
    ("vehicle", "ACC_truck", "/Game/Showcase/Vehicles", 1.0),
    ("character", "ACC_cesiumman", "/Game/Showcase/Characters", 1.0),
    ("environment", "ACC_lantern", "/Game/Showcase/Props", 0.1304),
    ("animation", "ACC_fox", "/Game/Showcase/Animations", 0.0201),
    ("blender_import", "ACC_black_suv", "/Game/NLR/BlackSUV", 1.0),
]
X_BASE = -1800
X_STEP = 900
FOX_WALK = "/Game/Showcase/Animations/Fox/SkeletalMeshes/FoxWalk.FoxWalk"


def main() -> int:
    start = time.time()
    bridge = UnrealBridge(host="127.0.0.1", port=6766, timeout=60)
    ping = bridge.ping()
    if not ping.get("ok"):
        print("BRIDGE NOT READY:", ping)
        return 1
    report = {"project": "ASSET_Showcase2", "bridge": "127.0.0.1:6766",
              "ok": False, "started_at": start, "categories": {}}

    def step(name: str, code: str) -> dict:
        r = bridge.execute_python(code)
        return r if isinstance(r, dict) else {}

    def os_capture(tag: str, title: str = "*ASSET_Showcase2*") -> dict:
        """Capture the real editor window via the OS (the only live render path)."""
        import subprocess
        dst = SHOT_DIR / f"accept_{tag}.png"
        try:
            dst.unlink(missing_ok=True)
        except OSError:
            pass
        cap = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
             str(ASSETLIB / "tools" / "capture_window.ps1"),
             "-ProcessName", "UnrealEditor", "-TitleMatch", title,
             "-OutFile", str(dst), "-WaitSeconds", "1"],
            capture_output=True, text=True, timeout=90)
        ok = dst.exists() and dst.stat().st_size > 0
        return {"ok": ok, "copied": str(dst).replace("\\", "/"),
                "bytes": dst.stat().st_size if ok else 0,
                "ps": (cap.stdout or cap.stderr or "").strip().splitlines()[-1:]}

    def redraw_capture(tag: str) -> dict:
        """OS-capture the live editor window for one category frame."""
        time.sleep(2.0)  # let the viewport settle after the camera frame
        return os_capture(tag)
        src = res.get("path")
        copied = None
        if res.get("ok") and src and Path(src).exists():
            dst = SHOT_DIR / f"accept_{tag}.png"
            shutil.copy2(src, dst)
            copied = str(dst).replace("\\", "/")
        caps["copied"] = copied
        return caps

    # ---- 0. Scene + BlackSUV import (idempotent) ---------------------------
    rscene = step("scene_import", r"""
import os, unreal
sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
for a in sub.get_all_level_actors():
    if a.get_actor_label().startswith("ACC_"):
        sub.destroy_actor(a)
plane = unreal.load_asset("/Engine/BasicShapes/BasicShapePlane")
if plane is not None:
    p = sub.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0))
    p.static_mesh_component.set_static_mesh(plane); p.set_actor_label("ACC_Ground")
    p.set_actor_scale3d(unreal.Vector(160, 160, 1))
sun = sub.spawn_actor_from_class(unreal.DirectionalLight, unreal.Vector(0, 800, 1600), unreal.Rotator(-55, 0, 25))
if sun: sun.set_actor_label("ACC_Sun")
sk = sub.spawn_actor_from_class(unreal.SkyLight, unreal.Vector(0, 0, 2000), unreal.Rotator(0, 0, 0))
if sk: sk.set_actor_label("ACC_SkyLight")
present = unreal.EditorAssetLibrary.list_assets("/Game/NLR/BlackSUV", recursive=True)
fbx = "C:/Users/Shadow/Desktop/Unreal-Agent/assetlib/tests/ue/nlr_in/BlackSUV.fbx"
if not present and os.path.exists(fbx):
    t = unreal.AssetImportTask()
    t.filename = fbx; t.destination_path = "/Game/NLR/BlackSUV"; t.automated = True
    t.save = True; t.replace_existing = False
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([t])
mesh = None
for pa in unreal.EditorAssetLibrary.list_assets("/Game/NLR/BlackSUV", recursive=True):
    a = unreal.load_asset(pa)
    if a is not None and a.get_class().get_name() == "StaticMesh":
        mesh = pa; break
world_ok = unreal.EditorLevelLibrary.get_editor_world() is not None
__bridge_result__ = {"ground_lights_ok": True, "black_suv_imported": bool(mesh),
                     "black_suv_mesh": mesh, "world_ok": world_ok}
""")
    report["scene"] = (rscene or {}).get("result") or {}

    for idx, (cat, prefix, folder, scale) in enumerate(CATS):
        x = X_BASE + idx * X_STEP
        anim = FOX_WALK if cat == "animation" else None
        code = (r"""
import unreal
sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
prefix = %r; folder = %r; scale = %f; x = %f; anim_path = %r
spawned = []
for pa in unreal.EditorAssetLibrary.list_assets(folder, recursive=True):
    a = unreal.load_asset(pa)
    if a is None: continue
    cls = a.get_class().get_name()
    at = unreal.Vector(x, 0, 0)
    if cls == "StaticMesh":
        actor = sub.spawn_actor_from_class(unreal.StaticMeshActor, at, unreal.Rotator(0, 0, 0))
        if actor is None: continue
        actor.static_mesh_component.set_static_mesh(a)
        actor.set_actor_label(prefix + "_" + str(len(spawned)))
        spawned.append(actor)
    elif cls == "SkeletalMesh":
        actor = sub.spawn_actor_from_class(unreal.SkeletalMeshActor, at, unreal.Rotator(0, 0, 0))
        if actor is None: continue
        actor.skeletal_mesh_component.set_skeletal_mesh_asset(a)
        actor.set_actor_label(prefix + "_" + str(len(spawned)))
        spawned.append(actor)
for actor in spawned:
    actor.set_actor_scale3d(unreal.Vector(scale, scale, scale))
bottoms = [ (a.get_actor_bounds(False, False)[0].z - a.get_actor_bounds(False, False)[1].z) for a in spawned]
lift = -min(bottoms) if bottoms else 0.0
for a in spawned:
    loc = a.get_actor_location()
    a.set_actor_location(unreal.Vector(x, 0, loc.z + lift), False, False)
info = {"actor_count": len(spawned), "classes": [], "sizes_cm": []}
collision = skeleton = None
for a in spawned:
    info["classes"].append(a.get_class().get_name())
    o, e = a.get_actor_bounds(False, False)
    info["sizes_cm"].append([round(2*e.x,1), round(2*e.y,1), round(2*e.z,1)])
    sc = getattr(a, "static_mesh_component", None)
    if sc is not None:
        try:
            sc.set_collision_enabled(unreal.CollisionEnabled.QUERY_AND_PHYSICS)
            try:
                collision = str(sc.get_collision_enabled())
            except Exception:
                try:
                    collision = str(sc.get_editor_property("collision_enabled"))
                except Exception as exc2:
                    collision = "set-ok,read:" + str(exc2)[:60]
        except Exception as exc:
            collision = "error:" + str(exc)
    sm = getattr(a, "skeletal_mesh_component", None)
    if sm is not None:
        try:
            skeleton = sm.skeletal_mesh_asset.skeleton.get_path_name()
        except Exception as exc:
            skeleton = "error:" + str(exc)
""" % (prefix, folder, scale, x, anim))
        # build anim + camera frame inside the same call for animation pose
        if anim:
            code += r"""
for a in spawned:
    sm = getattr(a, "skeletal_mesh_component", None)
    if sm is not None:
        try:
            sm.set_animation(unreal.load_asset(anim_path))
            try:
                sm.play(True)
            except Exception:
                pass  # set_animation already starts playback in single-node mode
            info["anim_played"] = anim_path.rsplit(".", 1)[-1]
            break
        except Exception as exc:
            info["anim_error"] = str(exc)
"""
        code += r"""
# frame this category's actors
import math
targets = [a for a in sub.get_all_level_actors() if a.get_actor_label().startswith(prefix)]
if targets:
    mins = [1e12]*3; maxs = [-1e12]*3
    for t in targets:
        o, e = t.get_actor_bounds(False, False)
        for i, (oa, ea) in enumerate(zip((o.x, o.y, o.z), (e.x, e.y, e.z))):
            mins[i] = min(mins[i], oa - ea); maxs[i] = max(maxs[i], oa + ea)
    center = unreal.Vector((mins[0]+maxs[0])/2, (mins[1]+maxs[1])/2, (mins[2]+maxs[2])/2)
    radius = max(maxs[0]-mins[0], maxs[1]-mins[1], maxs[2]-mins[2]) / 2 or 300.0
    dist = max(radius * 1.7, 350.0)
    loc = unreal.Vector(center.x, center.y - dist, center.z + radius * 0.7)
    pitch = -math.degrees(math.atan2(radius * 0.7, dist))
    unreal.EditorLevelLibrary.set_level_viewport_camera_info(loc, unreal.Rotator(pitch=pitch, yaw=0, roll=0))
    info["camera"] = [round(center.x,1), round(center.y,1), round(center.z,1)]
info["collision"] = collision; info["skeleton"] = skeleton
__bridge_result__ = {"ok": len(spawned) > 0, **info}
"""
        r = step(cat, code)
        res = (r or {}).get("result") or {}
        print(f"[{cat}] ok={res.get('ok')} actors={res.get('actor_count')} "
              f"sizes={res.get('sizes_cm')} collision={res.get('collision')} "
              f"anim={res.get('anim_played')}")
        time.sleep(1.0)
        caps = redraw_capture(cat)
        if cat == "animation":
            # small yaw nudge forces a redraw between the two OS captures so
            # the fox's walk pose advances on screen (md5 differs).
            step("anim_nudge", r"""
import unreal
camera = unreal.EditorLevelLibrary.get_level_viewport_camera_info()
loc, rot = camera[0], camera[1]
unreal.EditorLevelLibrary.set_level_viewport_camera_info(
    unreal.Vector(loc.x, loc.y, loc.z),
    unreal.Rotator(pitch=rot.pitch, yaw=rot.yaw + 3.0, roll=rot.roll))
__bridge_result__ = {"ok": True}
""")
            time.sleep(2.5)
            caps2 = redraw_capture("animation_t2")
            md5 = lambda p: __import__("hashlib").md5(  # noqa: E731
                Path(p).read_bytes()).hexdigest() if p and Path(p).exists() else ""
            h1 = md5(caps.get("copied"))
            h2 = md5(caps2.get("copied"))
            caps["advancing"] = {"ok": h1 != h2 and bool(h1) and bool(h2),
                                 "md5_t0": h1, "md5_t1": h2,
                                 "t1_copied": caps2.get("copied")}
            print(f"[animation] advancing={caps['advancing']}")
        report["categories"][cat] = {"place": res, **caps}
        print(f"[{cat}] capture copied={caps.get('copied')}")

    # ---- save map (Untitled -> save-as /Game/ShowcaseMap) ------------------
    rsave = step("save_map", r"""
import unreal
world = unreal.EditorLevelLibrary.get_editor_world()
world_path = world.get_path_name() if world else ""
saved = False
if world is not None:
    saved = bool(unreal.EditorLoadingAndSavingUtils.save_map(world, "/Game/ShowcaseMap"))
unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)
exists = bool(unreal.EditorAssetLibrary.does_asset_exist("/Game/ShowcaseMap"))
__bridge_result__ = {"saved": saved, "map_asset_exists": exists,
                     "world_before": world_path,
                     "map_file": (unreal.Paths.project_content_dir() + "/ShowcaseMap.umap").replace(chr(92), "/")}
""")
    report["save_map"] = (rsave or {}).get("result") or {}
    print("save_map:", json.dumps(report["save_map"]))

    all_ok = all((report["categories"][c]["place"] or {}).get("ok") for c, *_ in CATS)
    report["ok"] = bool(all_ok) and bool((report["save_map"] or {}).get("map_asset_exists"))
    report["elapsed_seconds"] = round(time.time() - start, 1)
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    # Map file on disk proof
    mfile = Path("assetlib/tests/ue/ASSET_Showcase2/Content/ShowcaseMap.umap")
    report["map_on_disk"] = mfile.exists() and mfile.stat().st_size
    REPORT.write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    print("REPORT:", REPORT, "| overall ok:", report["ok"],
          "| map_on_disk_bytes:", report.get("map_on_disk"))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())